import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


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
    
    # NetNut SERP API settings (legacy)
    netnut_serp_username: str = "invicttus"
    netnut_serp_password: str = "Jt4eg8E44dlVsXm"
    netnut_serp_url: str = "https://serp-api.netnut.io/search"

    # Bright Data general search: API key (optional) OR PROXY_URL SERP zone + brd_json=1
    brightdata_serp_api_key: Optional[str] = None
    brightdata_serp_zone: Optional[str] = None
    brightdata_serp_api_url: str = "https://api.brightdata.com/request"
    # SERP zone proxy (no API key): same credentials as PROXY_URL, SERP port 44445 by default
    brightdata_serp_proxy_url: Optional[str] = None
    brightdata_serp_proxy_port: int = 44445
    brightdata_serp_proxy_verify_ssl: bool = False
    brightdata_serp_max_concurrent: int = 100
    brightdata_serp_max_connections: int = 100
    brightdata_serp_max_keepalive: int = 50
    brightdata_serp_read_timeout: int = 120

    @field_validator("brightdata_serp_zone", mode="before")
    @classmethod
    def _normalize_brightdata_serp_zone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return str(value).strip() or None

    def resolve_brightdata_serp_zone(self) -> str:
        """
        SERP zone for POST /request payload.
        Priority: BRIGHTDATA_SERP_ZONE → zone in PROXY_URL username → serp_api1.
        """
        if self.brightdata_serp_zone:
            return self.brightdata_serp_zone
        zone_from_proxy = self._parse_brightdata_zone_from_proxy_url(self.proxy_url)
        if zone_from_proxy:
            return zone_from_proxy
        return "serp_api1"

    @staticmethod
    def _parse_brightdata_zone_from_proxy_url(proxy_url: str) -> Optional[str]:
        """Parse Bright Data zone from proxy user, e.g. brd-customer-...-zone-serp_api1."""
        try:
            username = urlparse(proxy_url).username or ""
            match = re.search(r"-zone-([^:]+)", username)
            return match.group(1) if match else None
        except Exception:
            return None

    def resolve_brightdata_serp_proxy_url(self) -> str:
        """
        Proxy URL for SERP JSON (brd_json=1). Uses BRIGHTDATA_SERP_PROXY_URL or
        PROXY_URL credentials on brightdata_serp_proxy_port (default 44445).
        """
        if self.brightdata_serp_proxy_url:
            return self.brightdata_serp_proxy_url.strip()
        parsed = urlparse(self.proxy_url)
        if not parsed.hostname:
            return self.proxy_url
        userinfo = ""
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo += f":{parsed.password}"
            userinfo += "@"
        scheme = parsed.scheme or "http"
        return f"{scheme}://{userinfo}{parsed.hostname}:{self.brightdata_serp_proxy_port}"

    # ScrapingDog Google Search API settings
    scrapingdog_api_key: str = "68aa5e4b6ab257fb0e4d4884"
    scrapingdog_url: str = "https://api.scrapingdog.com/google"
    scrapingdog_url_general: str = "https://api.scrapingdog.com/google"
    scrapingdog_url_images: str = "https://api.scrapingdog.com/google_images/"
    scrapingdog_url_shopping: str = "https://api.scrapingdog.com/google_shopping/"
    scrapingdog_url_news: str = "https://api.scrapingdog.com/google_news/"
    scrapingdog_url_videos: str = "https://api.scrapingdog.com/youtube/search"
    scrapingdog_url_trending_now: str = "https://api.scrapingdog.com/google_trends/trending_now"

    # Google Trending Now cache (ScrapingDog)
    trending_cache_hours: int = 24
    trending_store_count: int = 10
    trending_serve_count: int = 4
    trending_default_geo: str = "US"
    trending_hours: str = "24"  # ScrapingDog hours filter: 4, 24, 48, 168
    trending_language: str = "en"

    # Per-search-type provider. Values: brightdata | scrapingdog.
    # Defaults: ScrapingDog for general/images/shop/videos, Bright Data for news.
    search_provider_general: str = "scrapingdog"
    search_provider_isch: str = "scrapingdog"
    search_provider_nws: str = "brightdata"
    search_provider_shop: str = "scrapingdog"
    search_provider_videos: str = "scrapingdog"

    @field_validator(
        "search_provider_general",
        "search_provider_isch",
        "search_provider_nws",
        "search_provider_shop",
        "search_provider_videos",
        mode="before",
    )
    @classmethod
    def _normalize_search_provider(cls, value: Optional[str]) -> str:
        aliases = {
            "brightdata": "brightdata",
            "bright_data": "brightdata",
            "bright-data": "brightdata",
            "scrapingdog": "scrapingdog",
            "scraping_dog": "scrapingdog",
            "scraping-dog": "scrapingdog",
        }
        normalized = aliases.get(str(value or "").strip().lower())
        if not normalized:
            raise ValueError("search provider must be brightdata or scrapingdog")
        return normalized

    def provider_for(self, search_type: str) -> str:
        """Return the configured provider for a search type."""
        providers: Dict[str, str] = {
            "general": self.search_provider_general,
            "isch": self.search_provider_isch,
            "nws": self.search_provider_nws,
            "shop": self.search_provider_shop,
            "videos": self.search_provider_videos,
        }
        return providers.get(search_type, self.search_provider_general)

    def search_types_for_provider(self, provider: str) -> List[str]:
        return [
            search_type
            for search_type in ("general", "isch", "nws", "shop", "videos")
            if self.provider_for(search_type) == provider
        ]
    
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

    # User authentication (JWT). /auth endpoints return 503 until JWT_SECRET_KEY is set.
    jwt_secret_key: Optional[str] = None
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 525600  # 365 days — stay signed in until logout

    # Email OTP via Brevo
    brevo_api_key: Optional[str] = None
    brevo_sender_email: Optional[str] = None
    brevo_sender_name: str = "GS App"
    otp_expire_minutes: int = 10
    otp_resend_cooldown_seconds: int = 60
    # If True and Brevo is not configured, OTP is logged instead of emailed (local/dev only)
    email_otp_debug: bool = False

    # GeoIP settings (GeoLite2 local DB)
    geolite2_db_path: Optional[str] = "GeoLite2-Country.mmdb"  # e.g., /usr/local/share/GeoIP/GeoLite2-Country.mmdb
    
    class Config:
        env_file = str(_ENV_FILE)
        case_sensitive = False
        extra = "ignore"

# Global settings instance
settings = Settings() 