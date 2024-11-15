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


# import asyncio
# import sys
# from fastapi import FastAPI, HTTPException, Query
# from pydantic import BaseModel
# from playwright.sync_api import sync_playwright
# import os
# import time
# import threading
# import json
# from PIL import Image

# # Set WindowsProactorEventLoopPolicy if on Windows
# if sys.platform.startswith('win'):
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# class ScreenshotRequest(BaseModel):
#     url: str
#     output_base_path: str
#     browser_type: str
#     full_page: bool = True
#     executable_path: str = None

# app = FastAPI()

# def take_screenshot(url, output_path, browser_type, full_page, executable_path=None):
#     with sync_playwright() as p:
#         if browser_type == "chromium" and executable_path:
#             browser = p.chromium.launch(executable_path=executable_path, headless=True)
#         elif browser_type == "firefox":
#             browser = p.firefox.launch(headless=True)
#         elif browser_type == "webkit":
#             browser = p.webkit.launch(headless=True)
#         else:
#             browser = p.chromium.launch(headless=True)
        
#         context = browser.new_context()
#         page = context.new_page()
#         page.goto(url, timeout=180000)

#         # Extract links
#         links = extract_links(page)
#         # checkTime = time.time()
#         # # Check page dimensions if full_page is requested
#         # if full_page:
#         #     dimensions = page.evaluate('''() => {
#         #         return {
#         #             width: document.documentElement.scrollWidth,
#         #             height: document.documentElement.scrollHeight
#         #         }
#         #     }''')
#         #     if dimensions['width'] > 32767 or dimensions['height'] > 32767:
#         #         full_page = False  # Disable full page if dimensions exceed limit
#         # TotalCheckTime = time.time() - checkTime
#         # print("Check Time = ", TotalCheckTime)
#         # # Take a screenshot
#         # page.screenshot(path=output_path, full_page=full_page, timeout=180000)
#         # print(f"Screenshot saved at {output_path}")
#         # browser.close()
#         # return links

#         # Check page dimensions if full_page is requested
#         dimensions = page.evaluate('''() => {
#             return {
#                 width: document.documentElement.scrollWidth,
#                 height: document.documentElement.scrollHeight
#             }
#         }''')
    
#         if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
#             # Take multiple screenshots and stitch them together
#             output_path = take_large_screenshot(page, dimensions, output_path)
#         else:
#             # Take a single screenshot
#             page.screenshot(path=output_path, full_page=full_page, timeout=180000)
#             print(f"Screenshot saved at {output_path}")

#         browser.close()
#         return links

# def take_large_screenshot(page, dimensions, output_path):
#     scroll_width = dimensions['width']
#     scroll_height = dimensions['height']
#     viewport_width = page.viewport_size['width']
#     viewport_height = page.viewport_size['height']
#     stitch_image = Image.new('RGB', (scroll_width, scroll_height))
#     temp_image_paths = []

#     for y in range(0, scroll_height, viewport_height):
#         for x in range(0, scroll_width, viewport_width):
#             page.evaluate(f'window.scrollTo({x}, {y})')
#             temp_image_path = f'{output_path}_{x}_{y}.png'
#             page.screenshot(path=temp_image_path, clip={'x': x, 'y': y, 'width': viewport_width, 'height': viewport_height})
#             temp_image_paths.append(temp_image_path)

#     for temp_image_path in temp_image_paths:
#         temp_image = Image.open(temp_image_path)
#         x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
#         stitch_image.paste(temp_image, (x, y))
#         os.remove(temp_image_path)

#     stitch_image.save(output_path)
#     print(f"Large screenshot saved at {output_path}")
#     return output_path

# def monitor_resources(stop_event, log_file_path):
#     import psutil
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
#             log_file.write(json.dumps(log_data) + "\n")
#             time.sleep(1)

