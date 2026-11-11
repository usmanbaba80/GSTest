# High-Load Configuration for 1500 Concurrent Screenshot Requests

## 🚀 **System Requirements**

### **Minimum Hardware Specifications:**
- **CPU**: 16+ cores (Intel Xeon / AMD EPYC recommended)
- **RAM**: 64GB+ (128GB recommended)
- **Storage**: SSD with 500GB+ free space
- **Network**: 1Gbps+ bandwidth
- **OS**: Linux (Ubuntu 20.04+ recommended) or Windows Server

### **Recommended Cloud Instance Types:**
- **AWS**: c5.4xlarge or c5.9xlarge
- **Azure**: Standard_F16s_v2 or Standard_F32s_v2
- **GCP**: c2-standard-16 or c2-standard-30

## ⚙️ **Optimal Configuration**

### **Environment Variables (`.env`):**

```env
# Database Configuration (Increased pool size)
DB_HOST=your_database_host
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_DATABASE=your_database_name
DB_POOL_SIZE=32              # Increased from 32
DB_SSL_CA=DigiCertGlobalRootCA.crt 1.pem

# AWS/S3 Configuration
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
S3_ENDPOINT_URL=https://usc1.contabostorage.com
S3_BUCKET_NAME=gsdatasync

# Proxy Configuration
PROXY_URL=http://your_proxy_url

# Application Configuration
BASE_PATH=https://usc1.contabostorage.com/gsdatasync/
LOG_LEVEL=WARNING              # Reduced logging for performance

# High-Load Browser Configuration
BROWSER_POOL_SIZE=50           # Increased from 5
MAX_TABS_PER_BROWSER=30        # Increased from 10
SCREENSHOT_TIMEOUT=30          # Reduced timeout
BROWSER_HEADLESS=true
MAX_CONCURRENT_SCREENSHOTS=500 # Rate limiting
BROWSER_LAUNCH_TIMEOUT=30
PAGE_NAVIGATION_TIMEOUT=15
```

## 📊 **Configuration Analysis**

### **Browser Pool Calculation:**
- **Total Capacity**: 50 browsers × 30 tabs = **1,500 concurrent tabs**
- **Rate Limiting**: 500 concurrent processing to prevent resource exhaustion
- **Queue Management**: Remaining 1,000 requests will receive HTTP 429 (retry)

### **Memory Usage Estimation:**
- **Per Browser**: ~200MB RAM
- **Per Tab**: ~50MB RAM
- **Total Browser Memory**: 50 × 200MB = **10GB**
- **Total Tab Memory**: 1,500 × 50MB = **75GB**
- **System Overhead**: ~15GB
- **Total Memory Need**: **~100GB**

## 🏗️ **Deployment Architecture**

### **Option 1: Single Server (High-End)**
```yaml
Server Configuration:
  CPU: 32 cores
  RAM: 128GB
  Storage: 1TB SSD
  Network: 10Gbps
  
Estimated Capacity: 1,500 concurrent requests
Cost: $500-800/month (cloud)
```

### **Option 2: Load Balanced (Recommended)**
```yaml
Configuration:
  Load Balancer: 1 instance
  Application Servers: 3 instances (16 cores, 64GB each)
  Database: Separate instance (8 cores, 32GB)
  Redis Cache: 1 instance (4 cores, 16GB)

Per App Server:
  BROWSER_POOL_SIZE=17
  MAX_CONCURRENT_SCREENSHOTS=167
  
Total Capacity: 3 × 500 = 1,500 concurrent requests
Cost: $800-1200/month (cloud)
```

## 🔧 **System Optimizations**

### **1. Operating System Tuning**

```bash
# Increase file descriptor limits
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf

# Optimize network settings
echo "net.core.somaxconn = 65536" >> /etc/sysctl.conf
echo "net.ipv4.tcp_max_syn_backlog = 65536" >> /etc/sysctl.conf
echo "net.core.netdev_max_backlog = 65536" >> /etc/sysctl.conf

# Apply changes
sysctl -p
```

### **2. Application Server Configuration**

```bash
# Run with optimized settings
uvicorn GS_main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --max-requests 10000 \
  --max-requests-jitter 1000 \
  --preload
```

### **3. Database Optimizations**

