"""Authentication API routes: app signup/login and Google OAuth."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

import auth_service
import google_service
from config import settings
from logger import logger
from models import (
    AuthResponse,
    CreateBookmarkRequest,
    CreateHistoryRequest,
    GoogleAuthUrlResponse,
    GoogleCallbackRequest,
    LoginRequest,
    SignupRequest,
    UserProfile,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

_CALLBACK_HTML_PATH = Path(__file__).resolve().parent / "templates" / "google_callback.html"


def _db():
    from main import get_db_connection
    return get_db_connection


@router.post("/signup", response_model=AuthResponse)
async def signup(request: SignupRequest):
    """Register a new user with email and password (app login)."""
    try:
        user = await auth_service.create_app_user(
            _db(), request.email, request.password, request.full_name
        )
        bookmarks, history = await auth_service.get_user_auth_data(_db(), user["id"])
        return auth_service.build_auth_response(
            user, bookmarks=bookmarks, history=history, message="Signup successful"
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Signup failed: {exc}")
        raise HTTPException(status_code=500, detail="Signup failed") from exc


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """Login with email and password. Requires prior signup."""
    try:
        user = await auth_service.authenticate_app_user(_db(), request.email, request.password)
        bookmarks, history = await auth_service.get_user_auth_data(_db(), user["id"])
        return auth_service.build_auth_response(
            user, bookmarks=bookmarks, history=history, message="Login successful"
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Login failed: {exc}")
        raise HTTPException(status_code=500, detail="Login failed") from exc


@router.get("/google/url", response_model=GoogleAuthUrlResponse)
async def get_google_auth_url():
    """
    Get Google OAuth authorization URL (step 1: identity only).

    Google does not allow mixing Data Portability scopes with openid/email/profile.
    After identity login, the callback returns a second URL for Chrome data consent.
    """
    if not google_service.is_google_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI in .env",
        )

    authorization_url, state = google_service.build_google_auth_url(flow="identity")
    return {
        "status_code": 200,
        "success": True,
        "message": "Open this URL in a browser to authenticate with Google (identity step)",
        "authorization_url": authorization_url,
        "state": state,
    }


@router.get("/google/callback", response_class=HTMLResponse, include_in_schema=True)
async def google_callback_page():
    """
    Browser redirect landing page for Google OAuth.

    Set GOOGLE_REDIRECT_URI to this URL (e.g. http://localhost:8000/auth/google/callback).
    Google redirects here with ?code=...; the page then calls POST /auth/google/callback.
    """
    if not _CALLBACK_HTML_PATH.exists():
        raise HTTPException(status_code=500, detail="Google callback page template is missing")
    return HTMLResponse(content=_CALLBACK_HTML_PATH.read_text(encoding="utf-8"))


@router.post("/google/callback", response_model=AuthResponse)
async def google_callback(request: GoogleCallbackRequest):
    """
    Complete Google OAuth in two steps:

    1) Identity (`openid email profile`) → create user + JWT, return portability URL
    2) Data Portability (Chrome bookmarks/history only) → sync and return data
    """
    if not google_service.is_google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    try:
        # Exchange first so a failed token request does not consume OAuth state
        token_data = await google_service.exchange_code_for_tokens(request.code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")
        granted_scope = token_data.get("scope") or ""

        state_info = google_service.pop_oauth_state(request.state)
        flow = (state_info or {}).get("flow")

        # Fallback if state was lost (server restart): detect by granted scopes
        if not flow:
            if "dataportability" in granted_scope:
                flow = "portability"
            else:
                flow = "identity"

        # -------- Step 1: identity --------
        if flow == "identity":
            userinfo = await google_service.fetch_google_userinfo(access_token)
            google_sub = userinfo.get("sub")
            email = userinfo.get("email")
            if not google_sub or not email:
                raise HTTPException(
                    status_code=400,
                    detail="Google account missing required profile information",
                )

            user = await auth_service.upsert_google_user(
                _db(),
                google_sub=google_sub,
                email=email,
                full_name=userinfo.get("name"),
                profile_picture=userinfo.get("picture"),
            )

            portability_url, _ = google_service.build_google_auth_url(
                flow="portability",
                user_id=user["id"],
            )

            return auth_service.build_auth_response(
                user,
                bookmarks=[],
                history=[],
                google_sync={
                    "status": "pending_consent",
                    "message": "Identity OK. Open authorization_url to grant Chrome bookmarks/history access.",
                },
                message="Google identity verified. Continue to grant Chrome data access.",
                needs_portability_consent=True,
                authorization_url=portability_url,
                step="identity",
            )

        # -------- Step 2: data portability --------
        if flow == "portability":
            user_id = (state_info or {}).get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=400,
                    detail="Missing portability session. Start again from GET /auth/google/url",
                )

            user = await auth_service.get_user_by_id(_db(), int(user_id))
            if not user:
                raise HTTPException(status_code=404, detail="User not found for portability sync")

            await auth_service.store_oauth_tokens(
                _db(),
                user_id=user["id"],
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=expires_in,
                scopes=settings.google_oauth_scopes_portability,
            )

            sync_result = await google_service.sync_google_bookmarks_and_history(
                _db(), user["id"], access_token, auth_service
            )

            bookmarks = await auth_service.get_user_bookmarks(_db(), user["id"])
            history = await auth_service.get_user_history(_db(), user["id"])

            return auth_service.build_auth_response(
                user,
                bookmarks=bookmarks,
                history=history,
                google_sync=sync_result,
                message="Google login successful",
                needs_portability_consent=False,
                authorization_url=None,
                step="complete",
            )

        raise HTTPException(status_code=400, detail=f"Unknown OAuth flow: {flow}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Google OAuth callback failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Google login failed: {exc}") from exc


@router.get("/me", response_model=AuthResponse)
async def get_me(current_user: UserProfile = Depends(auth_service.get_current_user)):
    """Get the currently authenticated user's profile."""
    user = await auth_service.get_user_by_id(_db(), current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    bookmarks = await auth_service.get_user_bookmarks(_db(), user["id"])
    history = await auth_service.get_user_history(_db(), user["id"])

    return auth_service.build_auth_response(
        user,
        bookmarks=bookmarks,
        history=history,
        message="Profile retrieved",
    )


@router.get("/bookmarks")
async def list_bookmarks(
    current_user: UserProfile = Depends(auth_service.get_current_user),
    source: Optional[Literal["app", "google"]] = Query(None, description="Filter by source"),
    limit: int = Query(100, ge=1, le=500),
):
    """List bookmarks for the authenticated user."""
    bookmarks = await auth_service.get_user_bookmarks(_db(), current_user.id, limit=limit, source=source)
    return {
        "status_code": 200,
        "success": True,
        "message": "Bookmarks retrieved",
        "data": bookmarks,
    }


@router.post("/bookmarks")
async def add_bookmark(
    request: CreateBookmarkRequest,
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """Save a bookmark for the authenticated app user."""
    bookmark = await auth_service.create_app_bookmark(
        _db(),
        user_id=current_user.id,
        url=request.url,
        title=request.title,
        folder=request.folder,
    )
    return {
        "status_code": 201,
        "success": True,
        "message": "Bookmark saved",
        "data": bookmark,
    }


@router.delete("/bookmarks/{bookmark_id}")
async def remove_bookmark(
    bookmark_id: int,
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """Delete an app bookmark owned by the authenticated user."""
    deleted = await auth_service.delete_app_bookmark(_db(), current_user.id, bookmark_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Bookmark not found or not deletable")
    return {
        "status_code": 200,
        "success": True,
        "message": "Bookmark deleted",
    }


@router.get("/history")
async def list_history(
    current_user: UserProfile = Depends(auth_service.get_current_user),
    source: Optional[Literal["app", "google"]] = Query(None, description="Filter by source"),
    limit: int = Query(100, ge=1, le=500),
):
    """List browsing history for the authenticated user."""
    history = await auth_service.get_user_history(_db(), current_user.id, limit=limit, source=source)
    return {
        "status_code": 200,
        "success": True,
        "message": "History retrieved",
        "data": history,
    }


@router.post("/history")
async def record_history(
    request: CreateHistoryRequest,
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """Record a page visit in the authenticated user's app history."""
    visited_at = None
    if request.visited_at:
        try:
            visited_at = datetime.fromisoformat(request.visited_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid visited_at format. Use ISO 8601.") from exc

    entry = await auth_service.create_app_history_entry(
        _db(),
        user_id=current_user.id,
        url=request.url,
        title=request.title,
        visited_at=visited_at,
    )
    return {
        "status_code": 201,
        "success": True,
        "message": "History entry recorded",
        "data": entry,
    }


@router.delete("/history/{history_id}")
async def remove_history_entry(
    history_id: int,
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """Delete a single app history entry."""
    deleted = await auth_service.delete_app_history_entry(_db(), current_user.id, history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="History entry not found or not deletable")
    return {
        "status_code": 200,
        "success": True,
        "message": "History entry deleted",
    }


@router.delete("/history/clear")
async def clear_history(current_user: UserProfile = Depends(auth_service.get_current_user)):
    """Clear all app history entries for the authenticated user."""
    deleted_count = await auth_service.clear_app_history(_db(), current_user.id)
    return {
        "status_code": 200,
        "success": True,
        "message": "App history cleared",
        "deleted_count": deleted_count,
    }


@router.post("/google/sync")
async def trigger_google_sync(current_user: UserProfile = Depends(auth_service.get_current_user)):
    """Re-sync Chrome bookmarks and history from Google (Google users only)."""
    user = await auth_service.get_user_by_id(_db(), current_user.id)
    if not user or user["auth_provider"] != "google":
        raise HTTPException(status_code=400, detail="Google sync is only available for Google login users")

    tokens = await auth_service.get_oauth_tokens(_db(), current_user.id)
    if not tokens:
        raise HTTPException(status_code=400, detail="No Google OAuth tokens stored. Please login with Google again.")

    access_token = tokens["access_token"]
    if tokens.get("refresh_token"):
        try:
            refreshed = await google_service.refresh_access_token(tokens["refresh_token"])
            access_token = refreshed["access_token"]
            await auth_service.store_oauth_tokens(
                _db(),
                user_id=current_user.id,
                access_token=access_token,
                refresh_token=tokens.get("refresh_token"),
                expires_in=refreshed.get("expires_in"),
                scopes=tokens.get("scopes") or settings.google_oauth_scopes_portability,
            )
        except Exception as exc:
            logger.warning(f"Token refresh failed, using stored access token: {exc}")

    sync_result = await google_service.sync_google_bookmarks_and_history(
        _db(), current_user.id, access_token, auth_service
    )
    bookmarks = await auth_service.get_user_bookmarks(_db(), current_user.id)
    history = await auth_service.get_user_history(_db(), current_user.id)

    return {
        "status_code": 200,
        "success": sync_result["status"] == "complete",
        "message": sync_result["message"],
        "google_sync": sync_result,
        "bookmarks": bookmarks,
        "history": history,
    }
