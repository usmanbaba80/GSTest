"""DB schema for Google Trending Now cache (ScrapingDog)."""

from app.logger import logger

TRENDING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS google_trending_cache (
    id INT AUTO_INCREMENT PRIMARY KEY,
    geo VARCHAR(16) NOT NULL,
    results JSON NOT NULL,
    fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_geo (geo),
    INDEX idx_trending_fetched (fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


async def init_trending_tables(get_db_connection):
    """Create trending cache table if missing."""
    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(TRENDING_TABLE_SQL)
        logger.info("✅ Google trending cache table ready")
    except Exception as exc:
        logger.error(f"❌ Failed to initialize trending tables: {exc}")
        raise
