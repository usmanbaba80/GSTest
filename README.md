# GS Backend API

A FastAPI backend service for web scraping, screenshot generation, and search functionality.

## Features

- **Search API**: Cached search results with support for different search types (general, news, images, shopping)
- **Screenshot Service**: Web page screenshot generation with automatic slicing and cloud storage using optimized browser pool management
- **Link Extraction**: Extract all links from web pages

- **Cloud Storage**: Automatic upload to Contabo S3-compatible storage

## Security Improvements

✅ **Credentials Management**: All sensitive credentials moved to environment variables  
✅ **Input Validation**: Comprehensive validation using Pydantic models  
✅ **Structured Logging**: Replace print statements with proper logging  
✅ **Error Handling**: Consistent error responses across all endpoints  

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Playwright Browsers

```bash
playwright install chromium
```

### 3. Environment Configuration

Create a `.env` file in the project root with the following variables:

```env
# Database Configuration
DB_HOST=your_database_host
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_DATABASE=your_database_name
DB_POOL_SIZE=32
DB_SSL_CA=DigiCertGlobalRootCA.crt 1.pem

# AWS/S3 Configuration (Contabo)
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
S3_ENDPOINT_URL=https://usc1.contabostorage.com
S3_BUCKET_NAME=gsdatasync

# Proxy Configuration
PROXY_URL=http://your_proxy_url

# Application Configuration
BASE_PATH=https://usc1.contabostorage.com/gsdatasync/
LOG_LEVEL=INFO

# Browser Configuration
BROWSER_POOL_SIZE=5
MAX_TABS_PER_BROWSER=10
SCREENSHOT_TIMEOUT=180
BROWSER_HEADLESS=true
```

### 4. Run the Application

```bash
uvicorn GS_main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

### Search API
```
GET /search
```
**Parameters:**
- `query` (string): Search query (1-500 characters)
- `searchType` (string): Type of search - general, nws, isch, shop
- `start` (int): Start index for pagination (0-1000)
- `limit` (int): Number of results (1-100)

### Screenshot API
```
POST /screenshot/
```
**Body:** ScreenshotRequest model with URL, dimensions, and options

### Links API
```
POST /links/
```
**Body:** LinkRequest model with URL to extract links from

### Browser Pool Status API
```
GET /browser-pool-status
```
Returns current status of browser pool including:
- Number of active browsers
- Tabs per browser
- Pool utilization statistics

## Browser Pool Management

The application uses an advanced browser pool management system that optimizes resource usage:

### Key Features
- **Tab Reuse**: Opens new tabs instead of new browsers for each screenshot
- **Automatic Scaling**: Creates new browsers when tab limits are exceeded
- **Resource Monitoring**: Tracks active tabs and browser instances
- **Graceful Cleanup**: Properly releases resources after use

### Configuration
- `BROWSER_POOL_SIZE`: Maximum number of browser instances (default: 5)
- `MAX_TABS_PER_BROWSER`: Maximum tabs per browser before creating new instance (default: 10)
- `BROWSER_HEADLESS`: Run browsers in headless mode (default: true)

### Benefits
- **Memory Efficiency**: Reuses browser instances instead of creating new ones
- **Faster Processing**: Tab creation is faster than browser creation
- **Better Resource Management**: Automatic cleanup and monitoring
- **Scalability**: Handles concurrent requests efficiently

### High-Load Configuration (1500+ Concurrent Requests)

For handling 1500+ concurrent screenshot requests, additional configuration and system requirements apply:

**System Requirements:**
- CPU: 16+ cores
- RAM: 64GB+ (128GB recommended)
- Storage: SSD with 500GB+ free space
- Network: 1Gbps+ bandwidth

**High-Load Environment Variables:**
```env
BROWSER_POOL_SIZE=50
MAX_TABS_PER_BROWSER=30
MAX_CONCURRENT_SCREENSHOTS=500
SCREENSHOT_TIMEOUT=30
PAGE_NAVIGATION_TIMEOUT=15
DB_POOL_SIZE=100
LOG_LEVEL=WARNING
```

**Performance Expectations:**
- Total Capacity: 1,500 concurrent tabs (50 browsers × 30 tabs)
- Rate Limiting: 500 concurrent processing requests
- Memory Usage: ~100GB total system memory needed
- Throughput: 500-1000 screenshots per minute

For detailed high-load setup instructions, hardware requirements, scaling strategies, and performance tuning, see `high-load-config.md`.

## Project Structure

```
├── GS_main.py          # Main FastAPI application
├── config.py           # Configuration management
├── models.py           # Pydantic models with validation
├── logger.py           # Logging configuration
├── requirements.txt    # Python dependencies
├── .env               # Environment variables (create this)
└── README.md          # This file
```

## Security Best Practices

1. **Never commit `.env` files** - Add `.env` to your `.gitignore`
2. **Rotate credentials regularly** - Update API keys and database passwords periodically
3. **Use HTTPS in production** - Configure SSL/TLS for all endpoints
4. **Monitor logs** - Set up log aggregation and monitoring
5. **Rate limiting** - Consider adding rate limiting for public endpoints

## Logging

The application uses structured logging with configurable levels:
- `DEBUG`: Detailed information for debugging
- `INFO`: General operational messages
- `WARNING`: Important notices that don't stop operation
- `ERROR`: Error conditions that need attention

Set `LOG_LEVEL` in your `.env` file to control verbosity.

## Error Handling

All endpoints return consistent error responses:
```json
{
  "status_code": 500,
  "success": false,
  "message": "Error description",
  "detail": "Detailed error information"
}
```

## Development Notes

- Database connections use connection pooling for better performance
- Browser pool management optimizes resource usage with tab reuse and automatic scaling
- API calls include retry logic with exponential backoff
- All user inputs are validated to prevent injection attacks
- Screenshots are automatically sliced and uploaded to cloud storage
- Search results are cached in the database to improve response times
- Browser instances are shared across requests for improved efficiency

## Support

For issues or questions, check the application logs first. The structured logging provides detailed information about request processing and error conditions. 