"""User authentication: passwordless email OTP, JWT, bookmarks, and history."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import randbelow
from typing import Any, Dict, List, Optional

import aiomysql
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import email_service
from app.config import settings
from app.models import BookmarkItem, HistoryItem, UserProfile

bearer_scheme = HTTPBearer(auto_error=False)


def _hash_otp(otp_code: str) -> str:
    return sha256(otp_code.encode("utf-8")).hexdigest()


def _generate_otp() -> str:
    return f"{randbelow(1_000_000):06d}"


def create_access_token(
    user_id: int,
    email: str,
    auth_provider: str,
    token_version: int = 0,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "auth_provider": auth_provider,
        "tv": int(token_version or 0),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token has expired. Please sign in again.") from exc
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


async def _set_and_send_otp(
    get_db_connection,
    user: Dict[str, Any],
    purpose: str = "signin",
) -> int:
    """Generate OTP, store hash + purpose, send email. Returns expiry seconds."""
    if not email_service.is_email_configured() and not settings.email_otp_debug:
        raise HTTPException(
            status_code=503,
            detail="Email sign-in is not configured. Set BREVO_API_KEY and BREVO_SENDER_EMAIL.",
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
                SET otp_code_hash = %s,
                    otp_purpose = %s,
                    otp_expires_at = %s,
                    otp_last_sent_at = %s
                WHERE id = %s
                """,
                (otp_hash, purpose, expires_at, now, user["id"]),
            )

    try:
        await email_service.send_otp_email(
            user["email"],
            otp_code,
            user.get("full_name"),
            purpose=purpose,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send sign-in email: {exc}") from exc

    return settings.otp_expire_minutes * 60


def _validate_otp(user: Dict[str, Any], otp_code: str, expected_purpose: str) -> None:
    if not user.get("otp_code_hash") or not user.get("otp_expires_at"):
        raise HTTPException(status_code=400, detail="No active sign-in code. Request a new one.")

    purpose = user.get("otp_purpose") or "signin"
    if purpose != expected_purpose:
        raise HTTPException(status_code=400, detail="No active sign-in code. Request a new one.")

    expires_at = user["otp_expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Sign-in code expired. Request a new one.")

    if _hash_otp(otp_code) != user["otp_code_hash"]:
        raise HTTPException(status_code=400, detail="Invalid sign-in code")


async def get_or_create_user_by_email(get_db_connection, email: str) -> Dict[str, Any]:
    """Find user by email or create a passwordless account (race-safe)."""
    email = (email or "").lower().strip()

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Match on email only — unique_email is global
            await cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = await cursor.fetchone()
            if user:
                return user

            try:
                await cursor.execute(
                    """
                    INSERT INTO users (
                        email, password_hash, full_name, auth_provider,
                        email_verified, token_version, last_login
                    )
                    VALUES (%s, NULL, NULL, 'app', 0, 0, NULL)
                    """,
                    (email,),
                )
                user_id = cursor.lastrowid
                await cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                return await cursor.fetchone()
            except Exception as exc:
                # Concurrent sign-in can hit unique_email; re-load existing row
                errno = exc.args[0] if getattr(exc, "args", None) else None
                msg = str(exc).lower()
                if errno == 1062 or "duplicate" in msg:
                    await cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                    user = await cursor.fetchone()
                    if user:
                        return user
                raise


async def request_signin_otp(get_db_connection, email: str) -> Dict[str, Any]:
    """Start passwordless sign-in: create user if needed and email an OTP."""
    user = await get_or_create_user_by_email(get_db_connection, email)
    otp_expires_in = await _set_and_send_otp(get_db_connection, user, purpose="signin")
    return {
        "email": user["email"],
        "otp_expires_in": otp_expires_in,
        "email_verified": bool(user.get("email_verified")),
    }


async def verify_signin_otp(get_db_connection, email: str, otp_code: str) -> Dict[str, Any]:
    """Verify OTP and mark the email as signed in / verified."""
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT * FROM users WHERE email = %s",
                (email,),
            )
            user = await cursor.fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="User not found. Request a sign-in code first.")

    _validate_otp(user, otp_code, expected_purpose="signin")

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                UPDATE users
                SET email_verified = 1,
                    otp_code_hash = NULL,
                    otp_purpose = NULL,
                    otp_expires_at = NULL,
                    last_login = NOW()
                WHERE id = %s
                """,
                (user["id"],),
            )
            await cursor.execute("SELECT * FROM users WHERE id = %s", (user["id"],))
            return await cursor.fetchone()


async def resend_signin_otp(get_db_connection, email: str) -> Dict[str, Any]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT * FROM users WHERE email = %s",
                (email,),
            )
            user = await cursor.fetchone()

    if not user:
        return await request_signin_otp(get_db_connection, email)

    otp_expires_in = await _set_and_send_otp(get_db_connection, user, purpose="signin")
    return {
        "email": user["email"],
        "otp_expires_in": otp_expires_in,
        "email_verified": bool(user.get("email_verified")),
    }


async def logout_user(get_db_connection, user_id: int) -> None:
    """Invalidate all existing JWTs for this user by bumping token_version."""
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "UPDATE users SET token_version = COALESCE(token_version, 0) + 1 WHERE id = %s",
                (user_id,),
            )


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


async def create_app_bookmarks_bulk(
    get_db_connection,
    user_id: int,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Save each bookmark as its own record. Continues on per-item failures."""
    saved: List[BookmarkItem] = []
    errors: List[Dict[str, Any]] = []

    for index, item in enumerate(items):
        try:
            bookmark = await create_app_bookmark(
                get_db_connection,
                user_id=user_id,
                url=item["url"],
                title=item.get("title"),
                folder=item.get("folder"),
            )
            saved.append(bookmark)
        except Exception as exc:
            errors.append({"index": index, "url": item.get("url"), "error": str(exc)})

    return {
        "saved_count": len(saved),
        "failed_count": len(errors),
        "data": saved,
        "errors": errors,
    }


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