# @app.post("/screenshot/")
# def create_screenshot(request: ScreenshotRequest):
#     # log_file_path = "resource_usage.log"
#     # stop_event = threading.Event()
#     # monitor_thread = threading.Thread(target=monitor_resources, args=(stop_event, log_file_path))
#     # monitor_thread.start()
    
#     start_time = time.time()
#     try:
#         output_path = os.path.join(request.output_base_path, "screenshot.png")
#         links = take_screenshot(request.url, output_path, request.browser_type, request.full_page, request.executable_path)
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)
#         return {"message": "Screenshot taken successfully", "path": output_path, "links": links}
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         # stop_event.set()
#         # monitor_thread.join()
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)

# def extract_links(page):
#     return page.evaluate('''() => {
#         return Array.from(document.querySelectorAll('a')).map(a => ({
#             href: a.href,
#             text: a.innerText
#         }));
#     }''')



# import asyncio
# import sys
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from playwright.sync_api import sync_playwright
# import os
# import time
# from PIL import Image

# # Set WindowsProactorEventLoopPolicy if on Windows
# if sys.platform.startswith('win'):
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# class ScreenshotRequest(BaseModel):
#     url: str
#     output_base_path: str
#     browser_type: str
#     full_page: bool = True
#     executable_path: str = None

# app = FastAPI()

# def take_screenshot(url, output_path, browser_type, full_page, executable_path=None):
#     with sync_playwright() as p:
#         if browser_type == "chromium" and executable_path:
#             browser = p.chromium.launch(executable_path=executable_path, headless=True)
#         elif browser_type == "firefox":
#             browser = p.firefox.launch(headless=True)
#         elif browser_type == "webkit":
#             browser = p.webkit.launch(headless=True)
#         else:
#             browser = p.chromium.launch(headless=True)
        
#         context = browser.new_context()
#         page = context.new_page()
#         page.goto(url, timeout=180000)

#         # Wait for the page to load completely
#         page.wait_for_load_state('networkidle')

#         # Extract links
#         links = extract_links(page)
        
#         dimensions = page.evaluate('''() => {
#             return {
#                 width: document.documentElement.scrollWidth,
#                 height: document.documentElement.scrollHeight
#             }
#         }''')

#         if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
#             output_path = take_large_screenshot(page, dimensions, output_path)
#         else:
#             page.screenshot(path=output_path, full_page=full_page, timeout=180000)
#             print(f"Screenshot saved at {output_path}")

#         browser.close()
#         return links

# def take_large_screenshot(page, dimensions, output_path):
#     scroll_width = dimensions['width']
#     scroll_height = dimensions['height']
#     viewport_width = min(page.viewport_size['width'], 32767)
#     viewport_height = min(page.viewport_size['height'], 32767)
#     stitch_image = Image.new('RGB', (scroll_width, scroll_height))
#     temp_image_paths = []

#     for y in range(0, scroll_height, viewport_height):
#         for x in range(0, scroll_width, viewport_width):
#             page.evaluate(f'window.scrollTo({x}, {y})')
#             time.sleep(1)  # Increase delay to ensure the content has rendered
#             clip_width = min(viewport_width, scroll_width - x)
#             clip_height = min(viewport_height, scroll_height - y)
            
#             # Ensure clip area is within the viewport bounds
#             if clip_width <= 0 or clip_height <= 0:
#                 print(f"Skipping empty clip area at x: {x}, y: {y}, width: {clip_width}, height: {clip_height}")
#                 continue
            
#             temp_image_path = f'{output_path}_{x}_{y}.png'
#             try:
#                 page.screenshot(path=temp_image_path, clip={'x': x, 'y': y, 'width': clip_width, 'height': clip_height})
#                 temp_image_paths.append(temp_image_path)
#             except Exception as e:
#                 print(f"Failed to take screenshot at {x}, {y}: {e}")
    
#     for temp_image_path in temp_image_paths:
#         temp_image = Image.open(temp_image_path)
#         x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
#         stitch_image.paste(temp_image, (x, y))
#         os.remove(temp_image_path)

