"""Google Trending Now API routes (ScrapingDog + 24h DB cache)."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.trending import service as trending_service
from app.logger import logger

router = APIRouter(prefix="/trending", tags=["Trending"])


def _db():
    from app.main import get_db_connection
    return get_db_connection


@router.get("")
@router.get("/")
async def get_trending(
    geo: Optional[str] = Query(
        None,
        description="Google Trends geo code (e.g. US, GB, IN). Default from settings.",
    ),
    limit: Optional[int] = Query(
        None,
        ge=1,
        le=10,
        description="How many random trends to return from the cached top 10 (default 4).",
    ),
):
    """
    Return random trending searches from a 24h ScrapingDog cache.

    - Stores top 10 trends per geo in DB
    - Serves `limit` random items (default 4)
    - If cache is older than 24h (or missing), refreshes from ScrapingDog once
      (safe under concurrent callers)
    """
    try:
        return await trending_service.get_trending_results(
            _db(),
            geo=geo,
            serve_count=limit,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Trending endpoint failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to get trending results") from exc