```sql
-- MySQL Configuration (my.cnf)
[mysqld]
max_connections = 500
innodb_buffer_pool_size = 16G
innodb_log_file_size = 2G
innodb_flush_log_at_trx_commit = 2
query_cache_size = 256M
```

## 📈 **Performance Monitoring**

### **Key Metrics to Monitor:**

1. **Browser Pool Status:**
   ```bash
   curl http://localhost:8000/browser-pool-status
   ```

2. **System Resources:**
   ```bash
   # CPU Usage
   htop
   
   # Memory Usage
   free -h
   
   # Browser Processes
   ps aux | grep chromium | wc -l
   ```

3. **Database Performance:**
   ```sql
   SHOW PROCESSLIST;
   SHOW STATUS LIKE 'Threads_connected';
   ```

## ⚡ **Performance Expectations**

### **Expected Throughput:**
- **Cold Start**: 50-100 requests/minute (browsers launching)
- **Warm State**: 500-800 requests/minute
- **Peak Performance**: 1,000+ requests/minute

### **Response Times:**
- **Cache Hit**: 50-100ms
- **Simple Page**: 2-5 seconds
- **Complex Page**: 5-15 seconds
- **High-Load Average**: 8-12 seconds

## 🚨 **Failure Scenarios & Mitigation**

### **1. Memory Exhaustion**
```yaml
Symptoms: High swap usage, slow response times
Solution: 
  - Reduce MAX_TABS_PER_BROWSER to 20
  - Reduce BROWSER_POOL_SIZE to 40
  - Add memory alerts
```

### **2. Database Connection Pool Exhaustion**
```yaml
Symptoms: Database connection errors
Solution:
  - Increase DB_POOL_SIZE to 150
  - Add connection pooling monitoring
  - Implement connection retry logic
```

### **3. Rate Limit Overload**
```yaml
Symptoms: Many HTTP 429 responses
Solution:
  - Increase MAX_CONCURRENT_SCREENSHOTS gradually
  - Implement exponential backoff in clients
  - Add request queuing system
```

## 🔄 **Scaling Strategy**

### **Horizontal Scaling (Recommended):**

```yaml
Phase 1 (500 requests): 1 server, current config
Phase 2 (1000 requests): 2 servers, load balanced
Phase 3 (1500 requests): 3 servers, load balanced
Phase 4 (2000+ requests): 4+ servers + Redis queue
```

### **Auto-Scaling Rules:**

```yaml
Scale Up Triggers:
  - CPU > 70% for 5 minutes
  - Memory > 80% for 3 minutes
  - Request queue > 100 for 2 minutes

Scale Down Triggers:
  - CPU < 30% for 10 minutes
  - Memory < 50% for 10 minutes
  - Request queue < 10 for 15 minutes
```

## 📋 **Testing & Validation**

### **Load Testing Script:**

```python
import asyncio
import aiohttp
import time

async def test_screenshot(session, url):
    payload = {
        "url": url,
        "ux_type": 1,
        "ss_width": 1920,
        "ss_height": 1080
    }
    
    start = time.time()
    async with session.post('http://localhost:8000/screenshot/', json=payload) as response:
        result = await response.json()
        duration = time.time() - start
        return response.status, duration

async def load_test():
    urls = [f"https://example.com/page{i}" for i in range(1500)]
    
    async with aiohttp.ClientSession() as session:
        tasks = [test_screenshot(session, url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success_count = sum(1 for r in results if isinstance(r, tuple) and r[0] == 200)
    print(f"Success Rate: {success_count/1500*100:.2f}%")

# Run test
asyncio.run(load_test())
```

## 🎯 **Success Criteria**

### **Performance Targets:**
- **Success Rate**: >95% (>1,425 successful screenshots)
- **Average Response Time**: <10 seconds
- **Memory Usage**: <90% of available RAM
- **CPU Usage**: <80% average
- **Error Rate**: <5%

### **Monitoring Alerts:**
- Memory usage > 85%
- CPU usage > 85% for 5+ minutes
- Success rate < 90%
- Average response time > 15 seconds
- Browser pool utilization > 95%

---

**Note**: This configuration assumes a dedicated server for screenshot processing. For production use, consider implementing Redis-based queuing, auto-scaling, and distributed processing for even better performance and reliability. 