"""User authentication: signup, login, JWT, OTP email verification, and user data access."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import randbelow
from typing import Any, Dict, List, Optional

import aiomysql
import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import email_service
from config import settings
from models import BookmarkItem, HistoryItem, UserProfile

bearer_scheme = HTTPBearer(auto_error=False)

_BCRYPT_MAX_PASSWORD_BYTES = 72


def _password_bytes(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Password cannot be longer than {_BCRYPT_MAX_PASSWORD_BYTES} bytes",
        )
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def _hash_otp(otp_code: str) -> str:
    return sha256(otp_code.encode("utf-8")).hexdigest()


def _generate_otp() -> str:
    return f"{randbelow(1_000_000):06d}"


def create_access_token(user_id: int, email: str, auth_provider: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "auth_provider": auth_provider,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def _row_to_user_profile(row: Dict[str, Any]) -> UserProfile:
    created_at = row.get("created_at")
    return UserProfile(
        id=row["id"],
        email=row["email"],
        full_name=row.get("full_name"),
        profile_picture=row.get("profile_picture"),
        auth_provider=row.get("auth_provider") or "app",
        email_verified=bool(row.get("email_verified")),
        created_at=created_at.isoformat() if created_at else None,
    )


def _is_email_verified(row: Dict[str, Any]) -> bool:
    return bool(row.get("email_verified"))


async def _set_and_send_otp(get_db_connection, user: Dict[str, Any]) -> int:
    """Generate OTP, store hash, send email. Returns expiry seconds."""
    if not email_service.is_email_configured() and not settings.email_otp_debug:
        raise HTTPException(
            status_code=503,
            detail="Email verification is not configured. Set BREVO_API_KEY and BREVO_SENDER_EMAIL.",
        )

    now = datetime.now(timezone.utc)
    last_sent = user.get("otp_last_sent_at")
    if last_sent:
        if last_sent.tzinfo is None:
            last_sent = last_sent.replace(tzinfo=timezone.utc)
        elapsed = (now - last_sent).total_seconds()
        if elapsed < settings.otp_resend_cooldown_seconds:
            wait_for = int(settings.otp_resend_cooldown_seconds - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {wait_for} seconds before requesting another code",
            )

    otp_code = _generate_otp()
    otp_hash = _hash_otp(otp_code)
    expires_at = now + timedelta(minutes=settings.otp_expire_minutes)

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                UPDATE users
                SET otp_code_hash = %s, otp_expires_at = %s, otp_last_sent_at = %s
                WHERE id = %s
                """,
                (otp_hash, expires_at, now, user["id"]),
            )

    try:
        await email_service.send_otp_email(user["email"], otp_code, user.get("full_name"))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send verification email: {exc}") from exc

    return settings.otp_expire_minutes * 60


async def create_app_user(get_db_connection, email: str, password: str, full_name: Optional[str]) -> Dict[str, Any]:
    password_hash = hash_password(password)

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT id, email_verified FROM users WHERE email = %s", (email,))
            existing = await cursor.fetchone()
            if existing:
                if existing.get("email_verified"):
                    raise HTTPException(status_code=409, detail="Email already registered. Please login instead.")
                raise HTTPException(
                    status_code=409,
                    detail="Email already registered but not verified. Use /auth/resend-otp then /auth/verify-email.",
                )

            await cursor.execute(
                """
                INSERT INTO users (
                    email, password_hash, full_name, auth_provider,
                    email_verified, last_login
                )
                VALUES (%s, %s, %s, 'app', 0, NULL)
                """,
                (email, password_hash, full_name),
            )
            user_id = cursor.lastrowid
            await cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return await cursor.fetchone()


async def signup_with_otp(get_db_connection, email: str, password: str, full_name: Optional[str]) -> Dict[str, Any]:
    user = await create_app_user(get_db_connection, email, password, full_name)
    otp_expires_in = await _set_and_send_otp(get_db_connection, user)
    return {
        "email": user["email"],
        "otp_expires_in": otp_expires_in,
    }


async def authenticate_app_user(get_db_connection, email: str, password: str) -> Dict[str, Any]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT * FROM users WHERE email = %s AND auth_provider = 'app'",
                (email,),
            )
            user = await cursor.fetchone()

    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not _is_email_verified(user):
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Check your inbox for the OTP or call /auth/resend-otp.",
        )

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user["id"],))

    return user


