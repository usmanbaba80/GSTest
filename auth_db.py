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
        email_verified TINYINT(1) NOT NULL DEFAULT 0,
        otp_code_hash VARCHAR(255) NULL,
        otp_expires_at TIMESTAMP NULL,
        otp_last_sent_at TIMESTAMP NULL,
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

# For existing deployments created before email verification was added
AUTH_ALTER_SQL = [
    "ALTER TABLE users ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN otp_code_hash VARCHAR(255) NULL",
    "ALTER TABLE users ADD COLUMN otp_expires_at TIMESTAMP NULL",
    "ALTER TABLE users ADD COLUMN otp_last_sent_at TIMESTAMP NULL",
]


async def init_auth_tables(get_db_connection):
    """Create authentication-related tables if they do not exist."""
    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cursor:
                for statement in AUTH_TABLES_SQL:
                    await cursor.execute(statement)

                for statement in AUTH_ALTER_SQL:
                    try:
                        await cursor.execute(statement)
                    except Exception as alter_exc:
                        # Ignore "duplicate column" on already-migrated databases
                        msg = str(alter_exc).lower()
                        if "duplicate column" in msg or "exists" in msg:
                            continue
                        logger.warning(f"Auth schema alter skipped: {alter_exc}")

        logger.info("✅ Authentication tables initialized")
    except Exception as exc:
        logger.error(f"❌ Failed to initialize authentication tables: {exc}")
        raise
