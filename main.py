import asyncio
import sys
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
import io
import time
import random
import json
import cv2
import httpx
import threading
import pymysql
import uuid
import mysql.connector
from mysql.connector import pooling
from bs4 import BeautifulSoup
import numpy as np
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from datetime import datetime
from urllib.parse import urlparse
from typing import Tuple, List, Dict, Any, Optional
from ipaddress import ip_address
import geoip2.database
from contextlib import asynccontextmanager
import aiomysql
from botocore.config import Config

# Additional imports for search optimization
from collections import deque
from dataclasses import dataclass, field
import weakref

# Import our custom modules
from config import settings
from models import (
    ScreenshotRequest, SearchRequest, LinkRequest,
    SuccessResponse, ErrorResponse
)
from logger import logger

# Set WindowsProactorEventLoopPolicy if on Windows
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Global rate limiter for NetNut SERP API (high-load optimization)
netnut_api_semaphore = asyncio.Semaphore(50)  # Balanced rate limiting

proxyURLs = {
    'http://': httpx.HTTPTransport(proxy=settings.proxy_url),
    'https://': httpx.HTTPTransport(proxy=settings.proxy_url)
}
connection_pool = None

# GeoIP disabled (was previously initialized when DB provided)

pool_lock = asyncio.Lock()

async def init_connection_pool():
    global connection_pool
    try:
        async with pool_lock:
            connection_pool = await aiomysql.create_pool(
                host=settings.db_host,
                user=settings.db_user,
                password=settings.db_password,
                db=settings.db_database,
                maxsize=settings.db_pool_size,
                ssl=settings.db_ssl_ca,
                autocommit=True
            )
            logger.info("✅ MySQL connection pool initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize connection pool: {e}")
        connection_pool = None
        raise

@asynccontextmanager
async def get_db_connection():
    global connection_pool
    if connection_pool is None:
        logger.error("❌ Database connection pool not initialized. Check database configuration.")
        raise aiomysql.Error("Database connection pool not available. Please check database configuration in .env file.")
    try:
        async with connection_pool.acquire() as conn:
            yield conn
    except aiomysql.Error as e:
        logger.warning(f"⚠ PoolError detected: {e}. Resetting connection pool.")
        try:
            await init_connection_pool()
            if connection_pool is None:
                raise aiomysql.Error("Failed to reinitialize connection pool")
            async with connection_pool.acquire() as conn:
                yield conn
        except Exception as reset_error:
            logger.error(f"❌ Failed to reset connection pool: {reset_error}")
            connection_pool = None
            raise aiomysql.Error(f"Database connection failed: {reset_error}")
    except Exception as e:
        logger.error(f"❌ Unexpected error getting database connection: {e}")
        raise

# =====================================================================
# SEARCH API OPTIMIZATION COMPONENTS
# =====================================================================

class HTTPClientPool:
    """
    Optimized HTTP client pool for external API calls with connection reuse.
    Reduces connection overhead and improves performance for concurrent requests.
    """
    
    def __init__(self):
        self.client = None
        self.lock = asyncio.Lock()
        self._closed = False
    
    async def get_client(self):
        """Get or create optimized HTTP client with connection pooling"""
        if self.client is None and not self._closed:
            async with self.lock:
                if self.client is None and not self._closed:
                    # Advanced connection management for high concurrency
                    limits = httpx.Limits(
                        max_connections=settings.http_max_connections,
                        max_keepalive_connections=settings.http_max_keepalive,
                        keepalive_expiry=settings.http_keepalive_expiry
                    )
                    
                    timeout = httpx.Timeout(
                        connect=settings.http_connect_timeout,
                        read=settings.http_read_timeout,
                        write=settings.http_write_timeout,
                        pool=settings.http_pool_timeout
                    )
                    
                    self.client = httpx.AsyncClient(
                        timeout=timeout,
                        verify=True,
                        limits=limits,
                        http2=False,  # Disable HTTP/2 for stability
                        headers={
                            "User-Agent": "SearchBot/2.0 (High-Performance)",
                            "Accept": "text/html,application/json,*/*",
                            "Accept-Encoding": "gzip, deflate",
                            "Connection": "keep-alive",
                            "Cache-Control": "no-cache"
                        }
                    )
                    logger.info("✅ HTTP client pool initialized with optimized settings")
        
        return self.client
    
    async def close(self):
        """Close the HTTP client and release resources"""
        self._closed = True
        if self.client:
            async with self.lock:
                if self.client:
                    await self.client.aclose()
                    self.client = None
                    logger.info("🔄 HTTP client pool closed")

class SearchRequestQueue:
    """
    Advanced queue manager for search requests with intelligent rate limiting.
    Provides graceful handling of high concurrency with monitoring and metrics.
    """
    
    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.search_max_concurrent)
        self.active_requests = 0
        self.lock = asyncio.Lock()
        self.stats_lock = threading.Lock()  # For synchronous stats updates
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'queued_requests': 0,
            'timeout_requests': 0,
            'rejected_requests': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'external_api_calls': 0,
            'external_api_errors': 0,
            'avg_response_time': 0.0,
            'total_processing_time': 0.0
        }
        self.request_times = deque(maxlen=1000)  # Keep last 1000 request times
    
    async def acquire_search_slot(self) -> bool:
        """Try to acquire a search processing slot immediately"""
        # Use asyncio.wait_for with timeout=0 for non-blocking acquire
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=0.001)  # Very short timeout for non-blocking
            async with self.lock:
                self.active_requests += 1
                self.stats['total_requests'] += 1
            logger.debug(f"🔍 Search slot acquired. Active: {self.active_requests}/{settings.search_max_concurrent}")
            return True
        except asyncio.TimeoutError:
            logger.debug(f"⏳ Search capacity reached. Active: {self.active_requests}/{settings.search_max_concurrent}")
            return False
    
    async def acquire_search_slot_with_wait(self, timeout: int = None) -> bool:
        """Acquire slot with intelligent waiting and queue monitoring"""
        if timeout is None:
            timeout = settings.search_queue_timeout
        
        start_time = time.time()
        try:
            # Calculate queue position for monitoring
            async with self.lock:
                queue_position = max(0, self.active_requests - settings.search_max_concurrent + 1)
                self.stats['queued_requests'] += 1
            
            if queue_position > 0:
                estimated_wait = queue_position * 2  # Estimate 2 seconds per request
                logger.info(f"📝 Request queued. Position: {queue_position}, Est. wait: {estimated_wait}s")
            
            # Use asyncio.wait_for for Python 3.10 compatibility
            await asyncio.wait_for(self.semaphore.acquire(), timeout=timeout)
            
            async with self.lock:
                self.active_requests += 1
                self.stats['successful_requests'] += 1
            
            actual_wait = time.time() - start_time
            logger.info(f"✅ Search slot acquired after {actual_wait:.2f}s wait")
            return True
                
        except asyncio.TimeoutError:
            async with self.lock:
                self.stats['timeout_requests'] += 1
            logger.warning(f"⏰ Search request timed out after {timeout}s")
            return False
    
    def release_search_slot(self):
        """Release a search processing slot"""
        try:
            with self.stats_lock:
                self.active_requests = max(0, self.active_requests - 1)
            self.semaphore.release()
            logger.debug(f"📤 Search slot released. Active: {self.active_requests}")
        except Exception as e:
            logger.warning(f"⚠️ Error releasing search slot: {e}")
    
    async def record_request_metrics(self, response_time: float, cache_hit: bool, success: bool):
        """Record request metrics for monitoring"""
        async with self.lock:
            if settings.search_enable_request_metrics:
                self.request_times.append(response_time)
                self.stats['total_processing_time'] += response_time
                
                if cache_hit:
                    self.stats['cache_hits'] += 1
                else:
                    self.stats['cache_misses'] += 1
                    self.stats['external_api_calls'] += 1
                    
                if not success:
                    self.stats['external_api_errors'] += 1
                
                # Update average response time
                total_requests = self.stats['total_requests']
                if total_requests > 0:
                    self.stats['avg_response_time'] = self.stats['total_processing_time'] / total_requests
    
    async def get_status(self) -> Dict[str, Any]:
        """Get comprehensive queue status and performance metrics"""
        async with self.lock:
            utilization = (self.active_requests / settings.search_max_concurrent) * 100
            available_slots = settings.search_max_concurrent - self.active_requests
            
            # Calculate cache hit rate
            total_cache_requests = self.stats['cache_hits'] + self.stats['cache_misses']
            cache_hit_rate = (self.stats['cache_hits'] / total_cache_requests * 100) if total_cache_requests > 0 else 0
            
            # Calculate success rate
            total_api_calls = self.stats['external_api_calls']
            api_success_rate = ((total_api_calls - self.stats['external_api_errors']) / total_api_calls * 100) if total_api_calls > 0 else 100
            
            # Calculate percentile response times
            recent_times = list(self.request_times)
            recent_times.sort()
            
            p50 = recent_times[len(recent_times)//2] if recent_times else 0
            p95 = recent_times[int(len(recent_times)*0.95)] if recent_times else 0
            p99 = recent_times[int(len(recent_times)*0.99)] if recent_times else 0
            
            return {
                "active_requests": self.active_requests,
                "max_concurrent": settings.search_max_concurrent,
                "utilization_percent": round(utilization, 2),
                "available_slots": available_slots,
                "queue_enabled": settings.search_enable_queuing,
                "estimated_wait_seconds": max(0, (self.active_requests - settings.search_max_concurrent) * 2),
                "performance_metrics": {
                    "avg_response_time": round(self.stats['avg_response_time'], 3),
                    "p50_response_time": round(p50, 3),
                    "p95_response_time": round(p95, 3),
                    "p99_response_time": round(p99, 3),
                    "cache_hit_rate_percent": round(cache_hit_rate, 2),
                    "api_success_rate_percent": round(api_success_rate, 2)
                },
                "statistics": self.stats.copy()
            }

class ScreenshotRequestQueue:
    """
    Manages screenshot request queuing, rate limiting, and performance metrics.
    Similar to SearchRequestQueue but optimized for screenshot operations.
    """
    
    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.screenshot_max_concurrent)
        self.active_requests = 0
        self.lock = asyncio.Lock()
        self.stats_lock = threading.Lock()  # For synchronous stats updates
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'queue_rejections': 0,
            'timeout_errors': 0,
            'avg_response_time': 0.0,
            'cache_hits': 0,
            'cache_misses': 0,
            'browser_creation_count': 0,
            'browser_reuse_count': 0
        }
        self.request_times = deque(maxlen=1000)
        
    async def acquire_screenshot_slot(self) -> bool:
        """Try to acquire a screenshot slot immediately (non-blocking)."""
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=0.001)
            with self.stats_lock:
                self.active_requests += 1
            return True
        except asyncio.TimeoutError:
            return False
    
    async def acquire_screenshot_slot_with_wait(self, timeout: int = None) -> bool:
        """Acquire screenshot slot with optional timeout (for queuing)."""
        if timeout is None:
            timeout = settings.screenshot_queue_timeout
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=timeout)
            with self.stats_lock:
                self.active_requests += 1
            return True
        except asyncio.TimeoutError:
            return False
    
    def release_screenshot_slot(self):
        """Release a screenshot processing slot."""
        try:
            with self.stats_lock:
                self.active_requests = max(0, self.active_requests - 1)
            self.semaphore.release()
        except Exception as e:
            logger.warning(f"⚠️ Error releasing screenshot slot: {e}")
    
    async def record_request_metrics(self, response_time: float, cache_hit: bool, success: bool, browser_created: bool = False):
        """Record metrics for a screenshot request."""
        async with self.lock:
            self.stats['total_requests'] += 1
            
            if success:
                self.stats['successful_requests'] += 1
            else:
                self.stats['failed_requests'] += 1
            
            if cache_hit:
                self.stats['cache_hits'] += 1
            else:
                self.stats['cache_misses'] += 1
            
            if browser_created:
                self.stats['browser_creation_count'] += 1
            else:
                self.stats['browser_reuse_count'] += 1
            
            # Update response time
            self.request_times.append(response_time)
            if self.request_times:
                self.stats['avg_response_time'] = sum(self.request_times) / len(self.request_times)
    
    async def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status of screenshot queue and metrics."""
        async with self.lock:
            total_requests = self.stats['total_requests']
            success_rate = (self.stats['successful_requests'] / total_requests * 100) if total_requests > 0 else 0
            cache_hit_rate = (self.stats['cache_hits'] / (self.stats['cache_hits'] + self.stats['cache_misses']) * 100) if (self.stats['cache_hits'] + self.stats['cache_misses']) > 0 else 0
            
            recent_times = list(self.request_times)[-100:] if self.request_times else []
            recent_avg = sum(recent_times) / len(recent_times) if recent_times else 0
            
            return {
                'active_requests': self.active_requests,
                'max_concurrent': settings.screenshot_max_concurrent,
                'queue_utilization_percent': round((self.active_requests / settings.screenshot_max_concurrent) * 100, 2),
                'total_requests': total_requests,
                'successful_requests': self.stats['successful_requests'], 
                'failed_requests': self.stats['failed_requests'],
                'success_rate_percent': round(success_rate, 2),
                'queue_rejections': self.stats['queue_rejections'],
                'timeout_errors': self.stats['timeout_errors'],
                'avg_response_time_seconds': round(self.stats['avg_response_time'], 2),
                'recent_avg_response_time_seconds': round(recent_avg, 2),
                'cache_hits': self.stats['cache_hits'],
                'cache_misses': self.stats['cache_misses'],
                'cache_hit_rate_percent': round(cache_hit_rate, 2),
                'browser_creation_count': self.stats['browser_creation_count'],
                'browser_reuse_count': self.stats['browser_reuse_count'],
                'queue_enabled': settings.screenshot_enable_queuing,
                'queue_timeout_seconds': settings.screenshot_queue_timeout
            }

# Global instances for search optimization
http_client_pool = HTTPClientPool()
search_queue = SearchRequestQueue()

# Global instances for screenshot optimization  
screenshot_queue = ScreenshotRequestQueue()

# =====================================================================
# END SEARCH API OPTIMIZATION COMPONENTS
# =====================================================================

# Models are now imported from models.py


app = FastAPI(
    title="GS Backend API",
    description="High-performance web scraping, screenshot generation, and search functionality. Optimized for 1500+ concurrent requests.",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.middleware("http")
async def require_bearer_token(request: Request, call_next):
    """Enforce Bearer token authentication when enabled via settings.

    When `settings.api_auth_enabled` is True, every request must include an
    `Authorization: Bearer <token>` header that matches `settings.api_bearer_token`.
    """
    try:
        # Allow all traffic when authentication is disabled
        if not settings.api_auth_enabled:
            return await call_next(request)

        # Public paths: auth endpoints, docs, health
        public_paths = ("/auth", "/health", "/docs", "/redoc", "/openapi.json")
        if request.url.path.startswith(public_paths):
            return await call_next(request)

        expected_token = settings.api_bearer_token

        # If enabled but token is not configured, deny access
        if not expected_token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API token configuration"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication scheme"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        provided_token = parts[1]
        if provided_token != expected_token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Auth OK → proceed
        return await call_next(request)

    except Exception as auth_error:
        # Fail closed on unexpected errors
        logger.error(f"Authentication middleware error: {auth_error}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication failed"},
            headers={"WWW-Authenticate": "Bearer"},
        )

@app.on_event("startup")
async def startup_event():
    """Initialize resources on application startup."""
    try:
        await init_connection_pool()
        logger.info("✅ Database connection pool initialized at startup")

        from auth_db import init_auth_tables
        await init_auth_tables(get_db_connection)
        logger.info("✅ User authentication tables ready")
        logger.info("🚀 Starting GS Backend API...")
        logger.info(f"📊 Browser Configuration: {settings.browser_pool_size} browsers × {settings.max_tabs_per_browser} tabs = {settings.browser_pool_size * settings.max_tabs_per_browser} total capacity")
        logger.info(f"⚡ Screenshot Rate limiting: {settings.screenshot_max_concurrent} concurrent screenshots")
        
        # Initialize search optimization components
        logger.info("🔍 Initializing Search API optimization components...")
        # Load GeoLite2 DB if configured
        global geoip_reader
        try:
            if settings.geolite2_db_path and os.path.exists(settings.geolite2_db_path):
                geoip_reader = geoip2.database.Reader(settings.geolite2_db_path)
                logger.info(f"🌍 GeoLite2 database loaded: {settings.geolite2_db_path}")
            else:
                logger.info("🌍 GeoLite2 database not configured; set GEOLITE2_DB_PATH to enable GeoIP")
        except Exception as e:
            geoip_reader = None
            logger.warning(f"⚠️ Failed to load GeoLite2 DB: {e}")
        
        # Initialize HTTP client pool
        try:
            await http_client_pool.get_client()
            logger.info("✅ HTTP client pool initialized")
            logger.info(f"🌐 HTTP Client config: {settings.http_max_connections} max connections, {settings.http_max_keepalive} keepalive")
        except Exception as e:
            logger.warning(f"⚠️ HTTP client pool initialization failed: {e}")
        
        # Log search configuration
        logger.info(f"🔍 Search API Configuration:")
        logger.info(f"   - Max concurrent: {settings.search_max_concurrent}")
        logger.info(f"   - Queue enabled: {settings.search_enable_queuing}")
        logger.info(f"   - Queue size: {settings.search_queue_size}")
        logger.info(f"   - Queue timeout: {settings.search_queue_timeout}s")
        logger.info(f"   - Database pool: {settings.db_pool_size} connections")
        logger.info(f"   - Cache timeout: {settings.search_cache_timeout}s")
        logger.info(f"   - Background caching: {settings.search_enable_background_caching}")
        
        # Test search queue functionality
        try:
            initial_status = await search_queue.get_status()
            logger.info(f"✅ Search queue manager initialized and ready")
        except Exception as e:
            logger.warning(f"⚠️ Search queue status check failed: {e}")
        
        # Initialize and log screenshot optimization components
        logger.info("📷 Initializing Screenshot API optimization components...")
        
        # Log screenshot configuration
        logger.info(f"📷 Screenshot API Configuration:")
        logger.info(f"   - Max concurrent: {settings.screenshot_max_concurrent}")
        logger.info(f"   - Queue enabled: {settings.screenshot_enable_queuing}")
        logger.info(f"   - Queue size: {settings.screenshot_queue_size}")
        logger.info(f"   - Queue timeout: {settings.screenshot_queue_timeout}s")
        logger.info(f"   - Retry attempts: {settings.screenshot_retry_attempts}")
        logger.info(f"   - Screenshot timeout: {settings.screenshot_timeout}s")
        logger.info(f"   - Browser pool size: {settings.browser_pool_size}")
        logger.info(f"   - Max tabs per browser: {settings.max_tabs_per_browser}")
        logger.info(f"   - Concurrent browser creation: {settings.browser_launch_concurrent}")
        
        # Test screenshot queue functionality
        try:
            screenshot_status = await screenshot_queue.get_status()
            logger.info(f"✅ Screenshot queue manager initialized and ready")
        except Exception as e:
            logger.warning(f"⚠️ Screenshot queue status check failed: {e}")
        
        # Pre-warm the browser pool by initializing playwright
        try:
            logger.info("🔄 Starting browser pool initialization...")
            await browser_pool.initialize()
            logger.info("✅ Browser pool manager initialized")
        except Exception as e:
            logger.error(f"❌ CRITICAL: Browser pool initialization failed: {e}")
            logger.warning("⚠️ Server will start WITHOUT browser pool - screenshots will fail!")
            # Don't crash the server, but log the critical issue
        
        # Verify browser pool status after initialization
        try:
            pool_status = await browser_pool.get_pool_status()
            logger.info(f"📊 Browser pool verification:")
            logger.info(f"   • Total browsers created: {pool_status['total_browsers']}")
            logger.info(f"   • Max browsers configured: {pool_status['max_browsers']}")
            logger.info(f"   • Browser utilization: {pool_status['browser_utilization_percent']}%")
            logger.info(f"   • Browser details: {len(pool_status['browsers'])} browsers ready")
            
            if pool_status['total_browsers'] >= pool_status['max_browsers']:
                logger.info("🚀 Browser pool is FULLY READY for concurrent requests!")
            else:
                logger.warning(f"⚠️ Browser pool INCOMPLETE: {pool_status['total_browsers']}/{pool_status['max_browsers']} browsers")
                
            # Show individual browser status
            for browser in pool_status['browsers'][:5]:  # Show first 5 browsers
                logger.info(f"   • Browser #{browser['browser_id']}: {browser['active_tabs']} active tabs")
                
        except Exception as e:
            logger.error(f"❌ Browser pool verification failed: {e}")
            # Try to get basic info without detailed status
            try:
                logger.info(f"🔍 Basic browser count: {len(browser_pool.browsers)} browsers in pool")
            except Exception as e2:
                logger.error(f"❌ Even basic browser count failed: {e2}")
        
        # Test database connection
        try:
            async with get_db_connection() as conn:
                await conn.ping()
            logger.info("✅ Database connection verified")
        except Exception as e:
            logger.warning(f"⚠️ Database connection test failed: {e}")
        
        # Test S3 connection
        try:
            if s3_client:
                s3_client.list_objects_v2(Bucket=settings.s3_bucket_name, MaxKeys=1)
                logger.info("✅ S3 storage connection verified")
            else:
                logger.warning("⚠️ S3 client not initialized")
        except Exception as e:
            logger.warning(f"⚠️ S3 storage connection test failed: {e}")
        
        # Test search API health
        try:
            client = await http_client_pool.get_client()
            test_response = await client.get("https://www.google.com/search?q=startup_test&num=1")
            if test_response.status_code == 200:
                logger.info("✅ External search API connectivity verified")
            else:
                logger.warning(f"⚠️ External search API test returned: {test_response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ External search API connectivity test failed: {e}")
        
        # Log total system capacity
        total_screenshot_capacity = settings.browser_pool_size * settings.max_tabs_per_browser
        total_search_capacity = settings.search_max_concurrent + (settings.search_queue_size if settings.search_enable_queuing else 0)
        logger.info(f"🎯 Total System Capacity:")
        logger.info(f"   - Screenshots: {settings.screenshot_max_concurrent} concurrent ({total_screenshot_capacity} browser tabs)")
        logger.info(f"   - Search: {settings.search_max_concurrent} concurrent + {settings.search_queue_size if settings.search_enable_queuing else 0} queue = {total_search_capacity} total")
        
        logger.info("🎉 GS Backend API startup completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Critical error during startup: {e}")
        global connection_pool
        connection_pool = None
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on application shutdown."""
    try:
        logger.info("🛑 Shutting down GS Backend API...")
        
        # Log final search metrics before shutdown
        try:
            final_search_stats = await search_queue.get_status()
            logger.info(f"🔍 Final search metrics:")
            logger.info(f"   - Total requests: {final_search_stats['statistics']['total_requests']}")
            logger.info(f"   - Success rate: {final_search_stats['performance_metrics']['api_success_rate_percent']:.1f}%")
            logger.info(f"   - Cache hit rate: {final_search_stats['performance_metrics']['cache_hit_rate_percent']:.1f}%")
            logger.info(f"   - Avg response time: {final_search_stats['performance_metrics']['avg_response_time']:.2f}s")
            logger.info(f"   - Rejected requests: {final_search_stats['statistics']['rejected_requests']}")
        except Exception as e:
            logger.warning(f"⚠️ Error getting final search metrics: {e}")
        
        # Clean up HTTP client pool
        try:
            await http_client_pool.close()
            logger.info("✅ HTTP client pool cleanup completed")
        except Exception as e:
            logger.warning(f"⚠️ HTTP client pool cleanup error: {e}")
        # Close GeoIP reader
        global geoip_reader
        try:
            if geoip_reader:
                geoip_reader.close()
                geoip_reader = None
                logger.info("🌍 GeoLite2 reader closed")
        except Exception:
            pass
        
        # Clean up browser pool
        await browser_pool.cleanup()
        logger.info("✅ Browser pool cleanup completed")
        
        # Log final screenshot metrics
        final_stats = metrics.get_stats()
        logger.info(f"📊 Final screenshot metrics: {final_stats['total_requests']} total requests, "
                   f"{final_stats['success_rate_percent']:.1f}% success rate, "
                   f"{final_stats['average_response_time_seconds']:.2f}s avg response time")
        
        logger.info("👋 GS Backend API shutdown completed")
        
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")