#     stitch_image.save(output_path)
#     print(f"Large screenshot saved at {output_path}")
#     return output_path

# @app.post("/screenshot/")
# def create_screenshot(request: ScreenshotRequest):
#     start_time = time.time()
#     try:
#         output_path = os.path.join(request.output_base_path, "screenshot.png")
#         links = take_screenshot(request.url, output_path, request.browser_type, request.full_page, request.executable_path)
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)
#         return {"message": "Screenshot taken successfully", "path": output_path, "links": links}
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)

# def extract_links(page):
#     return page.evaluate('''() => {
#         return Array.from(document.querySelectorAll('a')).map(a => ({
#             href: a.href,
#             text: a.innerText
#         }));
#     }''')

# import asyncio
# import sys
# from fastapi import FastAPI, HTTPException
# from fastapi.responses import FileResponse
# from pydantic import BaseModel
# from playwright.sync_api import sync_playwright
# import os
# import time
# import json
# from PIL import Image
# import pymysql

# # Set WindowsProactorEventLoopPolicy if on Windows
# if sys.platform.startswith('win'):
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# class ScreenshotRequest(BaseModel):
#     url: str
#     output_base_path: str
#     browser_type: str
#     full_page: bool = True
#     executable_path: str = None

# app = FastAPI()

# def take_screenshot(url, output_path, browser_type, full_page, executable_path=None):
#     with sync_playwright() as p:
#         if browser_type == "chromium" and executable_path:
#             browser = p.chromium.launch(executable_path=executable_path, headless=True)
#         elif browser_type == "firefox":
#             browser = p.firefox.launch(headless=True)
#         elif browser_type == "webkit":
#             browser = p.webkit.launch(headless=True)
#         else:
#             browser = p.chromium.launch(headless=True)
        
#         context = browser.new_context()
#         page = context.new_page()
#         page.goto(url, timeout=180000)

#         # Extract links
#         links = extract_links(page)
        
#         dimensions = page.evaluate('''() => {
#             return {
#                 width: document.documentElement.scrollWidth,
#                 height: document.documentElement.scrollHeight
#             }
#         }''')

#         if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
#             output_path = take_large_screenshot(page, dimensions, output_path)
#         else:
#             page.screenshot(path=output_path, full_page=full_page, timeout=180000)
#             print(f"Screenshot saved at {output_path[0]}")

#         browser.close()
#         return links, output_path[1] 

# def take_large_screenshot(page, dimensions, output_path):
#     scroll_width = dimensions['width']
#     scroll_height = dimensions['height']
#     viewport_width = min(page.viewport_size['width'], 32767)
#     viewport_height = min(page.viewport_size['height'], 32767)
#     stitch_image = Image.new('RGB', (scroll_width, scroll_height))
#     temp_image_paths = []

#     for y in range(0, scroll_height, viewport_height):
#         for x in range(0, scroll_width, viewport_width):
#             page.evaluate(f'window.scrollTo({x}, {y})')
#             clip_width = min(viewport_width, scroll_width - x)
#             clip_height = min(viewport_height, scroll_height - y)
#             temp_image_path = f'{output_path}_{x}_{y}.png'
#             page.screenshot(path=temp_image_path, clip={'x': 0, 'y': 0, 'width': clip_width, 'height': clip_height})
#             temp_image_paths.append(temp_image_path)

#     for temp_image_path in temp_image_paths:
#         temp_image = Image.open(temp_image_path)
#         x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
#         stitch_image.paste(temp_image, (x, y))

#     stitch_image.save(output_path)
#     print(f"Large screenshot saved at {output_path}")
#     return [output_path, temp_image_paths]

# @app.post("/screenshot/")
# def create_screenshot(request: ScreenshotRequest):
#     start_time = time.time()
#     try:
#         output_path = os.path.join(request.output_base_path, "screenshot.png")
#         links, slices = take_screenshot(request.url, output_path, request.browser_type, request.full_page, request.executable_path)
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)
        