async def verify_email_otp(get_db_connection, email: str, otp_code: str) -> Dict[str, Any]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT * FROM users WHERE email = %s AND auth_provider = 'app'",
                (email,),
            )
            user = await cursor.fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please signup first.")

    if _is_email_verified(user):
        return user

    if not user.get("otp_code_hash") or not user.get("otp_expires_at"):
        raise HTTPException(status_code=400, detail="No active verification code. Request a new one.")

    expires_at = user["otp_expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Verification code expired. Request a new one.")

    if _hash_otp(otp_code) != user["otp_code_hash"]:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                UPDATE users
                SET email_verified = 1,
                    otp_code_hash = NULL,
                    otp_expires_at = NULL,
                    last_login = NOW()
                WHERE id = %s
                """,
                (user["id"],),
            )
            await cursor.execute("SELECT * FROM users WHERE id = %s", (user["id"],))
            return await cursor.fetchone()


async def resend_email_otp(get_db_connection, email: str) -> Dict[str, Any]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT * FROM users WHERE email = %s AND auth_provider = 'app'",
                (email,),
            )
            user = await cursor.fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please signup first.")
    if _is_email_verified(user):
        raise HTTPException(status_code=400, detail="Email is already verified. Please login.")

    otp_expires_in = await _set_and_send_otp(get_db_connection, user)
    return {
        "email": user["email"],
        "otp_expires_in": otp_expires_in,
    }


async def get_user_by_id(get_db_connection, user_id: int) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return await cursor.fetchone()


async def get_user_bookmarks(get_db_connection, user_id: int, limit: int = 100) -> List[BookmarkItem]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                SELECT id, title, url, folder, source
                FROM user_bookmarks
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()

    return [
        BookmarkItem(
            id=row["id"],
            title=row.get("title"),
            url=row["url"],
            folder=row.get("folder"),
            source=row.get("source") or "app",
        )
        for row in rows
    ]


async def get_user_history(get_db_connection, user_id: int, limit: int = 100) -> List[HistoryItem]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                SELECT id, title, url, visited_at, source
                FROM user_history
                WHERE user_id = %s
                ORDER BY visited_at DESC, created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()

    return [
        HistoryItem(
            id=row["id"],
            title=row.get("title"),
            url=row["url"],
            visited_at=row["visited_at"].isoformat() if row.get("visited_at") else None,
            source=row.get("source") or "app",
        )
        for row in rows
    ]


async def create_app_bookmark(
    get_db_connection,
    user_id: int,
    url: str,
    title: Optional[str] = None,
    folder: Optional[str] = None,
) -> BookmarkItem:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                SELECT id FROM user_bookmarks
                WHERE user_id = %s AND url = %s
                """,
                (user_id, url),
            )
            existing = await cursor.fetchone()
            if existing:
                await cursor.execute(
                    """
                    UPDATE user_bookmarks
                    SET title = %s, folder = %s, created_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND user_id = %s
                    """,
                    (title, folder, existing["id"], user_id),
                )
                bookmark_id = existing["id"]
            else:
                await cursor.execute(
                    """
                    INSERT INTO user_bookmarks (user_id, title, url, folder, source)
                    VALUES (%s, %s, %s, %s, 'app')
                    """,
                    (user_id, title, url, folder),
                )
                bookmark_id = cursor.lastrowid

            await cursor.execute(
                "SELECT id, title, url, folder, source FROM user_bookmarks WHERE id = %s",
                (bookmark_id,),
            )
            row = await cursor.fetchone()

    return BookmarkItem(
        id=row["id"],
        title=row.get("title"),
        url=row["url"],
        folder=row.get("folder"),
        source=row.get("source") or "app",
    )


async def delete_app_bookmark(get_db_connection, user_id: int, bookmark_id: int) -> bool:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "DELETE FROM user_bookmarks WHERE id = %s AND user_id = %s",
                (bookmark_id, user_id),
            )
            return cursor.rowcount > 0


async def create_app_history_entry(
    get_db_connection,
    user_id: int,
    url: str,
    title: Optional[str] = None,
    visited_at: Optional[datetime] = None,
) -> HistoryItem:
    visit_time = visited_at or datetime.now(timezone.utc)

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                INSERT INTO user_history (user_id, title, url, visited_at, source)
                VALUES (%s, %s, %s, %s, 'app')
                """,
                (user_id, title, url, visit_time),
            )
            history_id = cursor.lastrowid
            await cursor.execute(
                "SELECT id, title, url, visited_at, source FROM user_history WHERE id = %s",
                (history_id,),
            )
            row = await cursor.fetchone()

    return HistoryItem(
        id=row["id"],
        title=row.get("title"),
        url=row["url"],
        visited_at=row["visited_at"].isoformat() if row.get("visited_at") else None,
        source=row.get("source") or "app",
    )


async def delete_app_history_entry(get_db_connection, user_id: int, history_id: int) -> bool:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "DELETE FROM user_history WHERE id = %s AND user_id = %s",
                (history_id, user_id),
            )
            return cursor.rowcount > 0


async def clear_app_history(get_db_connection, user_id: int) -> int:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "DELETE FROM user_history WHERE user_id = %s",
                (user_id,),
            )
            return cursor.rowcount


async def get_user_auth_data(get_db_connection, user_id: int) -> tuple[List[BookmarkItem], List[HistoryItem]]:
    bookmarks = await get_user_bookmarks(get_db_connection, user_id)
    history = await get_user_history(get_db_connection, user_id)
    return bookmarks, history


def build_auth_response(
    user_row: Dict[str, Any],
    bookmarks: Optional[List[BookmarkItem]] = None,
    history: Optional[List[HistoryItem]] = None,
    message: str = "Authentication successful",
) -> dict:
    token = create_access_token(
        user_row["id"],
        user_row["email"],
        user_row.get("auth_provider") or "app",
    )
    return {
        "status_code": 200,
        "success": True,
        "message": message,
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
        "user": _row_to_user_profile(user_row),
        "bookmarks": bookmarks,
        "history": history,
    }


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> UserProfile:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials)
    user_id = int(payload["sub"])

    from main import get_db_connection

    user = await get_user_by_id(get_db_connection, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return _row_to_user_profile(user)