browser = None

class BrowserPoolManager:
    """
    Manages a pool of browser instances with tab limits.
    Optimized for high-load scenarios like 1500+ concurrent requests.
    FIXED: Async locks and parallel browser creation for true concurrency.
    """
    
    def __init__(self, max_tabs_per_browser: int = 10, max_browsers: int = 5, concurrent_browser_creation: int = 2):
        self.max_tabs_per_browser = max_tabs_per_browser
        self.max_browsers = max_browsers
        self.browsers: List[Dict[str, Any]] = []
        self.playwright = None
        self.lock = asyncio.Lock()  # ✅ FIXED: Use async lock instead of threading.Lock
        self.active_requests = 0
        self.max_concurrent_screenshots = settings.screenshot_max_concurrent
        self.semaphore = asyncio.Semaphore(self.max_concurrent_screenshots)
        self.browser_creation_semaphore = asyncio.Semaphore(concurrent_browser_creation)  # ✅ NEW: Configurable concurrent browser creation
        self.creating_browsers = set()  # ✅ NEW: Track browsers being created
        
    async def initialize(self):
        """Initialize the browser pool manager and pre-create browsers for optimal performance."""
        if self.playwright is None:
            self.playwright = await async_playwright().start()
            logger.info("🌐 Browser pool manager initialized")
            
            # Pre-create browsers for immediate parallel processing
            await self._pre_create_browsers()
    
    async def _pre_create_browsers(self):
        """Pre-create browsers during startup to avoid race conditions during concurrent requests."""
        startup_start = time.time()
        logger.info(f"🚀 Pre-creating {self.max_browsers} browsers for optimal performance...")
        logger.info(f"📊 Browser creation config: concurrent_creation={self.browser_creation_semaphore._value}, max_browsers={self.max_browsers}")
        
        # Create browsers in parallel batches to avoid overwhelming the system
        # 🚀 FORCE SINGLE BATCH: Create all browsers simultaneously for maximum speed
        batch_size = self.max_browsers  # Force single batch instead of limiting by semaphore
        logger.info(f"📦 Using batch size: {batch_size} (SINGLE BATCH MODE for maximum speed)")
        
        total_created = 0
        for batch_start in range(0, self.max_browsers, batch_size):
            batch_end = min(batch_start + batch_size, self.max_browsers)
            batch_start_time = time.time()
            logger.info(f"🔄 Creating browser batch {batch_start+1}-{batch_end}...")
            
            tasks = []
            for i in range(batch_start, batch_end):
                browser_id = i + 1
                task = self._create_new_browser_with_safe_id(browser_id)
                tasks.append(task)
            
            # Create browsers in parallel within each batch
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Count successful creations
                successful_in_batch = 0
                for idx, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"❌ Browser {batch_start + idx + 1} creation failed: {result}")
                    else:
                        successful_in_batch += 1
                        total_created += 1
                
                batch_time = time.time() - batch_start_time
                logger.info(f"✅ Batch {batch_start+1}-{batch_end} completed: {successful_in_batch}/{batch_end-batch_start} browsers in {batch_time:.2f}s")
                
            except Exception as e:
                logger.error(f"⚠️ Critical error in batch {batch_start+1}-{batch_end}: {e}")
        
        total_startup_time = time.time() - startup_start
        logger.info(f"🎉 Browser pool startup complete! Created {total_created}/{self.max_browsers} browsers in {total_startup_time:.2f}s")
        
        if total_created < self.max_browsers:
            logger.warning(f"⚠️ Only {total_created}/{self.max_browsers} browsers created successfully!")
        else:
            logger.info(f"🚀 All {total_created} browsers ready for immediate parallel processing!")
    
    async def get_browser_with_capacity(self) -> Dict[str, Any]:
        """
        Get a browser instance that has capacity for more tabs.
        FIXED: Round-robin selection with fallback to least busy browser.
        
        Returns:
            Dictionary with browser instance and metadata
        """
        async with self.lock:
            if not self.browsers:
                raise Exception("No browsers available - browser pool may not be initialized")
            
            # Initialize round-robin counter if not exists
            if not hasattr(self, '_round_robin_index'):
                self._round_robin_index = 0
            
            # Try round-robin selection first (better distribution)
            for attempt in range(len(self.browsers)):
                browser_index = (self._round_robin_index + attempt) % len(self.browsers)
                browser_info = self.browsers[browser_index]
                
                if browser_info['active_tabs'] < self.max_tabs_per_browser:
                    # Update round-robin index for next request
                    self._round_robin_index = (browser_index + 1) % len(self.browsers)
                    
                    logger.debug(f"🎯 Round-robin selected browser #{browser_info['browser_id']} "
                                f"(index {browser_index}) with {browser_info['active_tabs']}/{self.max_tabs_per_browser} tabs")
                    return browser_info
            
            # All browsers at capacity - fall back to least busy
            sorted_browsers = sorted(self.browsers, key=lambda x: x['active_tabs'])
            least_busy = sorted_browsers[0]
            
            logger.warning(f"⚠️ All browsers at capacity, using least busy browser #{least_busy['browser_id']} "
                          f"with {least_busy['active_tabs']} tabs")
            return least_busy
    
    async def _create_new_browser_with_safe_id(self, safe_id: int) -> Dict[str, Any]:
        """
        Create a new browser instance with safe ID handling.
        FIXED: No browser_id variable references in error handling.
        """
        creation_start = time.time()
        logger.debug(f"🔄 Creating browser #{safe_id}...")
        
        async with self.browser_creation_semaphore:
            try:
                browser_info = await self._create_new_browser()
                browser_info['browser_id'] = safe_id
                async with self.lock:
                    self.browsers.append(browser_info)
                
                creation_time = time.time() - creation_start
                logger.info(f"✅ Browser #{safe_id} created successfully in {creation_time:.2f}s (total browsers: {len(self.browsers)})")
                return browser_info
                
            except Exception as e:
                creation_time = time.time() - creation_start
                logger.error(f"❌ Browser #{safe_id} creation failed after {creation_time:.2f}s: {type(e).__name__}: {e}")
                # Log more details for debugging
                logger.error(f"🔍 Browser creation details: playwright={self.playwright is not None}, semaphore_value={self.browser_creation_semaphore._value}")
                raise e



    async def _create_new_browser(self) -> Dict[str, Any]:
        """Create a new browser instance optimized for high-load scenarios."""
        try:
            # Chrome launch options matching Puppeteer configuration
            browser_args = [
                # Core settings (matching Puppeteer)
                '--no-sandbox',                                # Required for some environments
                '--disable-setuid-sandbox',                    # Disable setuid sandbox
                '--disable-dev-shm-usage',                     # Disable /dev/shm usage
                '--disable-gpu',                               # Disable GPU acceleration
                
                # Lazy Loading and Preload optimizations
                '--disable-lazy-loading',                      # Disable all lazy loading
                '--disable-lazy-image-loading',                # Disable image lazy loading
                '--disable-lazy-frame-loading',                # Disable iframe lazy loading
                '--blink-settings=lazyImageLoadingDistanceThresholdPx=0',  # Force immediate image loading
                '--blink-settings=lazyFrameLoadingDistanceThresholdPx=0',  # Force immediate frame loading
                '--preload-enabled',                           # Enable resource preloading
                '--enable-preload',                            # Reinforce preloading behavior
                '--enable-features=NetworkServiceInProcess',    # Network service in main process
                '--enable-network-service-in-process',         # Keep network ops in main process
                
                # Performance optimizations
                '--disable-background-timer-throttling',       # Prevent timer throttling
                '--disable-backgrounding-occluded-windows',    # Prevent background throttling
                '--disable-renderer-backgrounding',            # Prevent renderer throttling
                '--disable-background-networking',             # Disable background network activity
                '--disable-features=IsolateOrigins,site-per-process', # Disable isolation
                '--disable-site-isolation-trials',             # Disable site isolation
                '--disable-web-security',                      # Disable web security for compatibility
                
                # Memory optimizations
                '--disable-extensions',                        # Disable extensions
                '--disable-component-extensions-with-background-pages', # Disable background extensions
                '--disable-default-apps',                      # Disable default apps
                '--disable-sync',                              # Disable sync
                '--disable-translate',                         # Disable translate
                '--disable-background-downloads',              # Disable background downloads
                '--disable-client-side-phishing-detection',    # Disable phishing detection
                '--disable-component-update',                  # Disable component updates
                '--disable-domain-reliability',                # Disable domain reliability
                '--disable-breakpad',                         # Disable crash reporting
                '--disable-ipc-flooding-protection',          # Disable IPC flooding protection
                
                # Network optimizations
                '--enable-tcp-fast-open',                     # Enable TCP fast open
                '--disable-features=VizDisplayCompositor',     # Disable compositor
                '--force-device-scale-factor=1',              # Force scale factor
                '--max-connections-per-host=6',               # Limit connections per host
                '--use-gl=swiftshader',                       # Use SwiftShader for rendering
                '--disable-blink-features=AutomationControlled', # Hide automation
                
                # Additional stability settings
                '--ignore-certificate-errors',                # Ignore SSL errors
                '--allow-running-insecure-content',           # Allow mixed content
                '--disable-http2',                           # Force HTTP/1.1
                '--disable-popup-blocking',                   # Disable popup blocker
                '--no-default-browser-check',                # Skip default browser check
                '--no-first-run',                           # Skip first run tasks
                '--metrics-recording-only',                  # Minimal metrics
                '--password-store=basic',                    # Basic password store
                '--use-mock-keychain'                       # Mock keychain
            ]
            
            browser = await self.playwright.chromium.launch(
                headless=settings.browser_headless,
                args=browser_args,
                timeout=settings.browser_launch_timeout * 1000  # Convert to milliseconds
            )
            
            browser_info = {
                'browser': browser,
                'active_tabs': 0,
                'created_at': datetime.utcnow(),
                'browser_id': 0  # Will be set by caller
            }
            
            return browser_info
            
        except Exception as e:
            logger.error(f"❌ Failed to create new browser: {e}")
            raise
    
    async def acquire_screenshot_slot(self) -> bool:
        """
        Acquire a slot for screenshot processing with rate limiting.
        
        Returns:
            True if slot acquired, False if at capacity
        """
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=0.001)
            # ✅ FIXED: Use simple counter increment without async lock for performance
            self.active_requests += 1
            logger.debug(f"📊 Screenshot slot acquired. Active requests: {self.active_requests}/{self.max_concurrent_screenshots}")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Screenshot capacity reached. Active requests: {self.active_requests}/{self.max_concurrent_screenshots}")
            return False
    
    def release_screenshot_slot(self):
        """Release a screenshot processing slot."""
        try:
            # ✅ FIXED: Use simple counter decrement without async lock for performance
            self.active_requests = max(0, self.active_requests - 1)
            self.semaphore.release()
            logger.debug(f"📊 Screenshot slot released. Active requests: {self.active_requests}/{self.max_concurrent_screenshots}")
        except Exception as e:
            logger.warning(f"⚠️ Error releasing screenshot slot: {e}")

    async def get_page(
        self,
        ss_width: int = 1920,
        ss_height: int = 1080,
        use_proxy: bool = False,
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Get a new page (tab) from an available browser.
        
        Args:
            ss_width: Screenshot width for viewport
            ss_height: Screenshot height for viewport
            
        Returns:
            Tuple of (page, browser_info)
        """
        await self.initialize()
        
        # Retry logic for browser failures
        max_retries = 3
        for attempt in range(max_retries):
            browser_info = await self.get_browser_with_capacity()
            
            try:
                # Check if browser is still connected before using it
                if not await self._is_browser_healthy(browser_info):
                    logger.warning(f"🔄 Browser #{browser_info['browser_id']} is not healthy, removing from pool")
                    await self._remove_browser_from_pool(browser_info)
                    continue
                
                # Create new context (this is like opening a new tab)
                context_options: Dict[str, Any] = {
                    "viewport": {"width": ss_width, "height": ss_height},
                    "bypass_csp": True,
                    "ignore_https_errors": True,
                    "java_script_enabled": True,
                    "has_touch": False,
                    "is_mobile": False,
                    "extra_http_headers": {
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                        'Upgrade-Insecure-Requests': '1',
                        'Connection': 'keep-alive',
                    },
                    "user_agent": (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    ),
                    "locale": 'en-US',
                    "timezone_id": 'America/New_York',
                    "offline": False,
                    "http_credentials": None,
                }
                if use_proxy and settings.proxy_url:
                    context_options["proxy"] = _parse_proxy_for_playwright(settings.proxy_url)
                    logger.info("📷 Using configured proxy for screenshot context")
                context = await browser_info['browser'].new_context(**context_options)
                await context.add_init_script(STEALTH_INIT_SCRIPT)
                page = await context.new_page()
                
                # Set timeouts for high-load scenarios
                page.set_default_navigation_timeout(settings.screenshot_timeout * 1000)
                page.set_default_timeout(settings.screenshot_timeout * 1000)
                
                # ✅ FIXED: Increment active tab count with async lock
                async with self.lock:
                    browser_info['active_tabs'] += 1
                
                # Store context reference for cleanup
                page._gs_context = context
                page._gs_browser_info = browser_info
                
                logger.debug(f"📄 Created new tab in browser #{browser_info['browser_id']} "
                            f"(tabs: {browser_info['active_tabs']}/{self.max_tabs_per_browser})")
                
                return page, browser_info
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to create page in browser #{browser_info['browser_id']} (attempt {attempt + 1}/{max_retries}): {e}")
                
                # Remove the faulty browser from pool
                await self._remove_browser_from_pool(browser_info)
                
                # If this is the last attempt, raise the error
                if attempt == max_retries - 1:
                    logger.error(f"❌ Failed to create page after {max_retries} attempts: {e}")
                    raise
                
                # Wait a moment before retrying
                await asyncio.sleep(0.1)
        
        # This should never be reached, but just in case
        raise Exception("Failed to create page after maximum retries")
    
    async def _is_browser_healthy(self, browser_info: Dict[str, Any]) -> bool:
        """Check if a browser is still healthy and connected."""
        try:
            # Try to get browser contexts - this will fail if browser is closed
            contexts = browser_info['browser'].contexts
            return True
        except Exception:
            return False
    
    async def _remove_browser_from_pool(self, browser_info: Dict[str, Any]):
        """Remove a browser from the pool (when it's closed or unhealthy)."""
        try:
            # ✅ FIXED: Use async lock for removing browser from pool
            async with self.lock:
                if browser_info in self.browsers:
                    self.browsers.remove(browser_info)
                    logger.info(f"🗑️ Removed unhealthy browser #{browser_info['browser_id']} from pool")
            
            # Try to close the browser gracefully
            try:
                await browser_info['browser'].close()
            except:
                pass  # Browser might already be closed
                
        except Exception as e:
            logger.warning(f"⚠️ Error removing browser from pool: {e}")
    
    async def release_page(self, page: Any):
        """
        Release a page and its context, decrementing the tab count.
        FIXED: Enhanced cleanup with better error handling and forced tab count decrement.
        
        Args:
            page: The page to release
        """
        browser_info = None
        context = None
        tab_decremented = False
        
        try:
            # Get browser info and context references
            browser_info = getattr(page, '_gs_browser_info', None)
            context = getattr(page, '_gs_context', None)
            
            # CRITICAL: Always decrement tab count first, even if cleanup fails
            if browser_info:
                async with self.lock:
                    browser_info['active_tabs'] = max(0, browser_info['active_tabs'] - 1)
                    tab_decremented = True
                
                logger.debug(f"🗑️ Decremented tab count for browser #{browser_info['browser_id']} "
                            f"(remaining tabs: {browser_info['active_tabs']})")
            
            # Now attempt to close page and context
            if page:
                try:
                    await page.close()
                    logger.debug("📄 Page closed successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing page: {e}")
            
            if context:
                try:
                    await context.close()
                    logger.debug("🔧 Context closed successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing context: {e}")
        
        except Exception as e:
            logger.error(f"❌ Critical error in release_page: {e}")
            
            # EMERGENCY: If tab count wasn't decremented due to error, force it
            if not tab_decremented and browser_info:
                try:
                    async with self.lock:
                        browser_info['active_tabs'] = max(0, browser_info['active_tabs'] - 1)
                    logger.warning(f"🚨 EMERGENCY: Force decremented tab count for browser #{browser_info['browser_id']}")
                except Exception as emergency_e:
                    logger.error(f"💥 CRITICAL: Could not decrement tab count: {emergency_e}")
        
        finally:
            # Clear references to prevent memory leaks
            if page:
                try:
                    if hasattr(page, '_gs_browser_info'):
                        delattr(page, '_gs_browser_info')
                    if hasattr(page, '_gs_context'):
                        delattr(page, '_gs_context')
                except:
                    pass  # Ignore cleanup errors
    
    async def get_pool_status(self) -> Dict[str, Any]:
        """Get current status of the browser pool."""
        total_tabs = sum(browser_info['active_tabs'] for browser_info in self.browsers)
        max_total_tabs = len(self.browsers) * self.max_tabs_per_browser
        
        # Calculate utilization percentages
        browser_utilization = (len(self.browsers) / self.max_browsers) * 100 if self.max_browsers > 0 else 0
        tab_utilization = (total_tabs / max_total_tabs) * 100 if max_total_tabs > 0 else 0
        request_utilization = (self.active_requests / self.max_concurrent_screenshots) * 100 if self.max_concurrent_screenshots > 0 else 0
        
        return {
            "total_browsers": len(self.browsers),
            "max_browsers": self.max_browsers,
            "browser_utilization_percent": round(browser_utilization, 2),
            "total_active_tabs": total_tabs,
            "max_possible_tabs": max_total_tabs,
            "tab_utilization_percent": round(tab_utilization, 2),
            "max_tabs_per_browser": self.max_tabs_per_browser,
            "active_screenshot_requests": self.active_requests,
            "max_concurrent_screenshots": self.max_concurrent_screenshots,
            "request_utilization_percent": round(request_utilization, 2),
            "browsers": [
                {
                    "browser_id": info['browser_id'],
                    "active_tabs": info['active_tabs'],
                    "tab_utilization_percent": round((info['active_tabs'] / self.max_tabs_per_browser) * 100, 2),
                    "created_at": info['created_at'].isoformat()
                }
                for info in self.browsers
            ]
        }
    
    async def cleanup(self):
        """Clean up all browser instances."""
        logger.info("🧹 Cleaning up browser pool...")
        
        for browser_info in self.browsers:
            try:
                await browser_info['browser'].close()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
        
        if self.playwright:
            await self.playwright.stop()
        
        self.browsers.clear()
        logger.info("✅ Browser pool cleanup completed")

# Global browser pool manager - OPTIMIZED (instantiated after class definition)
browser_pool = BrowserPoolManager(
    max_tabs_per_browser=settings.max_tabs_per_browser,
    max_browsers=settings.browser_pool_size,
    concurrent_browser_creation=settings.browser_launch_concurrent
)

# Global performance metrics
class PerformanceMetrics:
    """Track system performance metrics for monitoring."""
    
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_processing_time = 0.0
        self.start_time = datetime.utcnow()
        self.lock = threading.Lock()
    
    def increment_total_requests(self):
        with self.lock:
            self.total_requests += 1
    
    def increment_successful_requests(self, processing_time: float):
        with self.lock:
            self.successful_requests += 1
            self.total_processing_time += processing_time
    
    def increment_failed_requests(self):
        with self.lock:
            self.failed_requests += 1
    
    def increment_cache_hits(self):
        with self.lock:
            self.cache_hits += 1
    
    def increment_cache_misses(self):
        with self.lock:
            self.cache_misses += 1
    
    def get_stats(self) -> Dict[str, Any]:
        with self.lock:
            uptime = (datetime.utcnow() - self.start_time).total_seconds()
            avg_response_time = (
                self.total_processing_time / self.successful_requests 
                if self.successful_requests > 0 else 0
            )
            success_rate = (
                (self.successful_requests / self.total_requests * 100) 
                if self.total_requests > 0 else 0
            )
            cache_hit_rate = (
                (self.cache_hits / (self.cache_hits + self.cache_misses) * 100)
                if (self.cache_hits + self.cache_misses) > 0 else 0
            )
            
            return {
                "uptime_seconds": round(uptime, 2),
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate_percent": round(success_rate, 2),
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_hit_rate_percent": round(cache_hit_rate, 2),
                "average_response_time_seconds": round(avg_response_time, 2),
                "requests_per_minute": round((self.total_requests / uptime * 60) if uptime > 0 else 0, 2)
            }

# Global metrics instance
metrics = PerformanceMetrics()

@app.get("/health", response_model=Dict[str, Any])
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for monitoring.
    
    Returns:
        Dictionary with service health status
        
    Raises:
        HTTPException: If service is unhealthy
    """
    try:
        # Check database connection
        try:
            if connection_pool is None:
                db_status = "not_configured"
            else:
                async with get_db_connection() as conn:
                    await conn.ping()
                db_status = "connected"
        except Exception as e:
            logger.debug(f"Database health check failed: {e}")
            db_status = "disconnected"
        
        # Check browser pool status
        browser_pool_status = await browser_pool.get_pool_status()
        
        # Check S3 connection
        try:
            if s3_client:
                s3_client.list_objects_v2(Bucket=settings.s3_bucket_name, MaxKeys=1)
                s3_status = "connected"
            else:
                s3_status = "not_configured"
        except Exception as e:
            s3_status = "disconnected"
        
        # Get performance metrics
        performance_stats = metrics.get_stats()
        
        logger.info("Health check passed")
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "configuration": {
                "max_concurrent_screenshots": settings.screenshot_max_concurrent,
                "browser_pool_size": settings.browser_pool_size,
                "max_tabs_per_browser": settings.max_tabs_per_browser,
                "total_capacity": settings.browser_pool_size * settings.max_tabs_per_browser
            },
            "services": {
                "database": db_status,
                "browser_pool": browser_pool_status,
                "s3_storage": s3_status
            },
            "performance_metrics": performance_stats
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503, 
            detail=f"Service unhealthy: {str(e)}"
        )


# Initialize S3 client for Contabo storage with optimized concurrency settings
try:
    # 🚀 S3 CONCURRENCY OPTIMIZATION: Configure for better parallel uploads
    s3_config = Config(
        # Connection pool settings for concurrent uploads
        max_pool_connections=50,  # Increase from default 10 to support more concurrent uploads
        
        # Retry configuration for reliability under high load
        retries={
            'max_attempts': 3,
            'mode': 'adaptive'  # Adaptive retry mode for better performance
        },
        
        # Timeout settings optimized for slice uploads
        connect_timeout=10,  # Fast connection establishment
        read_timeout=30,     # Reasonable read timeout for image uploads
        
        # Regional configuration
        region_name='us-east-1'  # Default region for better performance
    )
    
    s3_client = boto3.client(
        's3',
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=s3_config  # Apply optimized configuration
    )
    logger.info("✅ S3 client initialized with optimized concurrency settings (max_pool_connections=50)")
except Exception as e:
    logger.warning(f"⚠️ S3 client initialization failed: {e}")
    s3_client = None
    logger.info("💡 App will start without S3 functionality. Configure AWS credentials in .env for full functionality.")


# =====================================================================
# OPTIMIZED SEARCH API ENDPOINTS
# =====================================================================

@app.get("/search", response_model=Dict[str, Any])
async def search(
    query: str = Query(..., min_length=1, max_length=500, description="Search query"),
    searchType: str = Query(..., regex="^(general|nws|isch|shop)$", description="Type of search results"),
    start: int = Query(0, ge=0, le=1000, description="Start index"),
    limit: int = Query(5, ge=1, le=100, description="Limit of results"),
    page: int = Query(0, ge=0, description="Page number (only used for general search type)"),
    request: Request = None,
) -> Dict[str, Any]:
    """
    Optimized search endpoint with intelligent rate limiting, queuing, and performance monitoring.
    
    Features:
    - Intelligent request queuing instead of immediate rejection
    - HTTP connection pooling for better performance
    - Non-blocking database operations with timeouts
    - Background caching to prevent response delays
    - Comprehensive metrics and monitoring
    
    Args:
        query: Search query string
        searchType: Type of search (general, nws, isch, shop)
        start: Start index for pagination
        limit: Number of results to return
        
    Returns:
        Dictionary containing search results and metadata
        
    Raises:
        HTTPException: For various error conditions including rate limiting
    """
    
    # Try to acquire search slot immediately
    if await search_queue.acquire_search_slot():
        # Process immediately
        try:
            return await _process_search_request(query, searchType, start, limit, page, request)
        finally:
            search_queue.release_search_slot()
    
    # If immediate processing unavailable, use intelligent queuing
    elif settings.search_enable_queuing:
        if await search_queue.acquire_search_slot_with_wait(settings.search_queue_timeout):
            try:
                result = await _process_search_request(query, searchType, start, limit, page, request)
                result["message"] += " (was queued)"
                result["queued"] = True
                return result
            finally:
                search_queue.release_search_slot()
        else:
            # Queue timeout
            with search_queue.stats_lock:
                search_queue.stats['rejected_requests'] += 1
            raise HTTPException(
                status_code=408,
                detail=f"Request timed out in queue after {settings.search_queue_timeout}s. Server is experiencing high load, please try again later."
            )
    else:
        # Queuing disabled, immediate rejection
        with search_queue.stats_lock:
            search_queue.stats['rejected_requests'] += 1
        raise HTTPException(
            status_code=429,
            detail=f"Search service at capacity ({settings.search_max_concurrent} concurrent requests). Please retry later."
        )

# Country detection disabled; using fixed parameters for ScrapingDog

def _get_client_ip_from_request(request: Optional[Request]) -> Optional[str]:
    """Extract and validate client IP from FastAPI request (supports X-Forwarded-For)."""
    if request is None:
        return None
    xff = request.headers.get("X-Forwarded-For")
    ip_raw = xff.split(',')[0].strip() if xff else (request.client.host if request.client else None)
    if not ip_raw:
        return None
    try:
        ip_address(ip_raw)
        return ip_raw
    except ValueError:
        return None


async def _process_search_request(query: str, searchType: str, start: int, limit: int, page: int = 0, request: Optional[Request] = None) -> Dict[str, Any]:
    """
    Internal search processing with optimized database and HTTP handling.
    
    Optimizations:
    - Fast cache checks with timeouts to prevent blocking
    - HTTP connection reuse via client pool
    - Retry logic with exponential backoff and jitter
    - Background cache storage (fire-and-forget)
    - Comprehensive error handling and logging
    """
    request_start_time = time.time()
    cache_hit = False
    success = True
    
    try:
        logger.info(f"🔍 Processing search: query='{query}', type='{searchType}', start={start}, limit={limit}")
        
        # Determine location (country code) before cache check using GeoLite2
        client_ip = _get_client_ip_from_request(request)
        location = 'us'
        try:
            if client_ip and geoip_reader is not None:
                resp = geoip_reader.country(client_ip)
                if resp and resp.country and resp.country.iso_code:
                    location = resp.country.iso_code.lower()
        except Exception:
            pass
        
        # Log search query for first page only (start=0)
        if start == 0 or start == 1:
            async def log_search_query_bg(query, searchType, location, ip_address_value):
                try:
                    async with get_db_connection() as conn:
                        async with conn.cursor() as cursor:
                            await cursor.execute(
                                """
                                INSERT INTO search_queries (query, searchType, location, ip_address)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (query, searchType, location, ip_address_value)
                            )
                            await conn.commit()
                except Exception as e:
                    logger.warning(f"⚠️ Failed to log search query: {e}")

            try:
                asyncio.create_task(log_search_query_bg(query, searchType, location, client_ip))
            except Exception as e:
                logger.debug(f"⚠️ Failed to create background task for logging search query: {e}")

        popular_results = []
        promo = None
        
        # OPTIMIZED: Fast cache check with timeout to prevent blocking
        if connection_pool is not None and searchType != "general":
            try:
                # Use asyncio.wait_for for Python 3.10 compatibility
                async def check_cache():
                    async with get_db_connection() as conn:
                        async with conn.cursor(aiomysql.DictCursor) as cursor:
                            await cursor.execute("""
                                SELECT results 
                                FROM query_results 
                                WHERE query = %s AND searchType = %s AND location = %s
                                LIMIT 1
                            """, (query, searchType, location))
                            return await cursor.fetchone()
                
                promo = await asyncio.wait_for(check_cache(), timeout=settings.search_cache_timeout)
                logger.debug(f"💾 Database cache check completed in {time.time() - request_start_time:.2f}s")
                
            except asyncio.TimeoutError:
                logger.warning(f"⏰ Cache check timeout ({settings.search_cache_timeout}s) for query: {query}")
                promo = None
            except Exception as e:
                logger.warning(f"⚠️ Cache check failed: {e}")
                promo = None
        else:
            promo = None
            if searchType == "general":
                logger.debug(f"🔄 Skipping cache check for '{query}' - general search type")
        
        # Return cached result immediately if found
        if promo:
            cache_hit = True
            logger.info(f"💾 Cache HIT for query: {query}")
            results_list = json.loads(promo["results"])

            # Special handling for 'nws' searchType: check location_news table for recent results
            if searchType == "nws":
                location_news_result = None
                try:
                    if connection_pool is not None:
                        async def check_location_news():
                            async with get_db_connection() as conn:
                                async with conn.cursor(aiomysql.DictCursor) as cursor:
                                    await cursor.execute("""
                                        SELECT results, timestamp
                                        FROM location_news
                                        WHERE location = %s AND timestamp > NOW() - INTERVAL 12 HOUR
                                        LIMIT 1
                                    """, (location,))
                                    return await cursor.fetchone()
                        location_news_result = await asyncio.wait_for(check_location_news(), timeout=settings.search_cache_timeout)
                except Exception as e:
                    logger.warning(f"⚠️ Location news cache check failed: {e}")
                    location_news_result = None

                # Check if found and timestamp is within last 12 hours
                use_location_news = False
                if location_news_result and location_news_result.get("timestamp"):
                    try:
                        ts = location_news_result["timestamp"]
                        if isinstance(ts, str):
                            ts = datetime.fromisoformat(ts)
                        elif isinstance(ts, (int, float)):
                            ts = datetime.fromtimestamp(ts)
                        else:
                            ts = ts  # assume datetime
                        if (datetime.utcnow() - ts).total_seconds() < 12 * 3600:
                            use_location_news = True
                    except Exception as e:
                        logger.warning(f"⚠️ Error parsing timestamp from location_news: {e}")

                if use_location_news:
                    logger.info(f"💾 Location news cache HIT for location: {location}")
                    popular_results = json.loads(location_news_result["results"])
                else:
                    # Make an async call to get trending news
                    try:
                        sd_timeout = httpx.Timeout(
                            connect=settings.http_connect_timeout,
                            read=settings.http_read_timeout,
                            write=settings.http_write_timeout,
                            pool=settings.http_pool_timeout
                        )
                        trending_params = {
                            "api_key": settings.scrapingdog_api_key,
                            "query": "trending news",
                            "results": 3,
                            "country": location,
                            "advance_search": "true",
                        }
                        async with httpx.AsyncClient(timeout=sd_timeout, verify=True) as trending_client:
                            trending_response = await trending_client.get(settings.scrapingdog_url_news, params=trending_params)
                        trending_response.raise_for_status()
                        trending_data = trending_response.json()
                        trending_results = trending_data.get('news_results', [])
                        popular_results = trending_results

                        # Save to location_news table in background
                        async def save_location_news():
                            try:
                                if connection_pool is not None:
                                    async with get_db_connection() as conn:
                                        async with conn.cursor() as cursor:
                                            await cursor.execute("""
                                                INSERT INTO location_news (location, results, timestamp)
                                                VALUES (%s, %s, CURRENT_TIMESTAMP)
                                                ON DUPLICATE KEY UPDATE
                                                    results = VALUES(results),
                                                    timestamp = CURRENT_TIMESTAMP
                                            """, (location, json.dumps(trending_results)))
                                    logger.info(f"💾 Updated location_news cache for {location}")
                            except Exception as e:
                                logger.warning(f"⚠️ Background save of location_news failed: {e}")

                        # Start background save task
                        asyncio.create_task(save_location_news())

                    except Exception as e:
                        logger.warning(f"⚠️ Trending news API request failed: {e}")
                        # Fallback to old results if they exist
                        if location_news_result and location_news_result.get("results"):
                            popular_results = json.loads(location_news_result["results"])
                        else:
                            popular_results = []

            # Special handling for 'nws' searchType: check location_news table for recent results
            # if searchType == "nws":
            #     location_news_result = None
            #     try:
            #         if connection_pool is not None:
            #             async def check_location_news():
            #                 async with get_db_connection() as conn:
            #                     async with conn.cursor(aiomysql.DictCursor) as cursor:
            #                         await cursor.execute("""
            #                             SELECT results, timestamp
            #                             FROM location_news
            #                             WHERE location = %s AND timestamp > NOW() - INTERVAL 6 HOUR
            #                             LIMIT 1
            #                         """, (location,))
            #                         return await cursor.fetchone()
            #             location_news_result = await asyncio.wait_for(check_location_news(), timeout=settings.search_cache_timeout)
            #     except Exception as e:
            #         logger.warning(f"⚠️ Location news cache check failed: {e}")
            #         location_news_result = None

            #     # Check if found and timestamp is within last 6 hours
            #     use_location_news = False
            #     if location_news_result and location_news_result.get("timestamp"):
            #         try:
            #             ts = location_news_result["timestamp"]
            #             if isinstance(ts, str):
            #                 ts = datetime.fromisoformat(ts)
            #             elif isinstance(ts, (int, float)):
            #                 ts = datetime.fromtimestamp(ts)
            #             else:
            #                 ts = ts  # assume datetime
            #             if (datetime.utcnow() - ts).total_seconds() < 6 * 3600:
            #                 use_location_news = True
            #         except Exception as e:
            #             logger.warning(f"⚠️ Error parsing timestamp from location_news: {e}")

            #     if use_location_news:
            #         logger.info(f"💾 Location news cache HIT for location: {location}")
            #         results_list = json.loads(location_news_result["results"])
            #         popular_results = results_list
            #     else:
            #         # Call ScrapingDog API for Google News
            #         import requests
            #         api_key = "68aa5e4b6ab257fb0e4d4884"
            #         url = "https://api.scrapingdog.com/google_news"
            #         params = {
            #             "api_key": api_key,
            #             "query": "Trendings",
            #             "results": 3,
            #             "country": location,
            #             "language": "es",
            #             "advance_search": "false",
            #         }
            #         try:
            #             resp = requests.get(url, params=params, timeout=30)
            #             resp.raise_for_status()
            #             news_data = resp.json()
            #             # Save to location_news table
            #             if connection_pool is not None:
            #                 async def save_location_news():
            #                     async with get_db_connection() as conn:
            #                         async with conn.cursor() as cursor:
            #                             await cursor.execute("""
            #                                 INSERT INTO location_news (location, results, timestamp)
            #                                 VALUES (%s, %s, CURRENT_TIMESTAMP)
            #                                 ON DUPLICATE KEY UPDATE
            #                                     results = VALUES(results),
            #                                     timestamp = CURRENT_TIMESTAMP
            #                             """, (location, json.dumps(news_data)))
            #                 try:
            #                     await asyncio.wait_for(save_location_news(), timeout=5)
            #                     logger.info(f"💾 Saved new location_news for {location}")
            #                 except Exception as e:
            #                     logger.warning(f"⚠️ Failed to save location_news: {e}")
            #             popular_results = news_data if isinstance(news_data, list) else news_data.get("data", [])
            #         except Exception as e:
            #             logger.warning(f"⚠️ ScrapingDog Google News API failed: {e}")
            #             popular_results = []

                # # Efficient pagination
                # total_results = len(popular_results)
                # end_index = min(limit, total_results)
                # sliced_data = popular_results[start:end_index] if start < total_results else []

                # processing_time = time.time() - request_start_time

                # # Record metrics
                # await search_queue.record_request_metrics(processing_time, cache_hit=True, success=True)

                # return {
                #     "status_code": 200,
                #     "success": True,
                #     "message": "Data retrieved from cache (location_news)" if use_location_news else "Data retrieved from ScrapingDog Google News",
                #     "popular_results": popular_results,
                #     "data": sliced_data,
                #     "total": total_results,
                #     "cache_hit": True,
                #     "processing_time": round(processing_time, 3),
                #     "queued": False
                # }
            logger.info(f"💾 Cache HIT for query: {query}")
            results_list = json.loads(promo["results"])
            
            # Handle shop-specific popular results
            if searchType == 'shop' and len(results_list) > 0:
                sample_size = min(7, len(results_list))
                popular_results = random.sample(results_list, sample_size)
            
            # Efficient pagination
            total_results = len(results_list)
            end_index = min(limit, total_results)
            sliced_data = results_list[start:end_index] if start < total_results else []
            
            processing_time = time.time() - request_start_time
            
            # Record metrics
            await search_queue.record_request_metrics(processing_time, cache_hit=True, success=True)
            
            return {
                "status_code": 200,
                "success": True,
                "message": "Data retrieved from cache",
                "popular_results": popular_results,
                "data": sliced_data,
                "total": total_results,
                "cache_hit": True,
                "processing_time": round(processing_time, 3),
                "queued": False
            }
        
        # CACHE MISS: External API call with optimized HTTP client
        logger.info(f"🌐 Cache MISS for query: {query}, calling external API")
        
        # Build ScrapingDog request
        # Select ScrapingDog endpoint per search type
        if searchType == "general":
            url = settings.scrapingdog_url_general
            params = {
                "api_key": settings.scrapingdog_api_key,
                "query": query,
                "results": 100,
                "country": location,
                "language": "en",
                "advance_search": "true",
                "domain": "google.com",
                "page": page
            }
        elif searchType == "nws":
            url = settings.scrapingdog_url_news
            params = {
                "api_key": settings.scrapingdog_api_key,
                "query": query,
                "results": 100,
                "country": location,
                "advance_search": "true",
            }
        elif searchType == "isch":
            url = settings.scrapingdog_url_images
            params = {
                "api_key": settings.scrapingdog_api_key,
                "query": query,
                "results": 100,
                "country": location,
                "advance_search": "false",
            }
        elif searchType == "shop":
            url = settings.scrapingdog_url_shopping
            params = {
                "api_key": settings.scrapingdog_api_key,
                "query": query,
                "results": 100,
                "country": location,
                "advance_search": "false",
            }
        else:
            url = settings.scrapingdog_url
            params = {
                "api_key": settings.scrapingdog_api_key,
                "query": query
            }

        # Country already resolved above as 'location' and applied to params
        
        # Use optimized HTTP client pool
        try:
            client = await http_client_pool.get_client()
        except Exception as e:
            logger.error(f"❌ Failed to get HTTP client: {e}")
            success = False
            raise HTTPException(status_code=503, detail="HTTP client unavailable")
        
        # Retry with exponential backoff and jitter
        data = []
        external_api_start = time.time()
        
        for attempt in range(settings.search_retry_attempts):
            try:
                # Add jitter to prevent thundering herd effect
                if attempt > 0:
                    jitter = random.uniform(0, 0.5)
                    backoff = (0.5 * (2 ** attempt)) + jitter
                    logger.debug(f"🔄 Retry attempt {attempt + 1} after {backoff:.2f}s")
                    await asyncio.sleep(backoff)
                
                logger.debug(f"📡 Making API call to: {url} with params: {params}")
                sd_timeout = httpx.Timeout(
                    connect=settings.http_connect_timeout,
                    read=settings.http_read_timeout,
                    write=settings.http_write_timeout,
                    pool=settings.http_pool_timeout
                )
                async with httpx.AsyncClient(timeout=sd_timeout, verify=True) as sd_client:
                    response = await sd_client.get(url, params=params)
                response.raise_for_status()
                
                logger.info(f"✅ External API success on attempt {attempt + 1}")
                
                # Use ScrapingDog JSON as-is, no transformation
                try:
                    response_data = response.json()
                except Exception:
                    response_data = {}
                if searchType == "general":
                    data = response_data.get('organic_results', [])
                elif searchType == "nws":
                    data = response_data.get('news_results', [])
                    
                    # Make an additional call for trending news
                    try:
                        trending_params = {
                            "api_key": settings.scrapingdog_api_key,
                            "query": "trending news",
                            "results": 3,
                            "country": location,
                            "language": "es",
                            "advance_search": "true",
                        }
                        async with httpx.AsyncClient(timeout=sd_timeout, verify=True) as trending_client:
                            trending_response = await trending_client.get(settings.scrapingdog_url_news, params=trending_params)
                        trending_response.raise_for_status()
                        trending_data = trending_response.json()
                        trending_results = trending_data.get('news_results', [])
                        popular_results = trending_results

                        # Save to location_news table
                        if connection_pool is not None:
                            async def save_location_news():
                                async with get_db_connection() as conn:
                                    async with conn.cursor() as cursor:
                                        await cursor.execute("""
                                            INSERT INTO location_news (location, results, timestamp)
                                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                                            ON DUPLICATE KEY UPDATE
                                                results = VALUES(results),
                                                timestamp = CURRENT_TIMESTAMP
                                        """, (location, json.dumps(trending_results)))
                            try:
                                await asyncio.wait_for(save_location_news(), timeout=5)
                                logger.info(f"💾 Saved new location_news for {location}")
                            except Exception as e:
                                logger.warning(f"⚠️ Failed to save location_news: {e}")
                    except Exception as e:
                        logger.warning(f"⚠️ Trending news API request failed: {e}")
                        popular_results = []
                elif searchType == "isch":
                    data = response_data.get('images_results', [])
                elif searchType == "shop":
                    data = response_data.get('shopping_results', [])
                    # Create popular_results by randomly selecting up to 7 items from shopping_results
                    if data:
                        sample_size = min(7, len(data))
                        popular_results = random.sample(data, sample_size)
                
                break  # Success - exit retry loop
                
            except httpx.RequestError as e:
                logger.error(f"❌ Request error on attempt {attempt + 1}: {e}")
                if attempt == settings.search_retry_attempts - 1:
                    success = False
                    raise HTTPException(
                        status_code=503,
                        detail="External search API temporarily unavailable. Please try again later."
                    )
            
            except httpx.HTTPStatusError as e:
                preview = None
                try:
                    preview = e.response.text[:500]
                    logger.error(f"❌ HTTP error {e.response.status_code} on attempt {attempt + 1} - body: {preview}")
                except Exception:
                    logger.error(f"❌ HTTP error {e.response.status_code} on attempt {attempt + 1}")

                # No fallback; propagate error handling below
                if e.response.status_code == 429:  # Rate limited
                    await asyncio.sleep(5.0 * (attempt + 1))
                if attempt == settings.search_retry_attempts - 1:
                    success = False
                    raise HTTPException(
                        status_code=502,
                        detail=f"External search API error: {e.response.status_code}"
                    )
            
            except Exception as e:
                logger.error(f"❌ Unexpected error on attempt {attempt + 1}: {e}")
                if attempt == settings.search_retry_attempts - 1:
                    success = False
                    raise HTTPException(
                        status_code=500,
                        detail="Search processing failed due to unexpected error"
                    )
        
        external_api_time = time.time() - external_api_start
        logger.info(f"🌐 External API completed in {external_api_time:.2f}s")
        
        # NON-BLOCKING background cache storage (fire and forget)
        if data and connection_pool is not None and settings.search_enable_background_caching and searchType != "general":
            asyncio.create_task(_cache_search_results_async(query, searchType, data, location))
        elif data and connection_pool is None:
            logger.debug(f"🔄 Skipping cache storage for '{query}' - database not available")
        elif searchType == "general":
            logger.debug(f"🔄 Skipping cache storage for '{query}' - general search type")
        
        # Efficient response preparation
        total_results = len(data)
        end_index = min(limit, total_results)
        sliced_data = data[start:end_index] if start < total_results else []
        
        processing_time = time.time() - request_start_time
        
        # Record metrics
        await search_queue.record_request_metrics(processing_time, cache_hit=False, success=success)
        
        logger.info(f"🎉 Search completed: {total_results} total, {len(sliced_data)} returned in {processing_time:.2f}s")
        
        return {
            "status_code": 200,
            "success": True,
            "message": "Data retrieved from external API",
            "popular_results": popular_results,
            "data": sliced_data,
            "total": total_results,
            "cache_hit": False,
            "processing_time": round(processing_time, 3),
            "external_api_time": round(external_api_time, 3),
            "queued": False
        }

    except HTTPException:
        # Record failed metrics
        processing_time = time.time() - request_start_time
        await search_queue.record_request_metrics(processing_time, cache_hit=cache_hit, success=False)
        raise
    except Exception as e:
        # Record failed metrics
        processing_time = time.time() - request_start_time
        await search_queue.record_request_metrics(processing_time, cache_hit=cache_hit, success=False)
        logger.error(f"❌ Unexpected error in search processing: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def _parse_general_search_optimized(html_content: str) -> List[Dict[str, Any]]:
    """
    Optimized HTML parsing for general search results with better error handling.
    """
    data = []
    
    try:
        # Use lxml parser for better performance (falls back to html.parser if lxml not available)
        try:
            soup = BeautifulSoup(html_content, 'lxml')
        except:
            soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all search result containers
        results = soup.select(".tF2Cxc")
        logger.debug(f"🔍 Found {len(results)} potential search results")
        
        for i, result in enumerate(results):
            try:
                # Extract title with multiple fallbacks
                title_elem = result.select_one(".DKV0Md")
                if not title_elem:
                    title_elem = result.select_one("h3")
                title = title_elem.get_text(strip=True) if title_elem else None
                
                # Extract heading/subtitle
                heading_elem = result.select_one(".VuuXrf")
                heading = heading_elem.get_text(strip=True) if heading_elem else None
                
                # Extract image
                image_elem = result.select_one(".XNo5Ab")
                image = image_elem.get("src") if image_elem else None
                
                # Extract snippet/description with multiple selectors
                snippet_elem = result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb")
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else None
                
                # Extract link with multiple fallbacks
                link_elem = result.select_one(".yuRUbf a")
                if not link_elem:
                    link_elem = result.select_one("a[href]")
                link = link_elem.get("href") if link_elem else None
                
                # Only add results with at least a title
                if title:
                    data.append({
                        "title": title,
                        "image": image,
                        "description": snippet,
                        "heading": heading,
                        "links": link
                    })
                    logger.debug(f"✅ Parsed result {i+1}: {title[:50]}...")
                else:
                    logger.debug(f"⚠️ Skipping result {i+1}: no title found")
            
            except Exception as e:
                logger.warning(f"⚠️ Error parsing search result {i+1}: {e}")
                continue
    
    except Exception as e:
        logger.error(f"❌ Critical error parsing search results: {e}")
        raise
    
    logger.info(f"📊 Successfully parsed {len(data)} search results")
    return data

async def _cache_search_results_async(query: str, searchType: str, data: List[Dict[str, Any]], location: str):
    """
    Background task to cache search results without blocking the response.
    Uses timeout to prevent long-running cache operations.
    """
    # Early check to avoid unnecessary processing if database is unavailable
    if connection_pool is None:
        logger.debug(f"🔄 Skipping cache for '{query}' - database connection pool not initialized")
        return
    
    try:
        # Use asyncio.wait_for for Python 3.10 compatibility
        async def cache_data():
            async with get_db_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Serialize data efficiently
                    data_json = json.dumps(data, separators=(',', ':'))  # Compact JSON
                    
                    # Use INSERT ON DUPLICATE KEY UPDATE for efficiency (matching actual schema)
                    await cursor.execute("""
                        INSERT INTO query_results (query, searchType, location, results, timestamp) 
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE 
                        results = VALUES(results), 
                        timestamp = CURRENT_TIMESTAMP
                    """, (query, searchType, location, data_json))
        
        await asyncio.wait_for(cache_data(), timeout=settings.search_cache_insertion_timeout)
        logger.debug(f"💾 Successfully cached {len(data)} results for: {query} ({searchType})")
        
    except asyncio.TimeoutError:
        logger.warning(f"⏰ Cache storage timeout ({settings.search_cache_insertion_timeout}s) for: {query}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to cache search results for {query}: {e}")
        # Don't raise - caching failure shouldn't affect the user response

# =====================================================================
# END OPTIMIZED SEARCH API ENDPOINTS
# =====================================================================

STEALTH_INIT_SCRIPT = """
(() => {
  const defineGetter = (obj, prop, getter) => {
    try {
      const desc = Object.getOwnPropertyDescriptor(obj, prop);
      if (desc && desc.configurable === false) return;
      Object.defineProperty(obj, prop, { get: getter, configurable: true });
    } catch (_) {}
  };
  try {
    delete Object.getPrototypeOf(navigator).webdriver;
  } catch (_) {}
  defineGetter(navigator, 'webdriver', () => undefined);
  defineGetter(navigator, 'plugins', () => [1, 2, 3, 4, 5]);
  defineGetter(navigator, 'languages', () => ['en-US', 'en']);
  if (!window.chrome) window.chrome = { runtime: {} };
})();
"""

BOT_SENSITIVE_DOMAINS = [
    'bestbuy.com', 'amazon.com', 'walmart.com', 'target.com', 'ebay.com',
]

BOT_BLOCK_TEXT_MARKERS = (
    'something went wrong',
    'verify you are human',
    'access denied',
    'please verify you are a human',
    'robot check',
)

EBAY_WARMUP_URL = 'https://www.ebay.com/'


class BotBlockedPageError(Exception):
    """Raised when the target site returns a bot-block or error shell page."""


def _url_matches_domain(url: str, domains: List[str]) -> bool:
    return any(domain in url.lower() for domain in domains)


def _proxy_domains_list() -> List[str]:
    return [d.strip() for d in settings.screenshot_proxy_domains.split(',') if d.strip()]


def _parse_proxy_for_playwright(proxy_url: str) -> Dict[str, str]:
    parsed = urlparse(proxy_url)
    server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    cfg: Dict[str, str] = {"server": server}
    if parsed.username:
        cfg["username"] = parsed.username
    if parsed.password:
        cfg["password"] = parsed.password
    return cfg


async def is_bot_blocked_page(page) -> bool:
    try:
        title = (await page.title()).lower()
        if 'error page' in title:
            return True
        body = (await page.locator('body').inner_text(timeout=5000)).lower()
        return any(marker in body for marker in BOT_BLOCK_TEXT_MARKERS)
    except Exception as e:
        logger.debug(f"Bot-block check skipped: {e}")
        return False


async def setup_stealth_mode(page, url):
    """
    Configure stealth HTTP headers. Navigator overrides run once via STEALTH_INIT_SCRIPT
    on context creation (avoid duplicate page.evaluate that breaks on webdriver).
    """
    await page.set_extra_http_headers({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cache-Control': 'no-cache',
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
    })

async def take_screenshot(page, url, output_path, full_page, ss_width, ss_height):
    """
    Take a screenshot of a webpage and process it into slices.
    
    Args:
        page: Playwright page instance
        url: URL to screenshot
        output_path: Output path for the screenshot
        full_page: Whether to take full page screenshot
        ss_width: Screenshot width
        ss_height: Screenshot height
        
    Returns:
        Tuple of (links, image_slices)
    """
    logger.debug(f"Starting screenshot process for URL: {url}")
    
    # Sites with aggressive bot detection (eBay, major retailers, etc.)
    is_problematic_site = _url_matches_domain(url, BOT_SENSITIVE_DOMAINS)
    is_ebay = 'ebay.com' in url.lower()

    await setup_stealth_mode(page, url)

    if is_ebay:
        logger.info(f"eBay URL detected, warming up session before search page: {url}")
        try:
            await page.goto(EBAY_WARMUP_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"eBay homepage warmup failed (continuing): {e}")
    
    if is_problematic_site:
        logger.warning(f"🚨 PROBLEMATIC SITE DETECTED: {url} - Using aggressive timeouts")
        # Ultra-aggressive timeouts for problematic sites
        strategies = [
            {"wait_until": "commit", "timeout": 20000, "description": "Initial commit (20s)"},
            {"wait_until": "domcontentloaded", "timeout": 40000, "description": "DOM ready (40s)"},
            {"wait_until": "load", "timeout": 60000, "description": "Full load (60s)"}
        ]
    else:
        # Standard aggressive timeouts for normal sites
        strategies = [
            {"wait_until": "commit", "timeout": 20000, "description": "Initial commit (20s)"},
            {"wait_until": "domcontentloaded", "timeout": 40000, "description": "DOM ready (40s)"},
            {"wait_until": "load", "timeout": 60000, "description": "Full load (60s)"}
        ]
    
    # Universal navigation strategy that works for all websites
    navigation_successful = False
    last_error = None
    
    # Progressive fallback strategies - OPTIMIZED for speed during testing
    # strategies = [
    #     # {"wait_until": "commit", "timeout": 15000, "description": "Fast commit"},
    #     # {"wait_until": "domcontentloaded", "timeout": 25000, "description": "DOM ready"},
    #     {"wait_until": "load", "timeout": 45000, "description": "Full load"},
    #     {"wait_until": "networkidle", "timeout": 60000, "description": "Network idle"}
    # ]
    
    for i, strategy in enumerate(strategies):
        start_time = time.time()
        print("Taking screenshot for URL: ", url, " at ", start_time)
        try:
            logger.debug(f"Navigation attempt {i+1}/{len(strategies)}: {strategy['description']} (timeout: {strategy['timeout']}ms)")
            
            await page.goto(url, wait_until=strategy["wait_until"], timeout=strategy["timeout"])
            # await page.goto(url, wait_until=strategy["wait_until"])
            
            # Post-load wait (eBay and other bot-sensitive sites need more time)
            post_load_wait = 2.5 if is_ebay else (1.0 if is_problematic_site else 0.1)
            logger.debug(f"Allowing {post_load_wait}s for dynamic content to load")
            await asyncio.sleep(post_load_wait)
            
            # Try to wait for network idle as a bonus, but don't fail if it times out
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)  # Increased to 30s for large pages
                logger.debug("Network idle achieved")
            except Exception as e:
                logger.debug(f"Network idle timeout - continuing anyway: {e}")
                # Don't fail - network idle is optional
            
            navigation_successful = True
            logger.info(f"✅ Page loaded successfully using strategy: {strategy['description']} ({strategy['timeout']}ms)")
            break
            
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            logger.warning(f"❌ Navigation attempt {i+1} failed ({strategy['description']}): {e}")
            
            # Universal error recovery strategies
            if any(keyword in error_msg for keyword in ['http2_protocol_error', 'net::err_http2_protocol_error', 'protocol_error']):
                logger.debug("HTTP/2 protocol error detected - should be prevented by browser config")
                
            elif any(keyword in error_msg for keyword in ['timeout', 'net::err_timed_out']):
                logger.debug("Timeout detected - will try faster strategy next")
                
            elif any(keyword in error_msg for keyword in ['net::err_connection_refused', 'net::err_name_not_resolved']):
                logger.error(f"Network connectivity issue with {url}")
                break  # No point retrying for these errors
                
            # Brief pause before next attempt
            if i < len(strategies) - 1:
                await asyncio.sleep(0.5)
                continue
        print("Took successful screenshot for URL: ", url, " at ", time.time() - start_time)
    
    if not navigation_successful:
        
        logger.error(f"🚫 All navigation strategies failed for {url}. Last error: {last_error}")
        raise Exception(f"Failed to load page after {len(strategies)} attempts. Last error: {last_error}")
    
    if await is_bot_blocked_page(page):
        logger.error(f"🚫 Bot-block page detected for {url}")
        raise BotBlockedPageError(
            "Target site returned a bot-block or error page (e.g. eBay 'something went wrong'). "
            "Try a residential/unblocker proxy via PROXY_URL, or SCREENSHOT_PROXY_DOMAINS."
        )
    
    logger.debug("✅ Page navigation completed successfully")
    # Extract links from the page
    links = await extract_links(page)
    logger.debug(f"Extracted {len(links)} links from page")

    # Get page dimensions to determine screenshot strategy
    dimensions = await page.evaluate('''() => {
        return {
            width: document.documentElement.scrollWidth,
            height: document.documentElement.scrollHeight
        }
    }''')
    
    logger.debug(f"Page dimensions: {dimensions['width']}x{dimensions['height']}")

    # Handle large pages differently to avoid browser limitations
    if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
        logger.info("Using large screenshot strategy for oversized page")
        slices = await take_large_screenshot(page, dimensions, s3_client, ss_width, ss_height)
        logger.debug("Large screenshot processing completed")
    else:
        logger.debug("Taking standard full page screenshot")
        screenshot_bytes = await page.screenshot(
            full_page=True, 
            type='png', 
            timeout=settings.screenshot_timeout * 1000
        )
        
        logger.debug("Processing screenshot into slices")
        slices = await slice_and_stretch_image(screenshot_bytes, s3_client, ss_width, ss_height)
        logger.debug("Screenshot slicing completed")

    logger.info(f"Screenshot process completed with {len(slices)} slices generated")
    return links, slices

async def slice_and_stretch_image(image_path, s3_client, ss_width, ss_height):
    """
    Slice and upload image to S3 storage.
    Optimized for high-load scenarios with better error handling and logging.

    This implementation uploads slices concurrently using a thread pool and asyncio,
    which is much better for concurrency than sequential uploads. However, the actual
    concurrency is limited by the S3 client, network, and the max_workers setting.
    """
    try:
        nparr = np.frombuffer(image_path, np.uint8)
        # Decode image data to OpenCV format
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            logger.error("Failed to decode image data")
            return []

        logger.debug("Converted ByteImage to OpenCV Image format")

        height, width, _ = image.shape
        slice_width = ss_width
        slice_height = ss_height

        temp_image_paths = []
        slice_buffers = []
        slice_count = 0
        
        # Optimize PNG compression for high-load scenarios
        png_compression_params = [cv2.IMWRITE_PNG_COMPRESSION, 3]  # Reduced from 6 for maximum speed

        # Prepare all slices and buffers first
        for y in range(0, height, slice_height):
            for x in range(0, width, slice_width):
                try:
                    unique_id = uuid.uuid4().hex
                    end_x = min(x + slice_width, width)
                    end_y = min(y + slice_height, height)
                    temp_image_path = f'{unique_id}_{end_x}_{end_y}.png'
                    
                    # Crop the image slice
                    cropped_slice = image[y:end_y, x:end_x]

                    # Resize if necessary
                    if cropped_slice.shape[1] != slice_width:
                        cropped_slice = cv2.resize(
                            cropped_slice, 
                            (slice_width, cropped_slice.shape[0]), 
                            interpolation=cv2.INTER_LINEAR
                        )

                    # Encode image to PNG with optimized compression
                    is_success, buffer = cv2.imencode('.png', cropped_slice, png_compression_params)
                    
                    if is_success:
                        image_data = buffer.tobytes()
                        image_file_obj = io.BytesIO(image_data)
                        slice_buffers.append((image_file_obj, temp_image_path, slice_count))
                        slice_count += 1
                    else:
                        logger.warning(f"Failed to encode slice {slice_count} to PNG")
                        slice_count += 1
                        continue
                except Exception as e:
                    logger.error(f"Error processing slice at position ({x}, {y}): {e}")
                    slice_count += 1
                    continue

        # Define upload function for thread pool
        def upload_slice(image_file_obj, temp_image_path, slice_idx):
            try:
                logger.debug(f"Uploading slice {slice_idx + 1} to S3")
                print("Not Uploading slice")
                s3_client.upload_fileobj(
                    image_file_obj, 
                    settings.s3_bucket_name, 
                    f'Images/{os.path.basename(temp_image_path)}', 
                    ExtraArgs={
                        'ACL': 'public-read', 
                        'ContentType': 'image/png'
                    }
                )
                remote_path = f'Images/{os.path.basename(temp_image_path)}'
                return (True, remote_path)
            except (NoCredentialsError, PartialCredentialsError) as e:
                logger.error(f"S3 credentials error uploading slice {slice_idx}: {e}")
                return (False, None)
            except Exception as e:
                logger.error(f"Error uploading slice {slice_idx} to S3: {e}")
                return (False, None)

        # Upload slices concurrently using ThreadPoolExecutor and asyncio
        from concurrent.futures import ThreadPoolExecutor

        # 🚀 IMPROVED S3 CONCURRENCY: Higher parallel uploads
        max_workers = min(32, len(slice_buffers))  # Increased from 16 to 32 for better S3 concurrency
        if slice_buffers:
            logger.info(f"Uploading {len(slice_buffers)} slices to S3 concurrently (max_workers={max_workers})")
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                upload_futures = [
                    loop.run_in_executor(
                        executor, upload_slice, image_file_obj, temp_image_path, idx
                    )
                    for idx, (image_file_obj, temp_image_path, idx) in enumerate(slice_buffers)
                ]
                upload_results = await asyncio.gather(*upload_futures, return_exceptions=True)
                
                # Process results with better error handling
                successful_uploads = 0
                for idx, result in enumerate(upload_results):
                    if isinstance(result, Exception):
                        logger.error(f"Upload exception for slice {idx}: {result}")
                    elif result and len(result) == 2:
                        success, remote_path = result
                        if success and remote_path:
                            temp_image_paths.append(remote_path)
                            successful_uploads += 1
                        else:
                            logger.warning(f"Upload failed for slice {idx}")
                    else:
                        logger.warning(f"Invalid result format for slice {idx}: {result}")
                
                logger.info(f"S3 upload summary: {successful_uploads}/{len(slice_buffers)} slices uploaded successfully")

        logger.info(f"Successfully uploaded {len(temp_image_paths)} image slices to S3")
        return temp_image_paths
        
    except Exception as e:
        logger.error(f"Critical error in slice_and_stretch_image: {e}")
        return []


async def take_large_screenshot(page, dimensions, s3_client, ss_width, ss_height):
    """
    Take large screenshot by scrolling and capturing viewport sections.
    Optimized for high-load scenarios with better error handling and logging.
    """
    try:
        x = 0
        viewport_height = ss_height
        temp_image_paths = []

        # Get total scrollable height
        page_height = dimensions['height']
        logger.debug(f"Taking large screenshot: {page_height}px height, {viewport_height}px viewport")

        screenshot_count = 0
        for y in range(0, page_height, viewport_height):
            try:
                # Scroll to position
                await page.evaluate(f"window.scrollTo(0, {y})")
                
                # Wait a brief moment for content to load (optimized for high-load)
                await asyncio.sleep(0.1)  # Reduced from potentially longer waits
                
                unique_id = uuid.uuid4().hex
                temp_image_path = f'{unique_id}_{x}_{y}.png'
                
                # Take screenshot with timeout
                screenshot_bytes = await page.screenshot(
                    timeout=settings.screenshot_timeout * 1000
                )
                
                x = x + ss_width
                image_file_obj = io.BytesIO(screenshot_bytes)

                # Upload to S3
                try:
                    logger.debug(f"Uploading large screenshot section {screenshot_count + 1}")
                    print("Not Uploading large screenshot section")
                    s3_client.upload_fileobj(
                        image_file_obj, 
                        settings.s3_bucket_name, 
                        f'Images/{os.path.basename(temp_image_path)}', 
                        ExtraArgs={
                            'ACL': 'public-read', 
                            'ContentType': 'image/png'
                        }
                    )
                    
                    remote_path = f'Images/{os.path.basename(temp_image_path)}'
                    temp_image_paths.append(remote_path)
                    screenshot_count += 1
                    logger.debug(f"Successfully uploaded section: {remote_path}")
                    
                except (NoCredentialsError, PartialCredentialsError) as e:
                    logger.error(f"S3 credentials error uploading section {screenshot_count}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error uploading section {screenshot_count} to S3: {e}")
                    continue
                    
            except Exception as e:
                logger.error(f"Error capturing screenshot section at y={y}: {e}")
                continue

        logger.info(f"Successfully captured and uploaded {len(temp_image_paths)} large screenshot sections")
        return temp_image_paths
        
    except Exception as e:
        logger.error(f"Critical error in take_large_screenshot: {e}")
        return []




@app.post("/screenshot/", response_model=Dict[str, Any])
async def create_screenshot(request: ScreenshotRequest) -> Dict[str, Any]:
    """
    Create a screenshot of a webpage using optimized browser pool management.
    ✅ OPTIMIZED: Implements intelligent queuing, parallel browser creation, and comprehensive metrics.
    
    Args:
        request: ScreenshotRequest with URL and configuration
        
    Returns:
        Dictionary with screenshot results and metadata
        
    Raises:
        HTTPException: If screenshot operation fails or rate limit exceeded
    """
    
    start_time = time.time()
    
    # ✅ STEP 1: Try to acquire slot immediately (non-blocking)
    if await screenshot_queue.acquire_screenshot_slot():
        # Got slot immediately - process the request
        try:
            return await _process_screenshot_request(request, start_time, False)
        finally:
            screenshot_queue.release_screenshot_slot()
    
    # ✅ STEP 2: No immediate slot available - check if queuing is enabled
    if not settings.screenshot_enable_queuing:
        # Queuing disabled - reject with 429
        with screenshot_queue.stats_lock:
            screenshot_queue.stats['queue_rejections'] += 1
        
        logger.warning(f"📷 Screenshot capacity reached, queuing disabled for URL: {request.url}")
        raise HTTPException(
            status_code=429,
            detail=f"Server at capacity. Max concurrent screenshots: {settings.screenshot_max_concurrent}. Queuing disabled. Please retry later."
        )
    
    # ✅ STEP 3: Try to queue the request (with timeout)
    if await screenshot_queue.acquire_screenshot_slot_with_wait(settings.screenshot_queue_timeout):
        # Got slot after waiting - process the request
        try:
            return await _process_screenshot_request(request, start_time, True)
        finally:
            screenshot_queue.release_screenshot_slot()
    else:
        # Timeout while waiting in queue
        with screenshot_queue.stats_lock:
            screenshot_queue.stats['timeout_errors'] += 1
        
        logger.warning(f"📷 Screenshot queue timeout after {settings.screenshot_queue_timeout}s for URL: {request.url}")
        raise HTTPException(
            status_code=408,
            detail=f"Request timeout. Queue wait time exceeded {settings.screenshot_queue_timeout} seconds. Please retry later."
        )

async def _process_screenshot_request(request: ScreenshotRequest, start_time: float, was_queued: bool) -> Dict[str, Any]:
    """
    Process the actual screenshot request with optimized browser management.
    ✅ OPTIMIZED: Includes caching, retry logic, URL-level locking, and comprehensive error handling.
    """
    
    page = None
    cache_hit = False
    browser_created = False
    browser_info = {'browser_id': 0}  # Initialize with default values
    
    try:
        # ✅ STEP 1: Check cache first (DISABLED FOR TESTING - want to see raw performance)
        respond = await check_existing_entry(str(request.url))
        if respond is not None:
            cache_hit = True
            processing_time = time.time() - start_time
            logger.info(f"📷 Screenshot cache HIT for URL: {request.url} (returned in {processing_time:.2f}s)")
            
            # Record cache hit metrics
            await screenshot_queue.record_request_metrics(processing_time, cache_hit, True, browser_created)
            
            return {
                "status_code": 200,
                "message": "Screenshot retrieved from cache",
                "base_path": settings.base_path,
                "slices": json.loads(respond['slices']),
                "processing_time": processing_time,
                "browser_id": 0,  # Cache hit
                "queue_position": screenshot_queue.active_requests,
                "cache_hit": True,
                "was_queued": was_queued
            }
        
        # Cache disabled for testing - always create new screenshot
        cache_hit = False
        logger.info(f"📷 Creating new screenshot for URL: {request.url} (cache and DB checks disabled for testing)")
        
        # ✅ STEP 2: Get a page from the optimized browser pool with retry logic
        url_str = str(request.url)
        use_proxy = False
        max_browser_retries = 3
        for browser_attempt in range(max_browser_retries):
            try:
                page, browser_info = await browser_pool.get_page(
                    ss_width=request.ss_width,
                    ss_height=request.ss_height,
                    use_proxy=use_proxy,
                )
                break  # Successfully got page
            except Exception as e:
                logger.warning(f"⚠️ Browser pool attempt {browser_attempt + 1}/{max_browser_retries} failed: {e}")
                if browser_attempt == max_browser_retries - 1:
                    logger.error(f"❌ Failed to get browser page after {max_browser_retries} attempts")
                    raise HTTPException(
                        status_code=503,
                        detail=f"Service temporarily unavailable. Browser pool exhausted. Please retry later."
                    )
                await asyncio.sleep(0.5)  # Brief pause before retry
        
        # Check if this was a newly created browser
        browser_created = browser_info.get('browser_id', 0) > len(browser_pool.browsers) - 2
        
        logger.debug(f"📄 Using browser #{browser_info['browser_id']} for screenshot (created: {browser_created})")
        
        output_path = request.output_base_path + "screenshot.png"
        
        # ✅ STEP 3: Take the screenshot with optimized timeout and retry logic
        links, slices = None, None
        last_error = None
        
        for attempt in range(settings.screenshot_retry_attempts + 1):
            try:
                # Use reduced timeout for faster processing
                page.set_default_timeout(settings.screenshot_timeout * 1000)
                
                # GLOBAL REQUEST TIMEOUT: Based on single request timing
                global_timeout = 90  # 90 seconds max for entire request (57s + buffer)
                links, slices = await asyncio.wait_for(
                    take_screenshot(
                        page, 
                        str(request.url), 
                        output_path, 
                        request.full_page, 
                        request.ss_width, 
                        request.ss_height
                    ),
                    timeout=global_timeout
                )
                break  # Success - exit retry loop
                
            except asyncio.TimeoutError:
                last_error = f"Global timeout after {global_timeout}s"
                logger.error(f"🚫 GLOBAL TIMEOUT: Request exceeded {global_timeout}s for URL: {request.url}")
                if attempt == settings.screenshot_retry_attempts:
                    raise HTTPException(
                        status_code=408,
                        detail=f"Request timeout. Processing exceeded {global_timeout} seconds. Site may be too slow."
                    )
                    
            except BotBlockedPageError as e:
                last_error = str(e)
                logger.error(f"📷 Bot-blocked page for URL: {request.url}")
                if not use_proxy and settings.proxy_url and _url_matches_domain(url_str, _proxy_domains_list()):
                    logger.info("📷 Retrying screenshot with proxy after bot-block")
                    await browser_pool.release_page(page)
                    page, browser_info = await browser_pool.get_page(
                        ss_width=request.ss_width,
                        ss_height=request.ss_height,
                        use_proxy=True,
                    )
                    use_proxy = True
                    links, slices = await asyncio.wait_for(
                        take_screenshot(
                            page,
                            url_str,
                            output_path,
                            request.full_page,
                            request.ss_width,
                            request.ss_height,
                        ),
                        timeout=global_timeout,
                    )
                    break
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Site blocked automated browser access. "
                        "For eBay, configure a residential/unblocker PROXY_URL "
                        "(SERP-only proxies often fail)."
                    ),
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(f"📷 Screenshot attempt {attempt + 1} failed: {e}")
                if attempt == settings.screenshot_retry_attempts:
                    # Final attempt failed
                    raise HTTPException(
                        status_code=500,
                        detail=f"Screenshot processing failed: {str(e)[:100]}"
                    )
                await asyncio.sleep(0.5)  # Brief pause before retry
        
        # ✅ STEP 4: Store results in database (background task for better performance)
        if slices:
            asyncio.create_task(store_slices_in_db(str(request.url), output_path, slices, links))
        
        processing_time = time.time() - start_time
        
        # ✅ STEP 5: Record metrics and return success
        await screenshot_queue.record_request_metrics(processing_time, cache_hit, True, browser_created)
        
        return {
            "status_code": 200,
            "message": "Screenshot created successfully",
            "base_path": settings.base_path,
            "slices": slices,
            "processing_time": processing_time,
            "browser_id": browser_info.get('browser_id', 0),
            "queue_position": screenshot_queue.active_requests,
            "cache_hit": cache_hit,
            "was_queued": was_queued
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # ✅ STEP 6: Comprehensive error handling and cleanup
        logger.error(f"❌ Unexpected error in screenshot processing for URL {request.url}: {e}")
        
        # Record failure metrics
        processing_time = time.time() - start_time
        await screenshot_queue.record_request_metrics(processing_time, cache_hit, False, browser_created)
        
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)[:100]}"
        )
    finally:
        # ✅ STEP 7: Always cleanup resources
        if page:
            try:
                await browser_pool.release_page(page)
                logger.debug(f"📄 Released page from browser #{browser_info.get('browser_id', 0)}")
            except Exception as e:
                logger.warning(f"⚠️ Error releasing page: {e}")

