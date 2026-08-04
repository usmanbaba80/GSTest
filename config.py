from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database settings - OPTIMIZED for high concurrency
    db_host: str
    db_port: int = 3306
    db_user: str
    db_password: str
    db_database: str
    db_pool_size: int = 32  # Increased from 32 for high concurrency
    db_ssl_ca: Optional[str] = None
    db_server_public_key: Optional[str] = None  # Path to MySQL server public key (PEM)
    
    # Database pool optimization settings
    db_connection_timeout: int = 30  # Increased from 10
    db_pool_reset_session: bool = True
    db_use_pure_python: bool = True
    db_pool_recycle: int = 3600  # Recycle connections every hour
    db_pool_pre_ping: bool = True  # Validate connections before use
    
    # AWS/S3 settings
    aws_access_key_id: str
    aws_secret_access_key: str
    s3_endpoint_url: str = "https://usc1.contabostorage.com"
    s3_bucket_name: str = "fbsdatasync"
    
    # Proxy settings
    proxy_url: str
    
    # NetNut SERP API settings (for general search)
    netnut_serp_username: str = "invicttus"
    netnut_serp_password: str = "Jt4eg8E44dlVsXm"
    netnut_serp_url: str = "https://serp-api.netnut.io/search"

    # ScrapingDog Google Search API settings
    scrapingdog_api_key: str = "68aa5e4b6ab257fb0e4d4884"
    scrapingdog_url: str = "https://api.scrapingdog.com/google"
    scrapingdog_url_general: str = "https://api.scrapingdog.com/google"
    scrapingdog_url_images: str = "https://api.scrapingdog.com/google_images/"
    scrapingdog_url_shopping: str = "https://api.scrapingdog.com/google_shopping/"
    scrapingdog_url_news: str = "https://api.scrapingdog.com/google_news/"
    
    # Application settings
    base_path: str = "https://usc1.contabostorage.com/b3bbd30e3698470b9cc05e271ae9b511:fbsdatasync/"
    log_level: str = "INFO"
    
    # Browser settings - CONSOLIDATED
    browser_pool_size: int = 4  # Reduced to match max concurrent screenshots
    max_tabs_per_browser: int = 5  # One tab per browser for better stability
    browser_headless: bool = True
    browser_launch_timeout: int = 15  # Reduced from 30 to speed up browser creation
    browser_launch_concurrent: int = 4 # Match browser pool size
    browser_health_check_interval: int = 30  # Health check interval in seconds
    
    # Screenshot settings - CONSOLIDATED
    screenshot_timeout: int = 60  # Based on single request timing
    screenshot_max_concurrent: int = 10  # Reduced to prevent resource contention
    screenshot_enable_queuing: bool = True  # Enable intelligent queuing
    screenshot_queue_size: int = 100  # Reasonable queue for sustainable load
    screenshot_queue_timeout: int = 300  # Longer timeout for queued requests (5 minutes)
    screenshot_retry_attempts: int = 0  # SINGLE RETRY: Handle transient failures
    screenshot_enable_request_metrics: bool = True  # Enable request metrics tracking
    # Comma-separated domains that use PROXY_URL for Playwright (e.g. ebay.com)
    screenshot_proxy_domains: str = "ebay.com"
    
    # Search API settings
    search_max_concurrent: int = 200  # Max concurrent search requests
    search_enable_queuing: bool = True  # Enable intelligent queuing
    search_queue_size: int = 1000  # Maximum requests in search queue
    search_queue_timeout: int = 120  # Max wait time in queue (seconds)
    search_cache_timeout: int = 3  # Database cache check timeout (seconds)
    search_retry_attempts: int = 3  # Number of retry attempts for external API
    search_enable_background_caching: bool = True  # Cache results asynchronously
    search_cache_insertion_timeout: int = 15  # Max time for cache insertion
    search_enable_request_metrics: bool = True  # Track detailed metrics
    search_enable_circuit_breaker: bool = False  # Future: circuit breaker pattern
    
    # HTTP Client Pool Configuration
    http_max_connections: int = 200  # Total HTTP connections in pool
    http_max_keepalive: int = 50  # Persistent connections to reuse
    http_keepalive_expiry: int = 30  # Connection lifetime (seconds)
    http_connect_timeout: int = 15  # Connection establishment timeout
    http_read_timeout: int = 60  # Response read timeout
    http_write_timeout: int = 10  # Request write timeout
    http_pool_timeout: int = 5  # Pool acquisition timeout

    # API Security
    api_auth_enabled: bool = False  # When True, require valid Bearer token on all endpoints
    api_bearer_token: Optional[str] = None  # Set in .env: API_BEARER_TOKEN=your-secret-token

    # User authentication (JWT + Google OAuth)
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 days
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: Optional[str] = None
    # Google forbids mixing Data Portability scopes with other scopes in one request.
    # Step 1: identity. Step 2: Chrome bookmarks/history export only.
    google_oauth_scopes_identity: str = "openid email profile"
    google_oauth_scopes_portability: str = (
        "https://www.googleapis.com/auth/dataportability.chrome.bookmarks "
        "https://www.googleapis.com/auth/dataportability.chrome.history"
    )
    # Kept for backward compatibility in docs/env; not used for mixed requests.
    google_oauth_scopes: Optional[str] = None

    # GeoIP settings (GeoLite2 local DB)
    geolite2_db_path: Optional[str] = "GeoLite2-Country.mmdb"  # e.g., /usr/local/share/GeoIP/GeoLite2-Country.mmdb
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Global settings instance
settings = Settings() 