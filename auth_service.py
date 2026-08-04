"""User authentication: signup, login, JWT, and user data access."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiomysql
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from config import settings
from logger import logger
from models import BookmarkItem, HistoryItem, UserProfile

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


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
        auth_provider=row["auth_provider"],
        created_at=created_at.isoformat() if created_at else None,
    )


async def create_app_user(get_db_connection, email: str, password: str, full_name: Optional[str]) -> Dict[str, Any]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if await cursor.fetchone():
                raise HTTPException(status_code=409, detail="Email already registered. Please login instead.")

            password_hash = hash_password(password)
            await cursor.execute(
                """
                INSERT INTO users (email, password_hash, full_name, auth_provider, last_login)
                VALUES (%s, %s, %s, 'app', NOW())
                """,
                (email, password_hash, full_name),
            )
            user_id = cursor.lastrowid
            await cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return await cursor.fetchone()


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

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user["id"],))

    return user


async def upsert_google_user(
    get_db_connection,
    google_sub: str,
    email: str,
    full_name: Optional[str],
    profile_picture: Optional[str],
) -> Dict[str, Any]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT * FROM users WHERE google_sub = %s", (google_sub,))
            existing = await cursor.fetchone()

            if existing:
                await cursor.execute(
                    """
                    UPDATE users
                    SET email = %s, full_name = %s, profile_picture = %s,
                        auth_provider = 'google', last_login = NOW()
                    WHERE id = %s
                    """,
                    (email, full_name, profile_picture, existing["id"]),
                )
                user_id = existing["id"]
            else:
                await cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                email_user = await cursor.fetchone()
                if email_user:
                    await cursor.execute(
                        """
                        UPDATE users
                        SET google_sub = %s, full_name = %s, profile_picture = %s,
                            auth_provider = 'google', last_login = NOW()
                        WHERE id = %s
                        """,
                        (google_sub, full_name or email_user.get("full_name"), profile_picture, email_user["id"]),
                    )
                    user_id = email_user["id"]
                else:
                    await cursor.execute(
                        """
                        INSERT INTO users (email, full_name, google_sub, profile_picture, auth_provider, last_login)
                        VALUES (%s, %s, %s, %s, 'google', NOW())
                        """,
                        (email, full_name, google_sub, profile_picture),
                    )
                    user_id = cursor.lastrowid

            await cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return await cursor.fetchone()


async def store_oauth_tokens(
    get_db_connection,
    user_id: int,
    access_token: str,
    refresh_token: Optional[str],
    expires_in: Optional[int],
    scopes: str,
) -> None:
    token_expiry = None
    if expires_in:
        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                INSERT INTO user_oauth_tokens (user_id, access_token, refresh_token, token_expiry, scopes)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    access_token = VALUES(access_token),
                    refresh_token = VALUES(refresh_token),
                    token_expiry = VALUES(token_expiry),
                    scopes = VALUES(scopes),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, access_token, refresh_token, token_expiry, scopes),
            )


async def get_oauth_tokens(get_db_connection, user_id: int) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT access_token, refresh_token, token_expiry, scopes FROM user_oauth_tokens WHERE user_id = %s",
                (user_id,),
            )
            return await cursor.fetchone()


async def get_user_by_id(get_db_connection, user_id: int) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return await cursor.fetchone()


async def get_user_bookmarks(
    get_db_connection, user_id: int, limit: int = 100, source: Optional[str] = None
) -> List[BookmarkItem]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            if source:
                await cursor.execute(
                    """
                    SELECT id, title, url, folder, source
                    FROM user_bookmarks
                    WHERE user_id = %s AND source = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (user_id, source, limit),
                )
            else:
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
            source=row["source"],
        )
        for row in rows
    ]