#         # Store the slices in the database
#         store_slices_in_db(request.url, output_path, slices)
        
#         return {"message": "Screenshot taken successfully", "path": output_path, "slices": slices, "links": links}
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)

# def extract_links(page):
#     return page.evaluate('''() => {
#         return Array.from(document.querySelectorAll('a')).map(a => ({
#             href: a.href,
#             text: a.innerText
#         }));
#     }''')

# def store_slices_in_db(url, output_path, slices):
#     connection = pymysql.connect(
#         host='alldbserver.mysql.database.azure.com',
#         user='u.s',
#         password='&!ALvg4ty5g9s&N',
#         database='devtest',
#         ssl={
#             'ca': 'DigiCertGlobalRootCA.crt 1.pem'
#         }
#     )
#     try:
#         with connection.cursor() as cursor:
#             sql = "INSERT INTO screenshots (url, output_path, slices) VALUES (%s, %s, %s)"
#             cursor.execute(sql, (url, output_path, json.dumps(slices)))
#         connection.commit()
#     finally:
#         connection.close()

# @app.get("/slice/")
# def get_slice(path: str):
#     if not os.path.exists(path):
#         raise HTTPException(status_code=404, detail="Slice not found")
#     return FileResponse(path)

# ["c:/screenshots/screenshot.png_0_0.png", "c:/screenshots/screenshot.png_0_720.png", "c:/screenshots/screenshot.png_0_1440.png", "c:/screenshots/screenshot.png_0_2160.png", "c:/screenshots/screenshot.png_0_2880.png", "c:/screenshots/screenshot.png_0_3600.png", "c:/screenshots/screenshot.png_0_4320.png", "c:/screenshots/screenshot.png_0_5040.png", "c:/screenshots/screenshot.png_0_5760.png", "c:/screenshots/screenshot.png_0_6480.png", "c:/screenshots/screenshot.png_0_7200.png", "c:/screenshots/screenshot.png_0_7920.png", "c:/screenshots/screenshot.png_0_8640.png", "c:/screenshots/screenshot.png_0_9360.png", "c:/screenshots/screenshot.png_0_10080.png", "c:/screenshots/screenshot.png_0_10800.png", "c:/screenshots/screenshot.png_0_11520.png", "c:/screenshots/screenshot.png_0_12240.png", "c:/screenshots/screenshot.png_0_12960.png", "c:/screenshots/screenshot.png_0_13680.png", "c:/screenshots/screenshot.png_0_14400.png", "c:/screenshots/screenshot.png_0_15120.png", "c:/screenshots/screenshot.png_0_15840.png", "c:/screenshots/screenshot.png_0_16560.png", "c:/screenshots/screenshot.png_0_17280.png", "c:/screenshots/screenshot.png_0_18000.png", "c:/screenshots/screenshot.png_0_18720.png", "c:/screenshots/screenshot.png_0_19440.png", "c:/screenshots/screenshot.png_0_20160.png", "c:/screenshots/screenshot.png_0_20880.png", "c:/screenshots/screenshot.png_0_21600.png", "c:/screenshots/screenshot.png_0_22320.png", "c:/screenshots/screenshot.png_0_23040.png", "c:/screenshots/screenshot.png_0_23760.png", "c:/screenshots/screenshot.png_0_24480.png", "c:/screenshots/screenshot.png_0_25200.png", "c:/screenshots/screenshot.png_0_25920.png", "c:/screenshots/screenshot.png_0_26640.png", "c:/screenshots/screenshot.png_0_27360.png", "c:/screenshots/screenshot.png_0_28080.png", "c:/screenshots/screenshot.png_0_28800.png", "c:/screenshots/screenshot.png_0_29520.png", "c:/screenshots/screenshot.png_0_30240.png", "c:/screenshots/screenshot.png_0_30960.png", "c:/screenshots/screenshot.png_0_31680.png", "c:/screenshots/screenshot.png_0_32400.png", "c:/screenshots/screenshot.png_0_33120.png", "c:/screenshots/screenshot.png_0_33840.png", "c:/screenshots/screenshot.png_0_34560.png", "c:/screenshots/screenshot.png_0_35280.png", "c:/screenshots/screenshot.png_0_36000.png", "c:/screenshots/screenshot.png_0_36720.png", "c:/screenshots/screenshot.png_0_37440.png", "c:/screenshots/screenshot.png_0_38160.png", "c:/screenshots/screenshot.png_0_38880.png", "c:/screenshots/screenshot.png_0_39600.png", "c:/screenshots/screenshot.png_0_40320.png", "c:/screenshots/screenshot.png_0_41040.png", "c:/screenshots/screenshot.png_0_41760.png", "c:/screenshots/screenshot.png_0_42480.png", "c:/screenshots/screenshot.png_0_43200.png", "c:/screenshots/screenshot.png_0_43920.png", "c:/screenshots/screenshot.png_0_44640.png", "c:/screenshots/screenshot.png_0_45360.png", "c:/screenshots/screenshot.png_0_46080.png", "c:/screenshots/screenshot.png_0_46800.png", "c:/screenshots/screenshot.png_0_47520.png", "c:/screenshots/screenshot.png_0_48240.png", "c:/screenshots/screenshot.png_0_48960.png", "c:/screenshots/screenshot.png_0_49680.png", "c:/screenshots/screenshot.png_0_50400.png", "c:/screenshots/screenshot.png_0_51120.png", "c:/screenshots/screenshot.png_0_51840.png", "c:/screenshots/screenshot.png_0_52560.png", "c:/screenshots/screenshot.png_0_53280.png", "c:/screenshots/screenshot.png_0_54000.png", "c:/screenshots/screenshot.png_0_54720.png", "c:/screenshots/screenshot.png_0_55440.png", "c:/screenshots/screenshot.png_0_56160.png", "c:/screenshots/screenshot.png_0_56880.png", "c:/screenshots/screenshot.png_0_57600.png"]

