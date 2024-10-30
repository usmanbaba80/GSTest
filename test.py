# import asyncio
# import sys
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from playwright.sync_api import sync_playwright
# import os
# import time
# # import psutil
# import threading
# import json

# # Set WindowsProactorEventLoopPolicy if on Windows
# if sys.platform.startswith('win'):
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# class ScreenshotRequest(BaseModel):
#     url: str
#     output_base_path: str
#     browser_type: str
#     executable_path: str = None

# app = FastAPI()

# def take_full_page_screenshot(url, output_path, browser_type, executable_path=None):
#     with sync_playwright() as p:
#         # if browser_type == "chromium" and executable_path:
#         #     browser = p.chromium.launch(executable_path=executable_path, headless=True)
#         # elif browser_type == "firefox":
#         #     browser = p.firefox.launch(headless=True)
#         # elif browser_type == "webkit":
#         #     browser = p.webkit.launch(headless=True)
#         # else:
#         #     browser = p.chromium.launch(headless=True)
        
#         browser = p.webkit.launch(headless=True)
#         context = browser.new_context()
#         page = context.new_page()
#         page.goto(url, timeout=180000)

#         # Extract links
#         links = extract_links(page)
        
#         # Take a full-page screenshot
#         page.screenshot(path=output_path, full_page=True, timeout=180000)
#         print(f"Full-page screenshot saved at {output_path}")
#         browser.close()

# def monitor_resources(stop_event, log_file_path):
#     process = psutil.Process()
#     with open(log_file_path, 'a') as log_file:
#         while not stop_event.is_set():
#             cpu_usage = process.cpu_percent(interval=1)
#             memory_usage = process.memory_info().rss / (1024 * 1024)  # in MB
#             log_data = {
#                 "timestamp": time.time(),
#                 "cpu_usage": cpu_usage,
#                 "memory_usage": memory_usage
#             }
#             print(log_data)
#             # log_file.write(json.dumps(log_data) + "\n")
#             time.sleep(1)

# # start_time = time.time()
# #     take_full_page_screenshot(url, output_path, browser_type, executable_path)
# #     elapsed_time = time.time() - start_time
# @app.post("/screenshot/")
# def create_screenshot(request: ScreenshotRequest):
#     # log_file_path = "resource_usage.log"
#     # stop_event = threading.Event()
#     # monitor_thread = threading.Thread(target=monitor_resources, args=(stop_event, log_file_path))
#     # monitor_thread.start()
#     start_time = time.time()
#     try:
#         output_path = os.path.join(request.output_base_path, "screenshot.png")
#         take_full_page_screenshot(request.url, output_path, request.browser_type, request.executable_path)
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)
#         return {"message": "Screenshot taken successfully", "path": output_path}
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#     elapsed_time = time.time() - start_time
#     print(elapsed_time)

# def extract_links(page):
#     return page.evaluate('''() => {
#         return Array.from(document.querySelectorAll('a')).map(a => ({
#             href: a.href,
#             text: a.innerText
#         }));
#     }''')


import asyncio
import sys
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
import os
import time
import threading
import json

# Set WindowsProactorEventLoopPolicy if on Windows
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

class ScreenshotRequest(BaseModel):
    url: str
    output_base_path: str
    browser_type: str
    full_page: bool = False
    executable_path: str = None

app = FastAPI()

def take_screenshot(url, output_path, browser_type, full_page, executable_path=None):
    with sync_playwright() as p:
        if browser_type == "chromium" and executable_path:
            browser = p.chromium.launch(executable_path=executable_path, headless=True)
        elif browser_type == "firefox":
            browser = p.firefox.launch(headless=True)
        elif browser_type == "webkit":
            browser = p.webkit.launch(headless=True)
        else:
            browser = p.chromium.launch(headless=True)
        
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, timeout=180000)

        # Extract links
        links = extract_links(page)
        
        # Check page dimensions if full_page is requested
        if full_page:
            dimensions = page.evaluate('''() => {
                return {
                    width: document.documentElement.scrollWidth,
                    height: document.documentElement.scrollHeight
                }
            }''')
            if dimensions['width'] > 32767 or dimensions['height'] > 32767:
                full_page = False  # Disable full page if dimensions exceed limit

        # Take a screenshot
        page.screenshot(path=output_path, full_page=full_page, timeout=180000)
        print(f"Screenshot saved at {output_path}")
        browser.close()
        return links

def monitor_resources(stop_event, log_file_path):
    import psutil
    process = psutil.Process()
    with open(log_file_path, 'a') as log_file:
        while not stop_event.is_set():
            cpu_usage = process.cpu_percent(interval=1)
            memory_usage = process.memory_info().rss / (1024 * 1024)  # in MB
            log_data = {
                "timestamp": time.time(),
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage
            }
            print(log_data)
            log_file.write(json.dumps(log_data) + "\n")
            time.sleep(1)

@app.post("/screenshot/")
def create_screenshot(request: ScreenshotRequest):
    log_file_path = "resource_usage.log"
    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=monitor_resources, args=(stop_event, log_file_path))
    monitor_thread.start()
    
    start_time = time.time()
    try:
        output_path = os.path.join(request.output_base_path, "screenshot.png")
        links = take_screenshot(request.url, output_path, request.browser_type, request.full_page, request.executable_path)
        elapsed_time = time.time() - start_time
        print(elapsed_time)
        return {"message": "Screenshot taken successfully", "path": output_path, "links": links}
    except Exception as e:
        print(f"An error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        stop_event.set()
        monitor_thread.join()
        elapsed_time = time.time() - start_time
        print(elapsed_time)

def extract_links(page):
    return page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a')).map(a => ({
            href: a.href,
            text: a.innerText
        }));
    }''')




