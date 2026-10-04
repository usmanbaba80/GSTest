"""Authentication API routes: passwordless email OTP sign-in, bookmarks, and history."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import service as auth_service
from app.logger import logger
from app.models import (
    AuthResponse,
    BulkBookmarksRequest,
    BulkHistoryRequest,
    CreateBookmarkRequest,
    CreateHistoryRequest,
    EmailOnlyRequest,
    OtpPendingResponse,
    UserProfile,
    VerifyOtpRequest,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _db():
    from app.main import get_db_connection
    return get_db_connection


@router.post("/signin", response_model=OtpPendingResponse)
async def signin(
    request: EmailOnlyRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_service.bearer_scheme),
):
    """
    Passwordless sign-in: send OTP to email.
    Creates the user automatically if the email is new.

    If Authorization Bearer token is present and still valid for the same email,
    OTP is not sent — client should call GET /auth/me instead.
    """
    try:
        session_user = await auth_service.get_valid_session_user(credentials)
        auth_service.raise_if_already_signed_in(session_user, request.email)

        result = await auth_service.request_signin_otp(_db(), request.email)
        return {
            "status_code": 200,
            "success": True,
            "message": "Sign-in code sent to your email.",
            "email": result["email"],
            "email_verified": result.get("email_verified", False),
            "requires_verification": True,
            "otp_expires_in": result["otp_expires_in"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Sign-in failed: {exc}")
        raise HTTPException(status_code=500, detail="Sign-in failed") from exc


# Backwards-compatible aliases for older clients
@router.post("/signup", response_model=OtpPendingResponse, include_in_schema=False)
async def signin_alias_signup(
    request: EmailOnlyRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_service.bearer_scheme),
):
    return await signin(request, credentials)


@router.post("/login", response_model=OtpPendingResponse, include_in_schema=False)
async def signin_alias_login(
    request: EmailOnlyRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_service.bearer_scheme),
):
    return await signin(request, credentials)


@router.post("/verify-otp", response_model=AuthResponse)
async def verify_otp(request: VerifyOtpRequest):
    """Verify email OTP and return a long-lived JWT (valid until logout)."""
    try:
        user = await auth_service.verify_signin_otp(_db(), request.email, request.otp_code)
        bookmarks, history = await auth_service.get_user_auth_data(_db(), user["id"])
        return auth_service.build_auth_response(
            user,
            bookmarks=bookmarks,
            history=history,
            message="Signed in successfully",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"OTP verification failed: {exc}")
        raise HTTPException(status_code=500, detail="OTP verification failed") from exc


@router.post("/verify-email", response_model=AuthResponse, include_in_schema=False)
async def verify_email_alias(request: VerifyOtpRequest):
    return await verify_otp(request)


@router.post("/resend-otp", response_model=OtpPendingResponse)
async def resend_otp(
    request: EmailOnlyRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_service.bearer_scheme),
):
    """Resend sign-in OTP for an email. Blocked if already signed in with a valid token."""
    try:
        session_user = await auth_service.get_valid_session_user(credentials)
        auth_service.raise_if_already_signed_in(session_user, request.email)

        result = await auth_service.resend_signin_otp(_db(), request.email)
        return {
            "status_code": 200,
            "success": True,
            "message": "A new sign-in code has been sent to your email.",
            "email": result["email"],
            "email_verified": result.get("email_verified", False),
            "requires_verification": True,
            "otp_expires_in": result["otp_expires_in"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Resend OTP failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to resend OTP") from exc


@router.post("/logout")
async def logout(current_user: UserProfile = Depends(auth_service.get_current_user)):
    """
    Explicit sign-out. Invalidates the current JWT (and all prior tokens for this user).
    Client should discard the access_token after this call.
    """
    try:
        await auth_service.logout_user(_db(), current_user.id)
        return {
            "status_code": 200,
            "success": True,
            "message": "Signed out successfully",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Logout failed: {exc}")
        raise HTTPException(status_code=500, detail="Logout failed") from exc


@router.get("/me", response_model=AuthResponse)
async def get_me(current_user: UserProfile = Depends(auth_service.get_current_user)):
    """Get the currently authenticated user's profile + bookmarks + history."""
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
    limit: int = Query(100, ge=1, le=500),
):
    """List bookmarks for the authenticated user (tied to their email)."""
    bookmarks = await auth_service.get_user_bookmarks(_db(), current_user.id, limit=limit)
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
    """Save a bookmark for the authenticated user."""
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


@router.post("/bookmarks/bulk")
async def add_bookmarks_bulk(
    request: BulkBookmarksRequest,
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """
    Bulk intake of bookmarks.
    Accepts an array; each item is saved as a separate user_bookmarks row.
    """
    result = await auth_service.create_app_bookmarks_bulk(
        _db(),
        user_id=current_user.id,
        items=[item.dict() if hasattr(item, "dict") else item.model_dump() for item in request.bookmarks],
    )
    return {
        "status_code": 201,
        "success": True,
        "message": f"Bulk bookmarks processed: {result['saved_count']} saved, {result['failed_count']} failed",
        **result,
    }


@router.delete("/bookmarks/{bookmark_id}")
async def remove_bookmark(
    bookmark_id: int,
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """Delete a bookmark owned by the authenticated user."""
    deleted = await auth_service.delete_app_bookmark(_db(), current_user.id, bookmark_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {
        "status_code": 200,
        "success": True,
        "message": "Bookmark deleted",
    }


@router.get("/history")
async def list_history(
    current_user: UserProfile = Depends(auth_service.get_current_user),
    limit: int = Query(100, ge=1, le=500),
):
    """List browsing history for the authenticated user (tied to their email)."""
    history = await auth_service.get_user_history(_db(), current_user.id, limit=limit)
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
    """Record a page visit in the authenticated user's history."""
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


@router.post("/history/bulk")
async def record_history_bulk(
    request: BulkHistoryRequest,
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """
    Bulk intake of history.
    Accepts an array; each item is saved as a separate user_history row.
    """
    result = await auth_service.create_app_history_bulk(
        _db(),
        user_id=current_user.id,
        items=[item.dict() if hasattr(item, "dict") else item.model_dump() for item in request.history],
    )
    return {
        "status_code": 201,
        "success": True,
        "message": f"Bulk history processed: {result['saved_count']} saved, {result['failed_count']} failed",
        **result,
    }


@router.delete("/history/clear")
async def clear_history(current_user: UserProfile = Depends(auth_service.get_current_user)):
    """Clear all history entries for the authenticated user."""
    deleted_count = await auth_service.clear_app_history(_db(), current_user.id)
    return {
        "status_code": 200,
        "success": True,
        "message": "History cleared",
        "deleted_count": deleted_count,
    }


@router.delete("/history/range")
async def delete_history_range(
    from_epoch: int = Query(
        ...,
        description="Unix epoch (seconds or milliseconds). Deletes history from this time until now.",
    ),
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """
    Delete history from `from_epoch` to now for the authenticated user.
    Example: DELETE /auth/history/range?from_epoch=1710000000
    """
    result = await auth_service.delete_app_history_from_epoch(
        _db(),
        current_user.id,
        from_epoch,
    )
    return {
        "status_code": 200,
        "success": True,
        "message": "History deleted for the selected time range",
        **result,
    }


@router.delete("/history/{history_id}")
async def remove_history_entry(
    history_id: int,
    current_user: UserProfile = Depends(auth_service.get_current_user),
):
    """Delete a single history entry."""
    deleted = await auth_service.delete_app_history_entry(_db(), current_user.id, history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="History entry not found")
    return {
        "status_code": 200,
        "success": True,
        "message": "History entry deleted",
    }