##### last fine code
# import asyncio
# import sys
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from playwright.sync_api import sync_playwright
# import os
# import time
# import json
# from PIL import Image

# # Set WindowsProactorEventLoopPolicy if on Windows
# if sys.platform.startswith('win'):
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# class ScreenshotRequest(BaseModel):
#     url: str
#     output_base_path: str
#     browser_type: str
#     full_page: bool = True
#     executable_path: str = None

# app = FastAPI()

# def take_screenshot(url, output_path, browser_type, full_page, executable_path=None):
#     with sync_playwright() as p:
#         if browser_type == "chromium" and executable_path:
#             browser = p.chromium.launch(executable_path=executable_path, headless=True)
#         elif browser_type == "firefox":
#             browser = p.firefox.launch(headless=True)
#         elif browser_type == "webkit":
#             browser = p.webkit.launch(headless=True)
#         else:
#             browser = p.chromium.launch(headless=True)
        
#         context = browser.new_context()
#         page = context.new_page()
#         page.goto(url, timeout=180000)

#         # Extract links
#         links = extract_links(page)
        
#         dimensions = page.evaluate('''() => {
#             return {
#                 width: document.documentElement.scrollWidth,
#                 height: document.documentElement.scrollHeight
#             }
#         }''')

#         if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
#             output_path = take_large_screenshot(page, dimensions, output_path)
#         else:
#             page.screenshot(path=output_path, full_page=full_page, timeout=180000)
#             print(f"Screenshot saved at {output_path[0]}")

#         browser.close()
#         return links, output_path[1] 

# def take_large_screenshot(page, dimensions, output_path):
#     scroll_width = dimensions['width']
#     scroll_height = dimensions['height']
#     viewport_width = min(page.viewport_size['width'], 32767)
#     viewport_height = min(page.viewport_size['height'], 32767)
#     stitch_image = Image.new('RGB', (scroll_width, scroll_height))
#     temp_image_paths = []

