"""Authentication API routes: app signup/login, email OTP, bookmarks, and history."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

import auth_service
from logger import logger
from models import (
    AuthResponse,
    CreateBookmarkRequest,
    CreateHistoryRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResendOtpRequest,
    ResetPasswordRequest,
    SignupPendingResponse,
    SignupRequest,
    UserProfile,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _db():
    from main import get_db_connection
    return get_db_connection


@router.post("/signup", response_model=SignupPendingResponse)
async def signup(request: SignupRequest):
    """
    Register a new user and send email OTP.
    Account stays unverified until POST /auth/verify-email succeeds.
    """
    try:
        result = await auth_service.signup_with_otp(
            _db(), request.email, request.password, request.full_name
        )
        return {
            "status_code": 200,
            "success": True,
            "message": "Signup successful. Enter the OTP sent to your email to verify your account.",
            "email": result["email"],
            "email_verified": False,
            "requires_verification": True,
            "otp_expires_in": result["otp_expires_in"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Signup failed: {exc}")
        raise HTTPException(status_code=500, detail="Signup failed") from exc


@router.post("/verify-email", response_model=AuthResponse)
async def verify_email(request: VerifyEmailRequest):
    """Verify signup email with OTP and return JWT."""
    try:
        user = await auth_service.verify_email_otp(_db(), request.email, request.otp_code)
        bookmarks, history = await auth_service.get_user_auth_data(_db(), user["id"])
        return auth_service.build_auth_response(
            user,
            bookmarks=bookmarks,
            history=history,
            message="Email verified successfully",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Email verification failed: {exc}")
        raise HTTPException(status_code=500, detail="Email verification failed") from exc


@router.post("/resend-otp", response_model=SignupPendingResponse)
async def resend_otp(request: ResendOtpRequest):
    """Resend verification OTP for an unverified account."""
    try:
        result = await auth_service.resend_email_otp(_db(), request.email)
        return {
            "status_code": 200,
            "success": True,
            "message": "A new verification code has been sent to your email.",
            "email": result["email"],
            "email_verified": False,
            "requires_verification": True,
            "otp_expires_in": result["otp_expires_in"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Resend OTP failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to resend OTP") from exc


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """Login with email and password. Requires prior signup and email verification."""
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


@router.post("/forgot-password", response_model=SignupPendingResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """
    Request a password-reset OTP.
    Always returns a generic success message (does not reveal whether the email exists).
    """
    try:
        result = await auth_service.forgot_password(_db(), request.email)
        return {
            "status_code": 200,
            "success": True,
            "message": "If an account exists for this email, a password reset code has been sent.",
            "email": result["email"],
            "email_verified": True,
            "requires_verification": True,
            "otp_expires_in": result["otp_expires_in"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Forgot password failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to process password reset request") from exc


@router.post("/reset-password", response_model=AuthResponse)
async def reset_password(request: ResetPasswordRequest):
    """Reset password with OTP and return a fresh JWT."""
    try:
        user = await auth_service.reset_password(
            _db(),
            request.email,
            request.otp_code,
            request.new_password,
        )
        bookmarks, history = await auth_service.get_user_auth_data(_db(), user["id"])
        return auth_service.build_auth_response(
            user,
            bookmarks=bookmarks,
            history=history,
            message="Password reset successful",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Reset password failed: {exc}")
        raise HTTPException(status_code=500, detail="Password reset failed") from exc


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
    limit: int = Query(100, ge=1, le=500),
):
    """List bookmarks for the authenticated user."""
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
    """List browsing history for the authenticated user."""
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