@app.get("/browser-pool-status", response_model=Dict[str, Any])
async def get_browser_pool_status() -> Dict[str, Any]:
    """
    Get current status of the browser pool for monitoring.
    
    Returns:
        Dictionary with browser pool status and statistics
    """
    try:
        status = await browser_pool.get_pool_status()
        logger.debug("Browser pool status requested")
        
        return {
            "status_code": 200,
            "message": "Browser pool status retrieved successfully",
            **status
        }
        
    except Exception as e:
        logger.error(f"Error getting browser pool status: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve browser pool status"
        )

@app.get("/metrics", response_model=Dict[str, Any])
async def get_performance_metrics() -> Dict[str, Any]:
    """
    Get detailed performance metrics for monitoring high-load scenarios.
    
    Returns:
        Dictionary with comprehensive performance statistics
    """
    try:
        performance_stats = metrics.get_stats()
        browser_pool_status = await browser_pool.get_pool_status()
        
        logger.debug("Performance metrics requested")
        
        return {
            "status_code": 200,
            "message": "Performance metrics retrieved successfully",
            "timestamp": datetime.utcnow().isoformat(),
            "system_performance": performance_stats,
            "browser_pool_status": browser_pool_status,
            "configuration": {
                "max_concurrent_screenshots": settings.screenshot_max_concurrent,
                "browser_pool_size": settings.browser_pool_size,
                "max_tabs_per_browser": settings.max_tabs_per_browser,
                "total_theoretical_capacity": settings.browser_pool_size * settings.max_tabs_per_browser,
                "screenshot_timeout": settings.screenshot_timeout
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve performance metrics"
        )

# =====================================================================
# SEARCH API MONITORING ENDPOINTS
# =====================================================================

@app.get("/search-status", response_model=Dict[str, Any])
async def get_search_status() -> Dict[str, Any]:
    """
    Get comprehensive search API performance metrics and status.
    
    This endpoint provides detailed information about:
    - Current queue status and utilization
    - Database pool statistics
    - HTTP client status
    - Performance metrics including response times and success rates
    - Cache hit rates and API call statistics
    
    Returns:
        Dictionary with comprehensive search API status and metrics
    """
    try:
        # Get search queue status
        queue_status = await search_queue.get_status()
        
        # Get database pool status
        db_stats = {
            "pool_size": settings.db_pool_size,
            "estimated_used": queue_status["active_requests"],
            "estimated_available": max(0, settings.db_pool_size - queue_status["active_requests"]),
            "utilization_percent": round((queue_status["active_requests"] / settings.db_pool_size) * 100, 2)
        }
        
        # Get HTTP client status
        http_status = {
            "client_initialized": http_client_pool.client is not None,
            "client_closed": http_client_pool._closed,
            "max_connections": settings.http_max_connections,
            "keepalive_connections": settings.http_max_keepalive,
            "connection_timeout": settings.http_connect_timeout,
            "read_timeout": settings.http_read_timeout
        }
        
        # Calculate performance summary
        total_requests = queue_status["statistics"]["total_requests"]
        successful_requests = queue_status["statistics"]["successful_requests"]
        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
        
        # Calculate capacity analysis
        processing_capacity = settings.search_max_concurrent
        queue_capacity = settings.search_queue_size if settings.search_enable_queuing else 0
        total_capacity = processing_capacity + queue_capacity
        
        return {
            "status_code": 200,
            "message": "Search API status retrieved successfully",
            "timestamp": datetime.utcnow().isoformat(),
            "search_queue_status": queue_status,
            "database_pool_status": db_stats,
            "http_client_status": http_status,
            "performance_summary": {
                "success_rate_percent": round(success_rate, 2),
                "total_processed": total_requests,
                "currently_processing": queue_status["active_requests"],
                "queue_enabled": queue_status["queue_enabled"],
                "cache_hit_rate": queue_status["performance_metrics"]["cache_hit_rate_percent"],
                "avg_response_time": queue_status["performance_metrics"]["avg_response_time"],
                "api_success_rate": queue_status["performance_metrics"]["api_success_rate_percent"]
            },
            "capacity_analysis": {
                "processing_slots_available": processing_capacity - queue_status["active_requests"],
                "processing_utilization_percent": queue_status["utilization_percent"],
                "total_system_capacity": total_capacity,
                "theoretical_max_throughput": f"{processing_capacity * 2} requests/minute"  # Estimate
            },
            "configuration": {
                "max_concurrent_searches": settings.search_max_concurrent,
                "queue_enabled": settings.search_enable_queuing,
                "queue_size": settings.search_queue_size,
                "queue_timeout": settings.search_queue_timeout,
                "cache_timeout": settings.search_cache_timeout,
                "retry_attempts": settings.search_retry_attempts,
                "background_caching": settings.search_enable_background_caching
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting search status: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve search status"
        )

@app.get("/search-health", response_model=Dict[str, Any])
async def search_health_check() -> Dict[str, Any]:
    """
    Quick health check for search API components.
    
    This endpoint performs rapid health checks on all critical components:
    - Database connectivity test
    - HTTP client availability test  
    - External API connectivity test
    - Search queue functionality test
    
    Returns:
        Dictionary with health status of all search API components
    """
    health_status = {
        "search_queue": "unknown",
        "database": "unknown", 
        "http_client": "unknown",
        "external_api": "unknown"
    }
    
    overall_healthy = True
    
    # Test search queue functionality
    try:
        await search_queue.get_status()
        health_status["search_queue"] = "healthy"
    except Exception as e:
        health_status["search_queue"] = f"unhealthy: {str(e)[:100]}"
        overall_healthy = False
    
    # Test database connection
    try:
        async def test_db():
            async with get_db_connection() as conn:
                await conn.ping()
        
        await asyncio.wait_for(test_db(), timeout=5.0)
        health_status["database"] = "healthy"
    except asyncio.TimeoutError:
        health_status["database"] = "unhealthy: connection timeout"
        overall_healthy = False
    except Exception as e:
        health_status["database"] = f"unhealthy: {str(e)[:100]}"
        overall_healthy = False
    
    # Test HTTP client
    try:
        client = await http_client_pool.get_client()
        if client and not http_client_pool._closed:
            health_status["http_client"] = "healthy"
        else:
            health_status["http_client"] = "degraded: client not available"
            overall_healthy = False
    except Exception as e:
        health_status["http_client"] = f"unhealthy: {str(e)[:100]}"
        overall_healthy = False
    
    # Test external API connectivity (quick check)
    try:
        async def test_external_api():
            client = await http_client_pool.get_client()
            # Test with a simple query
            test_url = "https://www.google.com/search?q=test&num=1"
            response = await client.get(test_url)
            return response.status_code
        
        status_code = await asyncio.wait_for(test_external_api(), timeout=10.0)
        if status_code == 200:
            health_status["external_api"] = "healthy"
        elif status_code == 429:
            health_status["external_api"] = "degraded: rate limited"
        else:
            health_status["external_api"] = f"degraded: HTTP {status_code}"
    except asyncio.TimeoutError:
        health_status["external_api"] = "degraded: timeout"
    except Exception as e:
        health_status["external_api"] = f"unhealthy: {str(e)[:100]}"
        overall_healthy = False
    
    # Get quick statistics
    try:
        queue_stats = await search_queue.get_status()
        current_load = {
            "active_requests": queue_stats["active_requests"],
            "utilization": queue_stats["utilization_percent"],
            "available_slots": queue_stats["available_slots"]
        }
    except:
        current_load = {"error": "Unable to get load statistics"}
    
    return {
        "status_code": 200 if overall_healthy else 503,
        "overall_status": "healthy" if overall_healthy else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "components": health_status,
        "current_load": current_load,
        "uptime_check": "search API is responding",
        "health_summary": {
            "critical_issues": sum(1 for status in health_status.values() if "unhealthy" in status),
            "warnings": sum(1 for status in health_status.values() if "degraded" in status),
            "healthy_components": sum(1 for status in health_status.values() if status == "healthy"),
            "total_components": len(health_status)
        }
    }

@app.get("/search-metrics-detailed", response_model=Dict[str, Any])
async def get_detailed_search_metrics() -> Dict[str, Any]:
    """
    Get detailed search API metrics for performance analysis and monitoring.
    
    This endpoint provides in-depth metrics including:
    - Request timing percentiles
    - Error rate breakdowns
    - Cache performance analysis
    - Queue performance statistics
    - Resource utilization trends
    
    Returns:
        Dictionary with detailed search API performance metrics
    """
    try:
        # Get comprehensive queue status
        queue_status = await search_queue.get_status()
        
        # Get browser pool status for comparison
        browser_status = await browser_pool.get_pool_status()
        
        # Calculate advanced metrics
        stats = queue_status["statistics"]
        total_requests = stats["total_requests"]
        
        # Calculate error rates
        timeout_rate = (stats["timeout_requests"] / total_requests * 100) if total_requests > 0 else 0
        rejection_rate = (stats["rejected_requests"] / total_requests * 100) if total_requests > 0 else 0
        api_error_rate = (stats["external_api_errors"] / stats["external_api_calls"] * 100) if stats["external_api_calls"] > 0 else 0
        
        # Calculate throughput metrics
        queue_efficiency = (stats["successful_requests"] / (stats["successful_requests"] + stats["queued_requests"]) * 100) if (stats["successful_requests"] + stats["queued_requests"]) > 0 else 0
        
        return {
            "status_code": 200,
            "message": "Detailed search metrics retrieved successfully", 
            "timestamp": datetime.utcnow().isoformat(),
            "request_metrics": {
                "total_requests": total_requests,
                "successful_requests": stats["successful_requests"],
                "queued_requests": stats["queued_requests"],
                "timeout_requests": stats["timeout_requests"],
                "rejected_requests": stats["rejected_requests"],
                "queue_efficiency_percent": round(queue_efficiency, 2)
            },
            "error_analysis": {
                "timeout_rate_percent": round(timeout_rate, 2),
                "rejection_rate_percent": round(rejection_rate, 2),
                "api_error_rate_percent": round(api_error_rate, 2),
                "total_external_api_calls": stats["external_api_calls"],
                "external_api_errors": stats["external_api_errors"]
            },
            "performance_metrics": queue_status["performance_metrics"],
            "cache_analysis": {
                "cache_hits": stats["cache_hits"],
                "cache_misses": stats["cache_misses"],
                "cache_hit_rate_percent": queue_status["performance_metrics"]["cache_hit_rate_percent"],
                "cache_effectiveness": "high" if queue_status["performance_metrics"]["cache_hit_rate_percent"] > 50 else "low"
            },
            "resource_utilization": {
                "search_queue": {
                    "current_utilization": queue_status["utilization_percent"],
                    "active_requests": queue_status["active_requests"],
                    "max_concurrent": queue_status["max_concurrent"]
                },
                "database_pool": {
                    "estimated_utilization": round((queue_status["active_requests"] / settings.db_pool_size) * 100, 2),
                    "pool_size": settings.db_pool_size
                },
                "browser_pool": {
                    "utilization": browser_status["request_utilization_percent"],
                    "active_screenshots": browser_status["active_screenshot_requests"],
                    "max_screenshots": browser_status["max_concurrent_screenshots"]
                }
            },
            "system_comparison": {
                "search_vs_screenshot_load": {
                    "search_utilization": queue_status["utilization_percent"],
                    "screenshot_utilization": browser_status["request_utilization_percent"],
                    "search_active": queue_status["active_requests"],
                    "screenshot_active": browser_status["active_screenshot_requests"]
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting detailed search metrics: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve detailed search metrics"
        )

# =====================================================================
# END SEARCH API MONITORING ENDPOINTS
# =====================================================================




async def extract_links(page):

    return await page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a'))
            .filter(a => a.innerText.trim().length > 0)
            .map(a => ({
                href: a.href,
                text: a.innerText.trim()
            }));
    }''')




async def store_slices_in_db(url: str, output_path: str, slices: List[str], links: List[Dict[str, str]]):
    """
    Store screenshot slices and extracted links in database.
    
    Args:
        url: The URL that was screenshotted
        output_path: Path where screenshot was saved
        slices: List of slice file paths
        links: List of extracted links
        
    Note:
        If database is not available, this function will log a warning and return gracefully
    """
    if connection_pool is None:
        logger.warning(f"Database not available, skipping storage of screenshot data for URL: {url}")
        return
    
    connection = None
    try:
        async with get_db_connection() as conn:
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = "INSERT INTO screenshots (url, output_path, slices, links) VALUES (%s, %s, %s, %s)"
                await cursor.execute(sql, (url, output_path, json.dumps(slices), json.dumps(links)))
                
                logger.debug(f"Stored screenshot data for URL: {url}")
                logger.debug(f"Generated {len(slices)} slices and {len(links)} links")
                
            await conn.commit()
            logger.info(f"Successfully stored screenshot data in database for URL: {url}")
            
    except Exception as e:
        logger.error(f"Error storing screenshot data in database: {e}")
        # Don't raise exception - this is not critical to the main functionality
        
    finally:
        if connection:
            pass # No explicit close needed here, async with handles it

async def check_existing_entry(url: str) -> Optional[Dict[str, Any]]:
    """
    Check if a screenshot already exists for the given URL.
    
    Args:
        url: URL to check for existing screenshot
        
    Returns:
        Dictionary with existing screenshot data or None if not found
        
    Note:
        If database is not available, returns None (no cached entry found)
    """
    if connection_pool is None:
        logger.debug(f"Database not available, skipping cache check for URL: {url}")
        return None
    
    connection = None
    try:
        async with get_db_connection() as conn:
            logger.debug(f"Checking for existing screenshot entry for URL: {url}")
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = "SELECT slices, links FROM screenshots WHERE url=%s"
                await cursor.execute(sql, (url,))
                result = await cursor.fetchone()
                
                if result:
                    print("Found existing screenshot entry for URL: ", url)
                    logger.info(f"Found existing screenshot entry for URL: {url}")
                    return {
                        "status_code": 200,
                        "message": "Cached screenshot found",
                        "base_path": settings.base_path,
                        "slices": result['slices'],
                        "links": result['links']
                    }
                    
                logger.debug(f"No existing screenshot found for URL: {url}")
                print("No existing screenshot found for URL: ", url)
                return None
                
    except Exception as e:
        logger.error(f"Error checking existing screenshot entry: {e}")
        return None  # Return None instead of raising exception
        
    finally:
        if connection:
            pass # No explicit close needed here, async with handles it

async def get_links_from_db(url: str) -> Optional[List[Dict[str, str]]]:
    """
    Retrieve links from database for a given URL.
    
    Args:
        url: URL to get links for
        
    Returns:
        List of links or None if not found
        
    Note:
        If database is not available, returns None (no links found)
    """
    if connection_pool is None:
        logger.debug(f"Database not available, cannot retrieve links for URL: {url}")
        return None
    
    connection = None
    try:
        async with get_db_connection() as conn:
            logger.debug(f"Retrieving links for URL: {url}")
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = "SELECT links FROM screenshots WHERE url=%s"
                await cursor.execute(sql, (url,))
                result = await cursor.fetchone()
                
                if result:
                    logger.debug("Links found in database, parsing JSON")
                    links = json.loads(result['links'])
                    logger.info(f"Successfully retrieved {len(links)} links for URL")
                    return links
                    
                logger.info("No links found in database for URL")
                return None
                
    except Exception as e:
        logger.error(f"Error retrieving links from database: {e}")
        return None  # Return None instead of raising exception
        
    finally:
        if connection:
            pass # No explicit close needed here, async with handles it

@app.post("/links/", response_model=Dict[str, Any])
async def get_links(request: LinkRequest) -> Dict[str, Any]:
    """
    Get links for a specific URL from database.
    
    Args:
        request: LinkRequest with URL
        
    Returns:
        Dictionary with status and links
        
    Raises:
        HTTPException: If operation fails
    """
    try:
        logger.info(f"Links request for URL: {request.url}")
        links = await get_links_from_db(str(request.url))
        
        return {
            "status_code": 200, 
            "message": "Successfully retrieved the links", 
            "links": links or []
        }
        
    except Exception as e:
        logger.error(f"Error in get_links endpoint: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Failed to retrieve links"
        )



browser = None

# =====================================================================
# SCREENSHOT API MONITORING ENDPOINTS  
# =====================================================================

@app.get("/screenshot-status", response_model=Dict[str, Any])
async def get_screenshot_status() -> Dict[str, Any]:
    """
    Get current status of the screenshot API queue and processing.
    ✅ NEW: Comprehensive screenshot API monitoring endpoint.
    
    Returns:
        Dictionary with screenshot queue status and statistics
    """
    try:
        screenshot_status = await screenshot_queue.get_status()
        browser_status = await browser_pool.get_pool_status()
        
        logger.debug("📷 Screenshot API status requested")
        
        return {
            "status_code": 200,
            "message": "Screenshot API status retrieved successfully",
            "timestamp": datetime.utcnow().isoformat(),
            "screenshot_queue": screenshot_status,
            "browser_pool": browser_status,
            "configuration": {
                "max_concurrent_screenshots": settings.screenshot_max_concurrent,
                "queue_enabled": settings.screenshot_enable_queuing,
                "queue_size_limit": settings.screenshot_queue_size,
                "queue_timeout_seconds": settings.screenshot_queue_timeout,
                "retry_attempts": settings.screenshot_retry_attempts,
                "screenshot_timeout_seconds": settings.screenshot_timeout,
                "browser_pool_size": settings.browser_pool_size,
                "max_tabs_per_browser": settings.max_tabs_per_browser,
                "concurrent_browser_creation": settings.browser_launch_concurrent
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting screenshot API status: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve screenshot API status"
        )

@app.get("/screenshot-health", response_model=Dict[str, Any])
async def get_screenshot_health() -> Dict[str, Any]:
    """
    Health check endpoint for screenshot API with detailed diagnostics.
    ✅ NEW: Comprehensive health check for screenshot operations.
    
    Returns:
        Dictionary with health status and diagnostics
    """
    try:
        health_status = {
            "service": "healthy",
            "browser_pool": "unknown",
            "queue": "unknown",
            "issues": []
        }
        
        # Check browser pool health
        try:
            browser_status = await browser_pool.get_pool_status()
            if browser_status["total_browsers"] > 0:
                health_status["browser_pool"] = "healthy"
            else:
                health_status["browser_pool"] = "degraded"
                health_status["issues"].append("No active browsers in pool")
        except Exception as e:
            health_status["browser_pool"] = "unhealthy"
            health_status["issues"].append(f"Browser pool error: {str(e)}")
        
        # Check screenshot queue health
        try:
            queue_status = await screenshot_queue.get_status()
            utilization = queue_status.get("queue_utilization_percent", 0)
            if utilization < 90:
                health_status["queue"] = "healthy"
            elif utilization < 100:
                health_status["queue"] = "degraded"
                health_status["issues"].append(f"High queue utilization: {utilization}%")
            else:
                health_status["queue"] = "critical"
                health_status["issues"].append("Queue at full capacity")
        except Exception as e:
            health_status["queue"] = "unhealthy"
            health_status["issues"].append(f"Queue health check error: {str(e)}")
        
        # Determine overall health
        if health_status["browser_pool"] == "unhealthy" or health_status["queue"] == "unhealthy":
            health_status["service"] = "unhealthy"
        elif health_status["browser_pool"] == "degraded" or health_status["queue"] == "degraded":
            health_status["service"] = "degraded"
        elif health_status["browser_pool"] == "critical" or health_status["queue"] == "critical":
            health_status["service"] = "critical"
        
        status_code = 200
        if health_status["service"] == "degraded":
            status_code = 200  # Still functional
        elif health_status["service"] in ["critical", "unhealthy"]:
            status_code = 503  # Service unavailable
        
        return {
            "status_code": status_code,
            "message": f"Screenshot API health: {health_status['service']}",
            "timestamp": datetime.utcnow().isoformat(),
            "health": health_status
        }
        
    except Exception as e:
        logger.error(f"❌ Error during screenshot health check: {e}")
        return {
            "status_code": 503,
            "message": "Screenshot API health check failed",
            "timestamp": datetime.utcnow().isoformat(),
            "health": {
                "service": "unhealthy",
                "browser_pool": "unknown",
                "queue": "unknown",
                "issues": [f"Health check system error: {str(e)}"]
            }
        }

@app.get("/screenshot-metrics-detailed", response_model=Dict[str, Any])
async def get_screenshot_metrics_detailed() -> Dict[str, Any]:
    """
    Get detailed screenshot API performance metrics and analytics.
    ✅ NEW: Comprehensive metrics for screenshot API optimization monitoring.
    
    Returns:
        Dictionary with detailed performance analytics
    """
    try:
        screenshot_status = await screenshot_queue.get_status()
        browser_status = await browser_pool.get_pool_status()
        performance_stats = metrics.get_stats()
        
        # Calculate additional analytics
        total_requests = screenshot_status.get("total_requests", 0)
        successful_requests = screenshot_status.get("successful_requests", 0)
        failed_requests = screenshot_status.get("failed_requests", 0)
        
        # Browser efficiency metrics
        browser_creation_count = screenshot_status.get("browser_creation_count", 0)
        browser_reuse_count = screenshot_status.get("browser_reuse_count", 0)
        total_browser_operations = browser_creation_count + browser_reuse_count
        
        browser_reuse_rate = (browser_reuse_count / total_browser_operations * 100) if total_browser_operations > 0 else 0
        
        # Queue efficiency metrics
        queue_rejections = screenshot_status.get("queue_rejections", 0)
        timeout_errors = screenshot_status.get("timeout_errors", 0)
        queue_rejection_rate = (queue_rejections / max(total_requests, 1) * 100)
        timeout_rate = (timeout_errors / max(total_requests, 1) * 100)
        
        return {
            "status_code": 200,
            "message": "Detailed screenshot metrics retrieved successfully",
            "timestamp": datetime.utcnow().isoformat(),
            "performance_summary": {
                "total_requests": total_requests,
                "successful_requests": successful_requests,
                "failed_requests": failed_requests,
                "success_rate_percent": screenshot_status.get("success_rate_percent", 0),
                "avg_response_time_seconds": screenshot_status.get("avg_response_time_seconds", 0),
                "recent_avg_response_time_seconds": screenshot_status.get("recent_avg_response_time_seconds", 0)
            },
            "queue_analytics": {
                "active_requests": screenshot_status.get("active_requests", 0),
                "max_concurrent": screenshot_status.get("max_concurrent", 0),
                "utilization_percent": screenshot_status.get("queue_utilization_percent", 0),
                "queue_rejections": queue_rejections,
                "timeout_errors": timeout_errors,
                "queue_rejection_rate_percent": round(queue_rejection_rate, 2),
                "timeout_rate_percent": round(timeout_rate, 2)
            },
            "browser_analytics": {
                "total_browsers": browser_status.get("total_browsers", 0),
                "max_browsers": browser_status.get("max_browsers", 0),
                "browser_utilization_percent": browser_status.get("browser_utilization_percent", 0),
                "total_active_tabs": browser_status.get("total_active_tabs", 0),
                "tab_utilization_percent": browser_status.get("tab_utilization_percent", 0),
                "browser_creation_count": browser_creation_count,
                "browser_reuse_count": browser_reuse_count,
                "browser_reuse_rate_percent": round(browser_reuse_rate, 2)
            },
            "cache_analytics": {
                "cache_hits": screenshot_status.get("cache_hits", 0),
                "cache_misses": screenshot_status.get("cache_misses", 0),
                "cache_hit_rate_percent": screenshot_status.get("cache_hit_rate_percent", 0)
            },
            "configuration": {
                "optimized_settings": {
                    "max_concurrent": settings.screenshot_max_concurrent,
                    "queue_enabled": settings.screenshot_enable_queuing,
                    "queue_timeout": settings.screenshot_queue_timeout,
                    "screenshot_timeout": settings.screenshot_timeout,
                    "retry_attempts": settings.screenshot_retry_attempts,
                    "browser_pool_size": settings.browser_pool_size,
                    "max_tabs_per_browser": settings.max_tabs_per_browser,
                    "concurrent_browser_creation": settings.browser_launch_concurrent
                },
                "theoretical_capacity": {
                    "max_concurrent_screenshots": settings.screenshot_max_concurrent,
                    "max_browser_tabs": settings.browser_pool_size * settings.max_tabs_per_browser,
                    "estimated_throughput_per_minute": settings.screenshot_max_concurrent * (60 / max(screenshot_status.get("avg_response_time_seconds", 30), 1))
                }
            },
            "raw_data": {
                "screenshot_queue": screenshot_status,
                "browser_pool": browser_status,
                "system_performance": performance_stats
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting detailed screenshot metrics: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve detailed screenshot metrics"
        )

# =====================================================================
# END SCREENSHOT API MONITORING ENDPOINTS
# =====================================================================

from auth_routes import router as auth_router

app.include_router(auth_router)