#     for y in range(0, scroll_height, viewport_height):
#         for x in range(0, scroll_width, viewport_width):
#             page.evaluate(f'window.scrollTo({x}, {y})')
#             clip_width = min(viewport_width, scroll_width - x)
#             clip_height = min(viewport_height, scroll_height - y)
#             temp_image_path = f'{output_path}_{x}_{y}.png'
#             # time.sleep(1)
#             page.screenshot(path=temp_image_path, clip={'x': 0, 'y': 0, 'width': clip_width, 'height': clip_height})

#             temp_image_paths.append(temp_image_path)
#     # print(temp_image_paths)
#     for temp_image_path in temp_image_paths:
#         temp_image = Image.open(temp_image_path)
#         x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
#         stitch_image.paste(temp_image, (x, y))
#         # os.remove(temp_image_path)

        

#     stitch_image.save(output_path)
#     print(f"Large screenshot saved at {output_path}")
#     return [output_path, temp_image_paths]

# @app.post("/screenshot/")
# def create_screenshot(request: ScreenshotRequest):
#     start_time = time.time()
#     try:
#         output_path = os.path.join(request.output_base_path, "screenshot.png")
#         links, slices = take_screenshot(request.url, output_path, request.browser_type, request.full_page, request.executable_path)
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)
#         return {"message": "Screenshot taken successfully", "path": output_path, "slices": slices, "links": links}
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         elapsed_time = time.time() - start_time
#         print(elapsed_time)

# def extract_links(page):
#     return page.evaluate('''() => {
#         return Array.from(document.querySelectorAll('a')).map(a => ({
#             href: a.href,
#             text: a.innerText
#         }));
#     }''')

#####################working last final locally ############################

import asyncio
import sys
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
import os
import time
import json
from PIL import Image
import pymysql
import uuid

# Set WindowsProactorEventLoopPolicy if on Windows
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

class ScreenshotRequest(BaseModel):
    url: str
    output_base_path: str = 'c:/screenshots/'
    browser_type: str = 'chromium'
    full_page: bool = True
    executable_path: str = None

app = FastAPI()

def take_screenshot(url, output_path, browser_type, full_page, executable_path=None):
    with sync_playwright() as p:
        if browser_type == "chromium":
            browser = p.chromium.launch(headless=True)
        elif browser_type == "firefox":
            browser = p.firefox.launch(headless=True)
        elif browser_type == "webkit":
            browser = p.webkit.launch(headless=True)
        else:
            browser = p.chromium.launch(headless=True)
        
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.goto(url, timeout=180000)

        # Extract links
        links = extract_links(page)
        
        dimensions = page.evaluate('''() => {
            return {
                width: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight
            }
        }''')

        if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
            output_path = take_large_screenshot(page, dimensions, output_path)
        else:
            page.screenshot(path=output_path, full_page=full_page, timeout=180000)
            print(f"Screenshot saved at {output_path[0]}")

        browser.close()
        return links, output_path[1] 

def take_large_screenshot(page, dimensions, output_path):
    scroll_width = dimensions['width']
    scroll_height = dimensions['height']
    viewport_width = min(page.viewport_size['width'], 32767)
    viewport_height = min(page.viewport_size['height'], 32767)
    stitch_image = Image.new('RGB', (scroll_width, scroll_height))
    temp_image_paths = []

    for y in range(0, scroll_height, viewport_height):
        # print("hello1")
        for x in range(0, scroll_width, viewport_width):
            unique_id = uuid.uuid4().hex
            page.evaluate(f'window.scrollTo({x}, {y})')
            clip_width = min(viewport_width, scroll_width - x)
            clip_height = min(viewport_height, scroll_height - y)
            temp_image_path = f'{output_path}{unique_id}_{x}_{y}.png'
            page.screenshot(path=temp_image_path, clip={'x': 0, 'y': 0, 'width': clip_width, 'height': clip_height})
            temp_image_paths.append(temp_image_path)
        # print("hello12")
    for temp_image_path in temp_image_paths:
        temp_image = Image.open(temp_image_path)
        x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
        stitch_image.paste(temp_image, (x, y))
    # print("hello3")

    stitch_image.save(output_path)
    print(f"Large screenshot saved at {output_path}")
    return [output_path, temp_image_paths]