async def create_app_history_bulk(
    get_db_connection,
    user_id: int,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Save each history entry as its own record. Continues on per-item failures."""
    saved: List[HistoryItem] = []
    errors: List[Dict[str, Any]] = []

    for index, item in enumerate(items):
        try:
            visited_at = item.get("visited_at")
            if isinstance(visited_at, str) and visited_at.strip():
                try:
                    visited_at = datetime.fromisoformat(visited_at.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("Invalid visited_at format. Use ISO 8601.") from exc
            else:
                visited_at = None

            entry = await create_app_history_entry(
                get_db_connection,
                user_id=user_id,
                url=item["url"],
                title=item.get("title"),
                visited_at=visited_at,
            )
            saved.append(entry)
        except Exception as exc:
            errors.append({"index": index, "url": item.get("url"), "error": str(exc)})

    return {
        "saved_count": len(saved),
        "failed_count": len(errors),
        "data": saved,
        "errors": errors,
    }


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


def _epoch_to_utc_datetime(epoch: int) -> datetime:
    """Accept seconds or milliseconds since epoch."""
    value = int(epoch)
    # Values above year ~2001 in ms range
    if value > 1_000_000_000_000:
        value = value / 1000.0
    return datetime.fromtimestamp(value, tz=timezone.utc)


async def delete_app_history_from_epoch(
    get_db_connection,
    user_id: int,
    from_epoch: int,
) -> Dict[str, Any]:
    """
    Delete history entries from from_epoch up to now (inclusive), for this user.
    Uses visited_at when set, otherwise created_at.
    """
    start_at = _epoch_to_utc_datetime(from_epoch)
    end_at = datetime.now(timezone.utc)

    if start_at > end_at:
        raise HTTPException(
            status_code=400,
            detail="from_epoch must be less than or equal to current time",
        )

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                DELETE FROM user_history
                WHERE user_id = %s
                  AND COALESCE(visited_at, created_at) >= %s
                  AND COALESCE(visited_at, created_at) <= %s
                """,
                (user_id, start_at, end_at),
            )
            deleted_count = cursor.rowcount

    return {
        "deleted_count": deleted_count,
        "from_epoch": int(from_epoch),
        "from_time": start_at.isoformat(),
        "to_time": end_at.isoformat(),
    }


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
        token_version=int(user_row.get("token_version") or 0),
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
    token_version = int(payload.get("tv") or 0)

    from app.main import get_db_connection

    user = await get_user_by_id(get_db_connection, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    current_version = int(user.get("token_version") or 0)
    if token_version != current_version:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")

    if not user.get("email_verified"):
        raise HTTPException(status_code=401, detail="Email not verified. Please sign in with OTP.")

    return _row_to_user_profile(user)


async def get_valid_session_user(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[Dict[str, Any]]:
    """
    Return the DB user row if Bearer token is a valid active session.
    Returns None when missing/invalid (does not raise).
    """
    if not credentials or credentials.scheme.lower() != "bearer":
        return None

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
        token_version = int(payload.get("tv") or 0)
    except HTTPException:
        return None
    except Exception:
        return None

    from app.main import get_db_connection

    user = await get_user_by_id(get_db_connection, user_id)
    if not user or not user.get("email_verified"):
        return None

    current_version = int(user.get("token_version") or 0)
    if token_version != current_version:
        return None

    return user


def raise_if_already_signed_in(
    session_user: Optional[Dict[str, Any]],
    requested_email: str,
) -> None:
    """Block OTP sign-in when a valid token for the same email is already present."""
    if not session_user:
        return
    if (session_user.get("email") or "").lower() != (requested_email or "").lower():
        return
    raise HTTPException(
        status_code=409,
        detail={
            "already_signed_in": True,
            "email": session_user["email"],
            "message": "You are already signed in. Use GET /auth/me with your existing access token instead of requesting a new OTP.",
            "use_endpoint": "/auth/me",
        },
    )