async def get_user_history(
    get_db_connection, user_id: int, limit: int = 100, source: Optional[str] = None
) -> List[HistoryItem]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            if source:
                await cursor.execute(
                    """
                    SELECT id, title, url, visited_at, source
                    FROM user_history
                    WHERE user_id = %s AND source = %s
                    ORDER BY visited_at DESC, created_at DESC
                    LIMIT %s
                    """,
                    (user_id, source, limit),
                )
            else:
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
            source=row["source"],
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
                WHERE user_id = %s AND url = %s AND source = 'app'
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
        source=row["source"],
    )


async def delete_app_bookmark(get_db_connection, user_id: int, bookmark_id: int) -> bool:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                DELETE FROM user_bookmarks
                WHERE id = %s AND user_id = %s AND source = 'app'
                """,
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
        source=row["source"],
    )


async def delete_app_history_entry(get_db_connection, user_id: int, history_id: int) -> bool:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                DELETE FROM user_history
                WHERE id = %s AND user_id = %s AND source = 'app'
                """,
                (history_id, user_id),
            )
            return cursor.rowcount > 0


async def clear_app_history(get_db_connection, user_id: int) -> int:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "DELETE FROM user_history WHERE user_id = %s AND source = 'app'",
                (user_id,),
            )
            return cursor.rowcount


async def get_user_auth_data(get_db_connection, user_id: int) -> tuple[List[BookmarkItem], List[HistoryItem]]:
    bookmarks = await get_user_bookmarks(get_db_connection, user_id)
    history = await get_user_history(get_db_connection, user_id)
    return bookmarks, history


async def save_google_bookmarks(get_db_connection, user_id: int, bookmarks: List[Dict[str, Any]]) -> int:
    saved = 0
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("DELETE FROM user_bookmarks WHERE user_id = %s AND source = 'google'", (user_id,))
            for item in bookmarks:
                await cursor.execute(
                    """
                    INSERT INTO user_bookmarks (user_id, title, url, folder, source, google_synced_at)
                    VALUES (%s, %s, %s, %s, 'google', NOW())
                    """,
                    (user_id, item.get("title"), item["url"], item.get("folder")),
                )
                saved += 1
    return saved


async def save_google_history(get_db_connection, user_id: int, history_items: List[Dict[str, Any]]) -> int:
    saved = 0
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("DELETE FROM user_history WHERE user_id = %s AND source = 'google'", (user_id,))
            for item in history_items:
                visited_at = item.get("visited_at")
                await cursor.execute(
                    """
                    INSERT INTO user_history (user_id, title, url, visited_at, source, google_synced_at)
                    VALUES (%s, %s, %s, %s, 'google', NOW())
                    """,
                    (user_id, item.get("title"), item["url"], visited_at),
                )
                saved += 1
    return saved


async def record_sync_job(
    get_db_connection,
    user_id: int,
    job_id: str,
    resource_type: str,
    status: str = "IN_PROGRESS",
) -> None:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                INSERT INTO google_sync_jobs (user_id, job_id, resource_type, status)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, job_id, resource_type, status),
            )


async def update_sync_job_status(get_db_connection, job_id: str, status: str) -> None:
    completed_at = "NOW()" if status == "COMPLETE" else "NULL"
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                f"""
                UPDATE google_sync_jobs
                SET status = %s, completed_at = {completed_at}
                WHERE job_id = %s
                """,
                (status, job_id),
            )


async def get_sync_jobs(get_db_connection, user_id: int) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                SELECT job_id, resource_type, status, created_at, completed_at
                FROM google_sync_jobs
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (user_id,),
            )
            return await cursor.fetchall()


def build_auth_response(
    user_row: Dict[str, Any],
    bookmarks: Optional[List[BookmarkItem]] = None,
    history: Optional[List[HistoryItem]] = None,
    google_sync: Optional[dict] = None,
    message: str = "Authentication successful",
) -> dict:
    token = create_access_token(user_row["id"], user_row["email"], user_row["auth_provider"])
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
        "google_sync": google_sync,
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
