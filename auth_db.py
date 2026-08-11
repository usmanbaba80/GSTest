"""Database schema initialization for user authentication."""

from logger import logger

AUTH_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        email VARCHAR(255) NOT NULL,
        password_hash VARCHAR(255) NULL,
        full_name VARCHAR(255) NULL,
        profile_picture VARCHAR(512) NULL,
        auth_provider VARCHAR(32) NOT NULL DEFAULT 'app',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP NULL,
        UNIQUE KEY unique_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS user_bookmarks (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        title VARCHAR(512) NULL,
        url TEXT NOT NULL,
        folder VARCHAR(255) NULL,
        source VARCHAR(32) NOT NULL DEFAULT 'app',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_bookmark_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_bookmark_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS user_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        title VARCHAR(512) NULL,
        url TEXT NOT NULL,
        visited_at TIMESTAMP NULL,
        source VARCHAR(32) NOT NULL DEFAULT 'app',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_history_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_history_user_visited (user_id, visited_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


async def init_auth_tables(get_db_connection):
    """Create authentication-related tables if they do not exist."""
    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cursor:
                for statement in AUTH_TABLES_SQL:
                    await cursor.execute(statement)
        logger.info("✅ Authentication tables initialized")
    except Exception as exc:
        logger.error(f"❌ Failed to initialize authentication tables: {exc}")
        raise
