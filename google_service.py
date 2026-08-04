"""Google OAuth and Chrome bookmarks/history sync via Data Portability API."""

import asyncio
import json
import secrets
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from config import settings
from logger import logger

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
DATA_PORTABILITY_INITIATE_URL = "https://dataportability.googleapis.com/v1/portabilityArchive:initiate"
DATA_PORTABILITY_STATE_URL = "https://dataportability.googleapis.com/v1/archiveJobs/{job_id}/portabilityArchiveState"

_oauth_states: Dict[str, float] = {}


def is_google_oauth_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri)


def build_google_auth_url() -> tuple[str, str]:
    if not is_google_oauth_configured():
        raise ValueError("Google OAuth is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI.")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = datetime.now(timezone.utc).timestamp()

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": settings.google_oauth_scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}", state


async def exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    if not is_google_oauth_configured():
        raise ValueError("Google OAuth is not configured.")

    payload = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=payload)
        response.raise_for_status()
        return response.json()


async def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    payload = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=payload)
        response.raise_for_status()
        return response.json()


async def fetch_google_userinfo(access_token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def initiate_portability_export(access_token: str, resource: str) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            DATA_PORTABILITY_INITIATE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"resources": [resource]},
        )
        response.raise_for_status()
        data = response.json()
        return data["archiveJobId"]


async def poll_portability_job(access_token: str, job_id: str, max_attempts: int = 30, delay_seconds: float = 2.0) -> Dict[str, Any]:
    url = DATA_PORTABILITY_STATE_URL.format(job_id=job_id)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        for _ in range(max_attempts):
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            state_data = response.json()
            state = state_data.get("state", "IN_PROGRESS")

            if state == "COMPLETE":
                return state_data
            if state in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"Google export job {job_id} ended with state {state}")

            await asyncio.sleep(delay_seconds)

    raise TimeoutError(f"Google export job {job_id} did not complete in time")


async def download_export_payload(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def _extract_files_from_export(content: bytes) -> List[tuple[str, bytes]]:
    if content[:2] == b"PK":
        files: List[tuple[str, bytes]] = []
        with zipfile.ZipFile(BytesIO(content)) as archive:
            for name in archive.namelist():
                files.append((name, archive.read(name)))
        return files
    return [("export.bin", content)]


def parse_bookmarks_html(html_content: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_content, "html.parser")
    bookmarks: List[Dict[str, Any]] = []
    current_folder: Optional[str] = None

    for element in soup.find_all(["h3", "a"]):
        if element.name == "h3":
            current_folder = element.get_text(strip=True) or None
        elif element.name == "a" and element.get("href"):
            bookmarks.append(
                {
                    "title": element.get_text(strip=True) or element["href"],
                    "url": element["href"],
                    "folder": current_folder,
                }
            )
    return bookmarks


def parse_history_json(raw_content: bytes) -> List[Dict[str, Any]]:
    text = raw_content.decode("utf-8", errors="ignore").strip()
    if not text:
        return []

    if text.startswith("Your data is encrypted"):
        logger.warning("Google history export is encrypted and cannot be parsed")
        return []

    history_items: List[Dict[str, Any]] = []

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return history_items

    entries = payload
    if isinstance(payload, dict):
        entries = payload.get("Browser History") or payload.get("browser_history") or payload.get("history") or []

    if not isinstance(entries, list):
        return history_items

    for entry in entries:
        if isinstance(entry, str):
            continue
        if not isinstance(entry, dict):
            continue

        url = entry.get("url")
        if not url:
            continue

        visited_at = None
        time_usec = entry.get("time_usec")
        if time_usec:
            visited_at = datetime.fromtimestamp(int(time_usec) / 1_000_000, tz=timezone.utc)

        history_items.append(
            {
                "title": entry.get("title"),
                "url": url,
                "visited_at": visited_at,
            }
        )

    return history_items


async def export_and_parse_resource(access_token: str, resource: str) -> List[Dict[str, Any]]:
    job_id = await initiate_portability_export(access_token, resource)
    state_data = await poll_portability_job(access_token, job_id)
    urls = state_data.get("urls") or []
    if not urls:
        return []

    content = await download_export_payload(urls[0])
    files = _extract_files_from_export(content)
    parsed: List[Dict[str, Any]] = []

    for filename, file_content in files:
        lower_name = filename.lower()
        if resource == "chrome.bookmarks" and (lower_name.endswith(".html") or b"<a href=" in file_content[:500]):
            parsed.extend(parse_bookmarks_html(file_content.decode("utf-8", errors="ignore")))
        elif resource == "chrome.history" and (lower_name.endswith(".json") or file_content[:1] in (b"{", b"[")):
            parsed.extend(parse_history_json(file_content))

    if resource == "chrome.bookmarks" and not parsed and b"<a href=" in content[:1000]:
        parsed.extend(parse_bookmarks_html(content.decode("utf-8", errors="ignore")))
    if resource == "chrome.history" and not parsed:
        parsed.extend(parse_history_json(content))

    return parsed


async def sync_google_bookmarks_and_history(
    get_db_connection,
    user_id: int,
    access_token: str,
    auth_service,
) -> Dict[str, Any]:
    result = {
        "bookmarks_job_id": None,
        "history_job_id": None,
        "bookmarks_count": 0,
        "history_count": 0,
        "status": "in_progress",
        "message": "Sync started",
    }

    try:
        bookmarks = await export_and_parse_resource(access_token, "chrome.bookmarks")
        history_items = await export_and_parse_resource(access_token, "chrome.history")

        bookmarks_count = await auth_service.save_google_bookmarks(get_db_connection, user_id, bookmarks)
        history_count = await auth_service.save_google_history(get_db_connection, user_id, history_items)

        result.update(
            {
                "bookmarks_count": bookmarks_count,
                "history_count": history_count,
                "status": "complete",
                "message": "Google bookmarks and history synced successfully",
            }
        )
    except Exception as exc:
        logger.error(f"Google sync failed for user {user_id}: {exc}")
        result.update({"status": "failed", "message": str(exc)})

    return result


def start_google_sync_background(get_db_connection, user_id: int, access_token: str, auth_service) -> None:
    async def _run_sync():
        await sync_google_bookmarks_and_history(get_db_connection, user_id, access_token, auth_service)

    asyncio.create_task(_run_sync())
