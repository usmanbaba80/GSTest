"""
Google Trending Now via ScrapingDog with 24h DB cache.

- Refresh ScrapingDog at most once per geo every `trending_cache_hours`
- Store top N trends (`trending_store_count`, default 10)
- Serve M random items (`trending_serve_count`, default 4)
- Concurrent callers for the same geo share one refresh (asyncio.Lock)
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiomysql
import httpx
from fastapi import HTTPException

from app.config import settings
from app.logger import logger

# One lock per geo so concurrent requests don't stampede ScrapingDog
_geo_locks: Dict[str, asyncio.Lock] = {}
_geo_locks_guard = asyncio.Lock()


async def _lock_for_geo(geo: str) -> asyncio.Lock:
    async with _geo_locks_guard:
        if geo not in _geo_locks:
            _geo_locks[geo] = asyncio.Lock()
        return _geo_locks[geo]


def _normalize_geo(geo: Optional[str]) -> str:
    value = (geo or settings.trending_default_geo or "US").strip().upper()
    if not value or len(value) > 16:
        raise HTTPException(status_code=400, detail="Invalid geo code")
    return value


def _is_fresh(fetched_at: Optional[datetime]) -> bool:
    if not fetched_at:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - fetched_at
    return age <= timedelta(hours=settings.trending_cache_hours)


def _pick_random(items: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    if not items:
        return []
    sample_size = min(count, len(items))
    return random.sample(items, sample_size)


async def _load_cache(get_db_connection, geo: str) -> Tuple[List[Dict[str, Any]], Optional[datetime]]:
    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                SELECT results, fetched_at
                FROM google_trending_cache
                WHERE geo = %s
                LIMIT 1
                """,
                (geo,),
            )
            row = await cursor.fetchone()

    if not row:
        return [], None

    results = row.get("results")
    if isinstance(results, (bytes, bytearray)):
        results = results.decode("utf-8")
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except json.JSONDecodeError:
            results = []
    if not isinstance(results, list):
        results = []

    return results, row.get("fetched_at")


async def _save_cache(get_db_connection, geo: str, top_items: List[Dict[str, Any]]) -> datetime:
    now = datetime.now(timezone.utc)
    payload = json.dumps(top_items, ensure_ascii=False)

    async with get_db_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                INSERT INTO google_trending_cache (geo, results, fetched_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    results = VALUES(results),
                    fetched_at = VALUES(fetched_at)
                """,
                (geo, payload, now),
            )
    return now


def _normalize_trend_item(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    title = (item.get("title") or item.get("query") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "search_volume": item.get("search_volume"),
        "increase_percentage": item.get("increase_percentage"),
        "active": item.get("active"),
        "start_timestamp": item.get("start_timestamp"),
        "end_timestamp": item.get("end_timestamp"),
        "trend_breakdown": item.get("trend_breakdown") or [],
    }


async def _fetch_scrapingdog_trending(geo: str) -> List[Dict[str, Any]]:
    params = {
        "api_key": settings.scrapingdog_api_key,
        "geo": geo,
        "hours": str(settings.trending_hours),
        "language": settings.trending_language,
    }
    timeout = httpx.Timeout(
        connect=settings.http_connect_timeout,
        read=settings.http_read_timeout,
        write=settings.http_write_timeout,
        pool=settings.http_pool_timeout,
    )
    url = settings.scrapingdog_url_trending_now

    async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    raw_list = data.get("trending_searches") or data.get("trends") or []
    if not isinstance(raw_list, list):
        raw_list = []

    normalized: List[Dict[str, Any]] = []
    for item in raw_list:
        parsed = _normalize_trend_item(item)
        if parsed:
            normalized.append(parsed)
        if len(normalized) >= settings.trending_store_count:
            break

    if not normalized:
        raise HTTPException(
            status_code=502,
            detail="ScrapingDog trending response contained no usable results",
        )

    logger.info(f"📈 ScrapingDog trending_now fetched {len(normalized)} items for geo={geo}")
    return normalized


async def _refresh_cache(get_db_connection, geo: str) -> Tuple[List[Dict[str, Any]], datetime]:
    top_items = await _fetch_scrapingdog_trending(geo)
    fetched_at = await _save_cache(get_db_connection, geo, top_items)
    return top_items, fetched_at


async def get_trending_results(
    get_db_connection,
    geo: Optional[str] = None,
    serve_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Return `serve_count` random trends from the cached top-10 for `geo`.
    Refreshes from ScrapingDog when cache is missing or older than 24h.
    Concurrent callers for the same geo wait on one refresh.
    """
    geo_code = _normalize_geo(geo)
    count = serve_count if serve_count is not None else settings.trending_serve_count
    count = max(1, min(int(count), settings.trending_store_count))

    cached, fetched_at = await _load_cache(get_db_connection, geo_code)
    refreshed = False

    if cached and _is_fresh(fetched_at):
        items = cached
    else:
        lock = await _lock_for_geo(geo_code)
        async with lock:
            # Another request may have refreshed while we waited
            cached, fetched_at = await _load_cache(get_db_connection, geo_code)
            if cached and _is_fresh(fetched_at):
                items = cached
            else:
                try:
                    items, fetched_at = await _refresh_cache(get_db_connection, geo_code)
                    refreshed = True
                except HTTPException:
                    raise
                except httpx.HTTPStatusError as exc:
                    logger.error(f"ScrapingDog trending HTTP error: {exc}")
                    if cached:
                        # Stale fallback if ScrapingDog fails
                        items = cached
                        logger.warning(f"Serving stale trending cache for geo={geo_code}")
                    else:
                        raise HTTPException(
                            status_code=502,
                            detail=f"ScrapingDog trending API error: {exc.response.status_code}",
                        ) from exc
                except Exception as exc:
                    logger.error(f"ScrapingDog trending failed: {exc}")
                    if cached:
                        items = cached
                        logger.warning(f"Serving stale trending cache for geo={geo_code}")
                    else:
                        raise HTTPException(
                            status_code=502,
                            detail="Failed to fetch Google trending data",
                        ) from exc

    served = _pick_random(items, count)
    if fetched_at and fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    expires_at = None
    age_seconds = None
    if fetched_at:
        expires_at = fetched_at + timedelta(hours=settings.trending_cache_hours)
        age_seconds = int((datetime.now(timezone.utc) - fetched_at).total_seconds())

    return {
        "status_code": 200,
        "success": True,
        "message": "Trending results retrieved",
        "geo": geo_code,
        "cache_refreshed": refreshed,
        "cache_fresh": bool(fetched_at and _is_fresh(fetched_at)),
        "cached_count": len(items),
        "served_count": len(served),
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "age_seconds": age_seconds,
        "data": served,
    }