@app.post("/screenshot/")
def create_screenshot(request: ScreenshotRequest):
    start_time = time.time()
    try:
        # Check if the URL already exists in the database
        ExistingCheckTime = time.time()
        existing_entry = check_existing_entry(request.url)
        if existing_entry:
            return {
                "message": "Screenshot already exists",
                "path": existing_entry['output_path'],
                "slices": json.loads(existing_entry['slices'])
                # "links": existing_entry['links']
            }
        print("Existing Check Time: ", time.time() - ExistingCheckTime)
        output_path = os.path.join(request.output_base_path, "screenshot.png")
        links, slices = take_screenshot(request.url, output_path, request.browser_type, request.full_page, request.executable_path)
        elapsed_time = time.time() - start_time
        print("Try bLock Check time : ",elapsed_time)
        
        # Store the slices in the database
        store_slices_in_db(request.url, output_path, slices, links)
        
        return {"message": "Screenshot taken successfully", "path": output_path, "slices": slices}
        # , "links": links
    except Exception as e:
        print(f"An error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        elapsed_time = time.time() - start_time
        print("Finally bLock Check time : ",elapsed_time)

def extract_links(page):
    return page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a')).map(a => ({
            href: a.href,
            text: a.innerText
        }));
    }''')


def store_slices_in_db(url, output_path, slices, links):
    connection = pymysql.connect(
        host='alldbserver.mysql.database.azure.com',
        user='u.s',
        password='&!ALvg4ty5g9s&N',
        database='devtest',
        ssl={
            'ca': 'DigiCertGlobalRootCA.crt 1.pem'
        }
    )
    try:
        with connection.cursor() as cursor:
            sql = "INSERT INTO screenshots (url, output_path, slices, links) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (url, output_path, json.dumps(slices), json.dumps(links)))
        connection.commit()
    except pymysql.MySQLError as e:
        print(f"Error: {e}")
    finally:
        connection.close()


def check_existing_entry(url):
    connection = pymysql.connect(
        host='alldbserver.mysql.database.azure.com',
        user='u.s',
        password='&!ALvg4ty5g9s&N',
        database='devtest',
        ssl={
            'ca': 'DigiCertGlobalRootCA.crt 1.pem'
        }
    )
    try:
        with connection.cursor() as cursor:
            sql = "SELECT output_path, slices, links FROM screenshots WHERE url=%s"
            cursor.execute(sql, (url,))
            result = cursor.fetchone()
            if result:
                return {
                    "output_path": result[0],
                    "slices": result[1],
                    "links": result[2]
                }
            return None
    finally:
        connection.close()

def get_links_from_db(url):
    connection = pymysql.connect(
        host='alldbserver.mysql.database.azure.com',
        user='u.s',
        password='&!ALvg4ty5g9s&N',
        database='devtest',
        ssl={
            'ca': 'DigiCertGlobalRootCA.crt 1.pem'
        }
    )
    try:
        with connection.cursor() as cursor:
            sql = "SELECT links FROM screenshots WHERE url=%s"
            cursor.execute(sql, (url,))
            result = cursor.fetchone()
            if result:
                # Parse the JSON string back into a Python object
                links = json.loads(result[0])
                return {
                    "links": links
                }
            return None
    finally:
        connection.close()


@app.get("/slice/")
def get_slice(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Slice not found")
    return FileResponse(path)

@app.get("/links/")
def get_links(url: str):
    try: 
        
        return get_links_from_db(url)

    except Exception as e:
        print(f"An error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))













