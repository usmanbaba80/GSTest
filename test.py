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

##################### working last final locally ############################


# from fastapi import FastAPI, Query
# from pydantic import BaseModel
# import requests
# import time
# from typing import Optional
# from bs4 import BeautifulSoup

# app = FastAPI()

# # Proxy settings
# proxies = {
#     'http': 'http://brd-customer-hl_d9339b7c-zone-serp_api1:w3u1xgsxexj2@brd.superproxy.io:22225',
#     'https': 'http://brd-customer-hl_d9339b7c-zone-serp_api1:w3u1xgsxexj2@brd.superproxy.io:22225'
# }

# # Disable SSL verification warnings
# requests.packages.urllib3.disable_warnings()

# # Endpoint to take a query parameter and fetch results
# @app.get("/search/")
# def search(query: str = Query(..., description="Search query")):
#     # Construct the URL with the query parameter
#     url = f"https://www.google.com/search?q={query}"
    
#     # Measure execution time
#     start_time = time.time()
    
#     # Make the request
#     try:
#         response = requests.get(url, proxies=proxies, verify=False)
#         response.raise_for_status()  # Raise an error for bad status codes
#     except requests.RequestException as e:
#         return {"error": str(e)}
    
#     end_time = time.time()
#     execution_time = end_time - start_time
    
#     # return {
#     #     "execution_time": execution_time,
#     #     "response": response.text
#     # }
#     data = []
#     soup = BeautifulSoup(response.text, 'html.parser')
        
#     for result in soup.select(".tF2Cxc"):
#         title = result.select_one(".DKV0Md").text
#         heading = result.select_one(".VuuXrf").text if result.select_one(".VuuXrf") else None
#         image_element = result.select_one(".XNo5Ab")
#         image = image_element.get("src") if image_element else None
#         snippet = result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb").text if result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb") else None
#         links = result.select_one(".yuRUbf a")["href"] if result.select_one(".yuRUbf a") else None

#         data.append({
#             "title": title,
#             "image": image,
#             "description": snippet,
#             "heading": heading,
#             "links": links
#         })
#     return data




# import asyncio
# import sys
# from fastapi import FastAPI, HTTPException, Query
# from fastapi.responses import FileResponse
# from pydantic import BaseModel
# from playwright.sync_api import sync_playwright
# import os
# import time
# import requests
# import json
# from PIL import Image
# import pymysql
# import uuid
# from bs4 import BeautifulSoup

# # Set WindowsProactorEventLoopPolicy if on Windows
# if sys.platform.startswith('win'):
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# # Proxy settings
# proxies = {
#     'http': 'http://brd-customer-hl_d9339b7c-zone-serp_api1:w3u1xgsxexj2@brd.superproxy.io:22225',
#     'https': 'http://brd-customer-hl_d9339b7c-zone-serp_api1:w3u1xgsxexj2@brd.superproxy.io:22225'
# }

# # Disable SSL verification warnings
# requests.packages.urllib3.disable_warnings()

# class ScreenshotRequest(BaseModel):
#     url: str
#     output_base_path: str = 'c:/screenshots/'
#     browser_type: str = 'chromium'
#     full_page: bool = True
#     executable_path: str = None

# app = FastAPI()


# # Endpoint to take a query parameter and fetch results
# @app.get("/search/")
# def search(query: str = Query(..., description="Search query")):
#     # Construct the URL with the query parameter
#     url = f"https://www.google.com/search?q={query}"
    
#     # Measure execution time
#     start_time = time.time()
    
#     # Make the request
#     try:
#         response = requests.get(url, proxies=proxies, verify=False)
#         response.raise_for_status()  # Raise an error for bad status codes
#     except requests.RequestException as e:
#         return {"error": str(e)}
    
#     end_time = time.time()
#     execution_time = end_time - start_time
    
#     # return {
#     #     "execution_time": execution_time,
#     #     "response": response.text
#     # }
#     data = []
#     soup = BeautifulSoup(response.text, 'html.parser')
        
#     for result in soup.select(".tF2Cxc"):
#         title = result.select_one(".DKV0Md").text
#         heading = result.select_one(".VuuXrf").text if result.select_one(".VuuXrf") else None
#         image_element = result.select_one(".XNo5Ab")
#         image = image_element.get("src") if image_element else None
#         snippet = result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb").text if result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb") else None
#         links = result.select_one(".yuRUbf a")["href"] if result.select_one(".yuRUbf a") else None

#         data.append({
#             "title": title,
#             "image": image,
#             "description": snippet,
#             "heading": heading,
#             "links": links
#         })
#     return data

# def take_screenshot(url, output_path, browser_type, full_page, executable_path=None):
#     with sync_playwright() as p:
#         if browser_type == "chromium":
#             browser = p.chromium.launch(headless=True)
#         elif browser_type == "firefox":
#             browser = p.firefox.launch(headless=True)
#         elif browser_type == "webkit":
#             browser = p.webkit.launch(headless=True)
#         else:
#             browser = p.chromium.launch(headless=True)
        
#         context = browser.new_context(viewport={"width": 1920, "height": 1080})
#         page = context.new_page()
#         page.goto(url, timeout=300000)

#         # Remove overlays and pop-ups
#         page.evaluate('''() => {
#             const selectors = [
#                 'div[class*="overlay"]', 
#                 'div[class*="popup"]', 
#                 'div[class*="modal"]', 
#                 'div[id*="overlay"]', 
#                 'div[id*="popup"]', 
#                 'div[id*="modal"]'
#             ];
#             for (const selector of selectors) {
#                 const elements = document.querySelectorAll(selector);
#                 elements.forEach(el => el.style.display = 'none');
#             }
#         }''')

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
#         # print("hello1")
#         for x in range(0, scroll_width, viewport_width):
#             unique_id = uuid.uuid4().hex
#             page.evaluate(f'window.scrollTo({x}, {y})')
#             clip_width = min(viewport_width, scroll_width - x)
#             clip_height = min(viewport_height, scroll_height - y)
#             temp_image_path = f'{output_path}{unique_id}_{x}_{y}.png'
#             page.screenshot(path=temp_image_path, clip={'x': 0, 'y': 0, 'width': clip_width, 'height': clip_height})
#             temp_image_paths.append(temp_image_path)
#         # print("hello12")
#     for temp_image_path in temp_image_paths:
#         temp_image = Image.open(temp_image_path)
#         x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
#         stitch_image.paste(temp_image, (x, y))
#     # print("hello3")

#     stitch_image.save(output_path)
#     print(f"Large screenshot saved at {output_path}")
#     return [output_path, temp_image_paths]


# @app.post("/screenshot/")
# def create_screenshot(request: ScreenshotRequest):
#     start_time = time.time()
#     try:
#         # Check if the URL already exists in the database
#         ExistingCheckTime = time.time()
#         existing_entry = check_existing_entry(request.url)
#         if existing_entry:
#             return {
#                 "message": "Screenshot already exists",
#                 "path": existing_entry['output_path'],
#                 "slices": json.loads(existing_entry['slices'])
#                 # "links": existing_entry['links']
#             }
#         print("Existing Check Time: ", time.time() - ExistingCheckTime)
#         output_path = os.path.join(request.output_base_path, "screenshot.png")
#         links, slices = take_screenshot(request.url, output_path, request.browser_type, request.full_page, request.executable_path)
#         elapsed_time = time.time() - start_time
#         print("Try bLock Check time : ",elapsed_time)
        
#         # Store the slices in the database
#         store_slices_in_db(request.url, output_path, slices, links)
        
#         return {"message": "Screenshot taken successfully", "path": output_path, "slices": slices}
#         # , "links": links
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         elapsed_time = time.time() - start_time
#         print("Finally bLock Check time : ",elapsed_time)

# def extract_links(page):
#     return page.evaluate('''() => {
#         return Array.from(document.querySelectorAll('a')).map(a => ({
#             href: a.href,
#             text: a.innerText
#         }));
#     }''')


# def store_slices_in_db(url, output_path, slices, links):
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
#             sql = "INSERT INTO screenshots (url, output_path, slices, links) VALUES (%s, %s, %s, %s)"
#             cursor.execute(sql, (url, output_path, json.dumps(slices), json.dumps(links)))
#         connection.commit()
#     except pymysql.MySQLError as e:
#         print(f"Error: {e}")
#     finally:
#         connection.close()


# def check_existing_entry(url):
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
#             sql = "SELECT output_path, slices, links FROM screenshots WHERE url=%s"
#             cursor.execute(sql, (url,))
#             result = cursor.fetchone()
#             if result:
#                 return {
#                     "output_path": result[0],
#                     "slices": result[1],
#                     "links": result[2]
#                 }
#             return None
#     finally:
#         connection.close()

# def get_links_from_db(url):
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
#             sql = "SELECT links FROM screenshots WHERE url=%s"
#             cursor.execute(sql, (url,))
#             result = cursor.fetchone()
#             if result:
#                 # Parse the JSON string back into a Python object
#                 links = json.loads(result[0])
#                 return {
#                     "links": links
#                 }
#             return None
#     finally:
#         connection.close()


# @app.get("/slice/")
# def get_slice(path: str):
#     if not os.path.exists(path):
#         raise HTTPException(status_code=404, detail="Slice not found")
#     return FileResponse(path)

# @app.get("/links/")
# def get_links(url: str):
#     try: 
        
#         return get_links_from_db(url)

#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
    
# @app.get("/cronjob/")
# def cronjob():
#     try:
#         print("11111")
#         # Get all records older than 2 hours
#         old_records = get_old_records()
#         print("22222")
#         for record in old_records:
#             # Delete images
#             # print(record)
#             slices = json.loads(record[1])
#             # slices = json.loads(record['slices'])
#             # print(slices)
#             for slice_path in slices:
#                 # print(slice_path)
#                 if os.path.exists(slice_path):
#                     os.remove(slice_path)
#                     print(f"Deleted slice: {slice_path}")

#             # Remove record from the database
#             delete_record(record[0])

#         return {"message": "Old records and associated images deleted successfully"}
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# def get_old_records():
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
#             sql = "SELECT id, slices FROM screenshots WHERE timestamp_column > NOW() - INTERVAL 2 HOUR"
#             cursor.execute(sql)
#             result = cursor.fetchall()
#             return result
#     finally:
#         connection.close()

# def delete_record(record_id):
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
#             sql = "DELETE FROM screenshots WHERE id=%s"
#             cursor.execute(sql, (record_id,))
#         connection.commit()
#     except pymysql.MySQLError as e:
#         print(f"Error: {e}")
#     finally:
#         connection.close()



################################### Next version Code ##############################################


# import asyncio
# import sys
# from fastapi import FastAPI, HTTPException
# from fastapi.responses import FileResponse
# from pydantic import BaseModel
# from playwright.async_api import async_playwright
# import os
# import time
# import json
# import cv2
# from PIL import Image
# import pymysql
# import uuid

# # Set WindowsProactorEventLoopPolicy if on Windows
# if sys.platform.startswith('win'):
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# class ScreenshotRequest(BaseModel):
#     url: str
#     output_base_path: str = 'c:/screenshots/'
#     browser_type: str = 'chromium'
#     full_page: bool = True
#     executable_path: str = None

# app = FastAPI()

# async def take_screenshot(url, output_path, browser_type, full_page, executable_path=None):
#     async with async_playwright() as p:
#         if browser_type == "chromium":
#             browser = await p.chromium.launch(headless=True)
#         elif browser_type == "firefox":
#             browser = await p.firefox.launch(headless=True)
#         elif browser_type == "webkit":
#             browser = await p.webkit.launch(headless=True)
#         else:
#             browser = await p.chromium.launch(headless=True)
        
#         context = await browser.new_context(viewport={"width": 1920, "height": 1080})
#         page = await context.new_page()
#         await page.goto(url, timeout=180000)
#         await page.wait_for_load_state('networkidle')

#         # Extract links
#         links = await extract_links(page)
        
#         dimensions = await page.evaluate('''() => {
#             return {
#                 width: document.documentElement.scrollWidth,
#                 height: document.documentElement.scrollHeight
#             }
#         }''')

#         if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
#             output_path = await take_large_screenshot(page, dimensions, output_path)
#         else:
#             await page.screenshot(path=output_path, full_page=full_page, timeout=180000)
#             output_path = slice_and_stretch_image(output_path, "c:/screenshots/")
#             print(f"Screenshot saved at {output_path[0]}")

#         await browser.close()
#         return links, output_path[1] 

# def slice_and_stretch_image(image_path, output_folder):
#     image = cv2.imread(image_path)
#     height, width, _ = image.shape
#     slice_width = 1920
#     slice_height = 1080
    
#     if not os.path.exists(output_folder):
#         os.makedirs(output_folder)
#     temp_image_paths = []
#     slice_count = 1

#     for y in range(0, height, slice_height):
#         for x in range(0, width, slice_width):
#             unique_id = uuid.uuid4().hex
#             end_x = min(x + slice_width, width)
#             end_y = min(y + slice_height, height)
#             temp_image_path = f'{output_folder}{unique_id}_{end_x}_{end_y}.png'
#             # Crop the image slice
#             cropped_slice = image[y:end_y, x:end_x]
            
#             if cropped_slice.shape[1] != slice_width:
#                 cropped_slice = cv2.resize(cropped_slice, (slice_width, cropped_slice.shape[0]), interpolation=cv2.INTER_LINEAR)
            
#             slice_filename = temp_image_path
#             cv2.imwrite(slice_filename, cropped_slice, [cv2.IMWRITE_JPEG_QUALITY, 30])
#             print(f"Saved stretched slice: {slice_filename}")
#             temp_image_paths.append(temp_image_path)
            
#             slice_count += 1
#     return [output_folder, temp_image_paths]

# async def take_large_screenshot(page, dimensions, output_path):
#     scroll_width = dimensions['width']
#     scroll_height = dimensions['height']
#     viewport_width = min(page.viewport_size['width'], 32767)
#     viewport_height = min(page.viewport_size['height'], 32767)
#     stitch_image = Image.new('RGB', (scroll_width, scroll_height))
#     temp_image_paths = []

#     for y in range(0, scroll_height, viewport_height):
#         for x in range(0, scroll_width, viewport_width):
#             unique_id = uuid.uuid4().hex
#             await page.evaluate(f'window.scrollTo({x}, {y})')
#             clip_width = min(viewport_width, scroll_width - x)
#             clip_height = min(viewport_height, scroll_height - y)
#             temp_image_path = f'{output_path}{unique_id}_{x}_{y}.png'
#             await page.screenshot(path=temp_image_path, clip={'x': 0, 'y': 0, 'width': clip_width, 'height': clip_height})
#             temp_image_paths.append(temp_image_path)
            
#     for temp_image_path in temp_image_paths:
#         temp_image = Image.open(temp_image_path)
#         x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
#         stitch_image.paste(temp_image, (x, y))
        
#     stitch_image.save(output_path)
#     print(f"Large screenshot saved at {output_path}")
#     return [output_path, temp_image_paths]

# @app.post("/screenshot/")
# async def create_screenshot(request: ScreenshotRequest):
#     start_time = time.time()
#     try:
#         # Check if the URL already exists in the database
#         ExistingCheckTime = time.time()
#         existing_entry = check_existing_entry(request.url)
#         if existing_entry:
#             return {
#                 "message": "Screenshot already exists",
#                 "path": existing_entry['output_path'],
#                 "slices": json.loads(existing_entry['slices'])
#             }
#         print("Existing Check Time: ", time.time() - ExistingCheckTime)
#         output_path = os.path.join(request.output_base_path, "screenshot.png")
#         links, slices = await take_screenshot(request.url, output_path, request.browser_type, request.full_page, request.executable_path)
#         elapsed_time = time.time() - start_time
#         print("Try bLock Check time : ",elapsed_time)
        
#         # Store the slices in the database
#         store_slices_in_db(request.url, output_path, slices, links)
        
#         return {"message": "Screenshot taken successfully", "path": output_path, "slices": slices}
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         elapsed_time = time.time() - start_time
#         print("Finally bLock Check time : ",elapsed_time)

# async def extract_links(page):
#     return await page.evaluate('''() => {
#         return Array.from(document.querySelectorAll('a')).map(a => ({
#             href: a.href,
#             text: a.innerText
#         }));
#     }''')

# def store_slices_in_db(url, output_path, slices, links):
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
#             sql = "INSERT INTO screenshots (url, output_path, slices, links) VALUES (%s, %s, %s, %s)"
#             cursor.execute(sql, (url, output_path, json.dumps(slices), json.dumps(links)))
#         connection.commit()
#     except pymysql.MySQLError as e:
#         print(f"Error: {e}")
#     finally:
#         connection.close()

# def check_existing_entry(url):
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
#             sql = "SELECT output_path, slices, links FROM screenshots WHERE url=%s"
#             cursor.execute(sql, (url,))
#             result = cursor.fetchone()
#             if result:
#                 return {
#                     "output_path": result[0],
#                     "slices": result[1],
#                     "links": result[2]
#                 }
#             return None
#     finally:
#         connection.close()

# def get_links_from_db(url):
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
#             sql = "SELECT links FROM screenshots WHERE url=%s"
#             cursor.execute(sql, (url,))
#             result = cursor.fetchone()
#             if result:
#                 # Parse the JSON string back into a Python object
#                 links = json.loads(result[0])
#                 return {
#                     "links": links
#                 }
#             return None
#     finally:
#         connection.close()

# @app.get("/slice/")
# def get_slice(path: str):
#     if not os.path.exists(path):
#         raise HTTPException(status_code=404, detail="Slice not found")
#     return FileResponse(path)

# @app.get("/links/")
# def get_links(url: str):
#     try: 
#         return get_links_from_db(url)
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

########################## Last Final Updated code 13/12/2024 #######################
# import asyncio
# import sys
# from fastapi import FastAPI, HTTPException, Query
# from fastapi.responses import FileResponse
# from pydantic import BaseModel
# from playwright.async_api import async_playwright
# import os
# import time
# import requests
# import json
# import cv2
# from PIL import Image
# import pymysql
# import uuid
# from bs4 import BeautifulSoup

# # Set WindowsProactorEventLoopPolicy if on Windows
# if sys.platform.startswith('win'):
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# # Proxy settings
# proxies = {
#     'http': 'http://brd-customer-hl_d9339b7c-zone-serp_api1:w3u1xgsxexj2@brd.superproxy.io:22225',
#     'https': 'http://brd-customer-hl_d9339b7c-zone-serp_api1:w3u1xgsxexj2@brd.superproxy.io:22225'
# }

# # Disable SSL verification warnings
# requests.packages.urllib3.disable_warnings()

# class ScreenshotRequest(BaseModel):
#     url: str
#     output_base_path: str = 'https://usc1.contabostorage.com/gsdatasync/'
#     browser_type: str = 'chromium'
#     full_page: bool = True
#     executable_path: str = None


# app = FastAPI()

# # Endpoint to take a query parameter and fetch results
# @app.get("/search/")
# def search(query: str = Query(..., description="Search query"), searchType: str = Query(..., description="Type of search results")):
#     # Construct the URL with the query parameter
#     # if searchType == "news":
#     print(searchType)
#     if searchType == "general":
#         url = f"https://www.google.com/search?q={query}&gl=us"
#         print("general URL is hitted")
#     else:
#         url = f"https://www.google.com/search?q={query}&tbm={searchType}&brd_json=1&gl=us"
#         print("Other URL is hitted")
#     # Measure execution time
#     start_time = time.time()
    
#     # Make the request
#     try:
#         response = requests.get(url, proxies=proxies, verify=False)
#         response.raise_for_status()  # Raise an error for bad status codes
#     except requests.RequestException as e:
#         return {"error": str(e)}
    
#     end_time = time.time()
#     execution_time = end_time - start_time
    
#     # return {
#     #     "execution_time": execution_time,
#     #     "response": response.text
#     # }
#     if searchType == "general":
#         print("In General")
#         data = []
#         soup = BeautifulSoup(response.text, 'html.parser')
            
#         for result in soup.select(".tF2Cxc"):
#             title = result.select_one(".DKV0Md").text
#             heading = result.select_one(".VuuXrf").text if result.select_one(".VuuXrf") else None
#             image_element = result.select_one(".XNo5Ab")
#             image = image_element.get("src") if image_element else None
#             snippet = result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb").text if result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb") else None
#             links = result.select_one(".yuRUbf a")["href"] if result.select_one(".yuRUbf a") else None

#             data.append({
#                 "title": title,
#                 "image": image,
#                 "description": snippet,
#                 "heading": heading,
#                 "links": links
#             })
#         return data

#     elif searchType == "nws":
#         print("In News")

#         return response.json()['news']
    
#     elif searchType == "isch":
#         print("In Images")

#         return response.json()['images']
    
#     elif searchType == "shop":
#         print("In Shopping")

#         return response.json()['shopping']


# async def take_screenshot(page, url, output_path, full_page):
#     await page.goto(url, timeout=180000)
#     # await page.wait_for_load_state('networkidle')

#     # Extract links
#     links = await extract_links(page)
    
#     dimensions = await page.evaluate('''() => {
#         return {
#             width: document.documentElement.scrollWidth,
#             height: document.documentElement.scrollHeight
#         }
#     }''')

#     if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
#         output_path = await take_large_screenshot(page, dimensions, output_path)
#     else:
#         await page.screenshot(path=output_path, full_page=full_page, timeout=180000)
#         output_path = slice_and_stretch_image(output_path, "https://usc1.contabostorage.com/gsdatasync/")
#         print(f"Screenshot saved at {output_path[0]}")

#     return links, output_path[1]

# def slice_and_stretch_image(image_path, output_folder):
#     image = cv2.imread(image_path)
#     height, width, _ = image.shape
#     slice_width = 1920
#     slice_height = 1080
    
#     if not os.path.exists(output_folder):
#         os.makedirs(output_folder)
#     temp_image_paths = []
#     slice_count = 1

#     for y in range(0, height, slice_height):
#         for x in range(0, width, slice_width):
#             unique_id = uuid.uuid4().hex
#             end_x = min(x + slice_width, width)
#             end_y = min(y + slice_height, height)
#             temp_image_path = f'{output_folder}{unique_id}_{end_x}_{end_y}.png'
#             # Crop the image slice
#             cropped_slice = image[y:end_y, x:end_x]
            
#             if cropped_slice.shape[1] != slice_width:
#                 cropped_slice = cv2.resize(cropped_slice, (slice_width, cropped_slice.shape[0]), interpolation=cv2.INTER_LINEAR)
            
#             slice_filename = temp_image_path
#             cv2.imwrite(slice_filename, cropped_slice, [cv2.IMWRITE_JPEG_QUALITY, 30])
#             print(f"Saved stretched slice: {slice_filename}")
#             temp_image_paths.append(temp_image_path)
            
#             slice_count += 1
#     return [output_folder, temp_image_paths]

# async def take_large_screenshot(page, dimensions, output_path):
#     scroll_width = dimensions['width']
#     scroll_height = dimensions['height']
#     viewport_width = min(page.viewport_size['width'], 32767)
#     viewport_height = min(page.viewport_size['height'], 32767)
#     stitch_image = Image.new('RGB', (scroll_width, scroll_height))
#     temp_image_paths = []

#     for y in range(0, scroll_height, viewport_height):
#         for x in range(0, scroll_width, viewport_width):
#             unique_id = uuid.uuid4().hex
#             await page.evaluate(f'window.scrollTo({x}, {y})')
#             clip_width = min(viewport_width, scroll_width - x)
#             clip_height = min(viewport_height, scroll_height - y)
#             temp_image_path = f'{output_path}{unique_id}_{x}_{y}.png'
#             await page.screenshot(path=temp_image_path, clip={'x': 0, 'y': 0, 'width': clip_width, 'height': clip_height})
#             temp_image_paths.append(temp_image_path)
            
#     for temp_image_path in temp_image_paths:
#         temp_image = Image.open(temp_image_path)
#         x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
#         stitch_image.paste(temp_image, (x, y))
        
#     stitch_image.save(output_path)
#     print(f"Large screenshot saved at {output_path}")
#     return [output_path, temp_image_paths]

# @app.post("/screenshot/")
# async def create_screenshot(request: ScreenshotRequest):
#     start_time = time.time()
#     async with async_playwright() as p:
#         try:
#             if request.browser_type == "chromium":
#                 browser = await p.chromium.launch(headless=True)
#             elif request.browser_type == "firefox":
#                 browser = await p.firefox.launch(headless=True)
#             elif request.browser_type == "webkit":
#                 browser = await p.webkit.launch(headless=True)
#             else:
#                 browser = await p.chromium.launch(headless=True)
            
#             # Check if the URL already exists in the database
#             ExistingCheckTime = time.time()
#             existing_entry = check_existing_entry(request.url)
#             if existing_entry:
#                 return {
#                     "message": "Screenshot already exists",
#                     "path": existing_entry['output_path'],
#                     "slices": json.loads(existing_entry['slices'])
#                 }
#             print("Existing Check Time: ", time.time() - ExistingCheckTime)
#             output_path = os.path.join(request.output_base_path, "screenshot.png")
            
#             context = await browser.new_context(viewport={"width": 1920, "height": 1080})
#             page = await context.new_page()
#             links, slices = await take_screenshot(page, request.url, output_path, request.full_page)
#             await page.close()
#             elapsed_time = time.time() - start_time
#             print("Try bLock Check time : ",elapsed_time)
            
#             # Store the slices in the database
#             store_slices_in_db(request.url, output_path, slices, links)
            
#             return {"message": "Screenshot taken successfully", "path": output_path, "slices": slices}
#         except Exception as e:
#             print(f"An error occurred: {e}")
#             raise HTTPException(status_code=500, detail=str(e))
#         finally:
#             await browser.close()
#             elapsed_time = time.time() - start_time
#             print("Finally bLock Check time : ",elapsed_time)

# async def extract_links(page):
#     return await page.evaluate('''() => {
#         return Array.from(document.querySelectorAll('a')).map(a => ({
#             href: a.href,
#             text: a.innerText
#         }));
#     }''')

# def store_slices_in_db(url, output_path, slices, links):
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
#             sql = "INSERT INTO screenshots (url, output_path, slices, links) VALUES (%s, %s, %s, %s)"
#             cursor.execute(sql, (url, output_path, json.dumps(slices), json.dumps(links)))
#         connection.commit()
#     except pymysql.MySQLError as e:
#         print(f"Error: {e}")
#     finally:
#         connection.close()

# def check_existing_entry(url):
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
#             sql = "SELECT output_path, slices, links FROM screenshots WHERE url=%s"
#             cursor.execute(sql, (url,))
#             result = cursor.fetchone()
#             if result:
#                 return {
#                     "output_path": result[0],
#                     "slices": result[1],
#                     "links": result[2]
#                 }
#             return None
#     finally:
#         connection.close()

# def get_links_from_db(url):
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
#             sql = "SELECT links FROM screenshots WHERE url=%s"
#             cursor.execute(sql, (url,))
#             result = cursor.fetchone()
#             if result:
#                 # Parse the JSON string back into a Python object
#                 links = json.loads(result[0])
#                 return {
#                     "links": links
#                 }
#             return None
#     finally:
#         connection.close()

# @app.get("/slice/")
# def get_slice(path: str):
#     if not os.path.exists(path):
#         raise HTTPException(status_code=404, detail="Slice not found")
#     return FileResponse(path)

# @app.get("/links/")
# def get_links(url: str):
#     try: 
#         return get_links_from_db(url)
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
    
# @app.get("/cronjob/")
# def cronjob(time: int):
#     try:
#         print("11111")
#         # Get all records older than 2 hours
#         old_records = get_old_records(time)
#         print("22222")
#         for record in old_records:
#             # Delete images
#             # print(record)
#             slices = json.loads(record[1])
#             # slices = json.loads(record['slices'])
#             # print(slices)
#             for slice_path in slices:
#                 # print(slice_path)
#                 if os.path.exists(slice_path):
#                     os.remove(slice_path)
#                     print(f"Deleted slice: {slice_path}")

#             # Remove record from the database
#             delete_record(record[0])

#         return {"message": "Old records and associated images deleted successfully"}
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# def get_old_records(time):
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
#         # with connection.cursor() as cursor:
#         #     sql = "SELECT id, slices FROM screenshots WHERE timestamp_column > NOW() - INTERVAL {time} HOUR"
#         #     cursor.execute(sql)
#         #     result = cursor.fetchall()
#         #     return result
#         with connection.cursor() as cursor:
#             # Use parameterized query to safely insert the time value
#             sql = "SELECT id, slices FROM screenshots WHERE timestamp_column < NOW() - INTERVAL %s HOUR"
#             cursor.execute(sql, (time,))
#             result = cursor.fetchall()
#             return result
#     finally:
#         connection.close()

# def delete_record(record_id):
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
#             sql = "DELETE FROM screenshots WHERE id=%s"
#             cursor.execute(sql, (record_id,))
#         connection.commit()
#     except pymysql.MySQLError as e:
#         print(f"Error: {e}")
#     finally:
#         connection.close()

import asyncio
import sys
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright
import os
import io
import time
import requests
import json
import cv2
from PIL import Image
import pymysql
import uuid
from bs4 import BeautifulSoup
import numpy as np
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

# Set WindowsProactorEventLoopPolicy if on Windows
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Proxy settings
proxies = {
    'http': 'http://brd-customer-hl_d9339b7c-zone-serp_api1:w3u1xgsxexj2@brd.superproxy.io:22225',
    'https': 'http://brd-customer-hl_d9339b7c-zone-serp_api1:w3u1xgsxexj2@brd.superproxy.io:22225'
}

# Disable SSL verification warnings
requests.packages.urllib3.disable_warnings()

class ScreenshotRequest(BaseModel):
    url: str
    output_base_path: str = 'https://usc1.contabostorage.com/gsdatasync/'
    browser_type: str = 'chromium'
    full_page: bool = True
    executable_path: str = None


app = FastAPI()


# Initialize S3 client for Contabo storage
s3_client = boto3.client(
    's3',
    endpoint_url='https://usc1.contabostorage.com',  # Contabo storage endpoint
    aws_access_key_id='f4f5b81dec2f7eca236d4ca7210b5d52',
    aws_secret_access_key='fb9b918586db40cd32ee687ed3a2e6da'
)


# Endpoint to take a query parameter and fetch results
@app.get("/search/")
def search(query: str = Query(..., description="Search query"), searchType: str = Query(..., description="Type of search results")):
    # Construct the URL with the query parameter
    # if searchType == "news":
    print(searchType)
    if searchType == "general":
        url = f"https://www.google.com/search?q={query}&gl=us"
        print("general URL is hitted")
    else:
        url = f"https://www.google.com/search?q={query}&tbm={searchType}&brd_json=1&gl=us"
        print("Other URL is hitted")
    # Measure execution time
    start_time = time.time()
    
    # Make the request
    try:
        response = requests.get(url, proxies=proxies, verify=False)
        response.raise_for_status()  # Raise an error for bad status codes
    except requests.RequestException as e:
        return {"error": str(e)}
    
    end_time = time.time()
    execution_time = end_time - start_time
    
    # return {
    #     "execution_time": execution_time,
    #     "response": response.text
    # }
    if searchType == "general":
        print("In General")
        data = []
        soup = BeautifulSoup(response.text, 'html.parser')
            
        for result in soup.select(".tF2Cxc"):
            title = result.select_one(".DKV0Md").text
            heading = result.select_one(".VuuXrf").text if result.select_one(".VuuXrf") else None
            image_element = result.select_one(".XNo5Ab")
            image = image_element.get("src") if image_element else None
            snippet = result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb").text if result.select_one(".VwiC3b,.r025kc,.hJNv6b,.Hdw6tb") else None
            links = result.select_one(".yuRUbf a")["href"] if result.select_one(".yuRUbf a") else None

            data.append({
                "title": title,
                "image": image,
                "description": snippet,
                "heading": heading,
                "links": links
            })
        return data

    elif searchType == "nws":
        print("In News")

        return response.json()['news']
    
    elif searchType == "isch":
        print("In Images")

        return response.json()['images']
    
    elif searchType == "shop":
        print("In Shopping")

        return response.json()['shopping']


async def take_screenshot(page, url, output_path, full_page):
    await page.goto(url, timeout=180000)
    # await page.wait_for_load_state('networkidle')

    # Extract links
    links = await extract_links(page)
    
    dimensions = await page.evaluate('''() => {
        return {
            width: document.documentElement.scrollWidth,
            height: document.documentElement.scrollHeight
        }
    }''')

    if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
        screenshot_path, slices = await take_large_screenshot(page, dimensions, output_path)
    else:
        # await page.screenshot(path=output_path, full_page=full_page, timeout=180000)
        print("Before Main Screenshot")
        screenshot_bytes = await page.screenshot(full_page=True, type='png', timeout=180000)
        print("After Main Screenshot")
        # Upload screenshot to Contabo storage
        # try:
        #     s3_client.upload_file(output_path, 'gsdatasync', f'screenshots{os.path.basename(output_path)}', ExtraArgs={'ACL': 'public-read', 'ContentType': 'image/png'})
        #     remote_path = f'https://usc1.contabostorage.com/gsdatasync/{os.path.basename(output_path)}'
        # except (NoCredentialsError, PartialCredentialsError) as e:
        #     print(f"Error uploading to Contabo: {e}")
        #     return None

        slices = slice_and_stretch_image(screenshot_bytes, s3_client)
        print(f"Screenshot saved at {slices}")

    return links, slices

    # if full_page and (dimensions['width'] > 32767 or dimensions['height'] > 32767):
    #     output_path = await take_large_screenshot(page, dimensions, output_path)
    # else:
    #     await page.screenshot(path=output_path, full_page=full_page, timeout=180000)
    #     output_path = slice_and_stretch_image(output_path, "https://usc1.contabostorage.com/gsdatasync/")
    #     print(f"Screenshot saved at {output_path[0]}")

    # return links, output_path[1]

def slice_and_stretch_image(image_path, s3_client):
    print("In slice_and_stretch_image function")
    # Convert bytes data to a NumPy array
    nparr = np.frombuffer(image_path, np.uint8)
    # Decode image data to OpenCV format
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    print("Converted ByteImage to Image")
    # image = cv2.imread(image_path)
    height, width, _ = image.shape
    slice_width = 1920
    slice_height = 1080

    temp_image_paths = []
    slice_count = 1

    for y in range(0, height, slice_height):
        for x in range(0, width, slice_width):
            unique_id = uuid.uuid4().hex
            end_x = min(x + slice_width, width)
            end_y = min(y + slice_height, height)
            temp_image_path = f'{unique_id}_{end_x}_{end_y}.png'
            # Crop the image slice
            cropped_slice = image[y:end_y, x:end_x]

            if cropped_slice.shape[1] != slice_width:
                cropped_slice = cv2.resize(cropped_slice, (slice_width, cropped_slice.shape[0]), interpolation=cv2.INTER_LINEAR)

            slice_filename = temp_image_path
            print("Before saving Slices in buffer")
            is_success, buffer = cv2.imencode('.png', cropped_slice, [cv2.IMWRITE_PNG_COMPRESSION, 9])
            print("After saving Slices in buffer")
            if is_success:
                image_data = buffer.tobytes()
                image_file_obj = io.BytesIO(image_data)
                # image_data = buffer.tobytes()
            # cv2.imwrite(slice_filename, cropped_slice, [cv2.IMWRITE_JPEG_QUALITY, 30])
            # print(f"Saved stretched slice: {slice_filename}")

            # Upload the image slice to the Contabo bucket
                try:
                    print("before uploading slice to bucket")
                    s3_client.upload_fileobj(image_file_obj, 'gsdatasync', f'{os.path.basename(temp_image_path)}', ExtraArgs={'ACL': 'public-read', 'ContentType': 'image/png'})
                    # s3_client.upload_file(image_data, 'gsdatasync', f'{os.path.basename(slice_filename)}', ExtraArgs={'ACL': 'public-read', 'ContentType': 'image/png'})
                    print("After uploading slice to bucket")
                    remote_path = f'{os.path.basename(slice_filename)}'
                    temp_image_paths.append(remote_path)
                except (NoCredentialsError, PartialCredentialsError) as e:
                    print(f"Error uploading to Contabo: {e}")
                    return None

                slice_count += 1

    return temp_image_paths

# def slice_and_stretch_image(image_path, output_folder):
#     image = cv2.imread(image_path)
#     height, width, _ = image.shape
#     slice_width = 1920
#     slice_height = 1080
    
#     if not os.path.exists(output_folder):
#         os.makedirs(output_folder)
#     temp_image_paths = []
#     slice_count = 1

#     for y in range(0, height, slice_height):
#         for x in range(0, width, slice_width):
#             unique_id = uuid.uuid4().hex
#             end_x = min(x + slice_width, width)
#             end_y = min(y + slice_height, height)
#             temp_image_path = f'{output_folder}{unique_id}_{end_x}_{end_y}.png'
#             # Crop the image slice
#             cropped_slice = image[y:end_y, x:end_x]
            
#             if cropped_slice.shape[1] != slice_width:
#                 cropped_slice = cv2.resize(cropped_slice, (slice_width, cropped_slice.shape[0]), interpolation=cv2.INTER_LINEAR)
            
#             slice_filename = temp_image_path
#             cv2.imwrite(slice_filename, cropped_slice, [cv2.IMWRITE_JPEG_QUALITY, 30])
#             print(f"Saved stretched slice: {slice_filename}")
#             temp_image_paths.append(temp_image_path)
            
#             slice_count += 1
#     return [output_folder, temp_image_paths]

async def take_large_screenshot(page, dimensions, output_path):
    scroll_width = dimensions['width']
    scroll_height = dimensions['height']
    viewport_width = min(page.viewport_size['width'], 32767)
    viewport_height = min(page.viewport_size['height'], 32767)
    stitch_image = Image.new('RGB', (scroll_width, scroll_height))
    temp_image_paths = []

    for y in range(0, scroll_height, viewport_height):
        for x in range(0, scroll_width, viewport_width):
            unique_id = uuid.uuid4().hex
            await page.evaluate(f'window.scrollTo({x}, {y})')
            clip_width = min(viewport_width, scroll_width - x)
            clip_height = min(viewport_height, scroll_height - y)
            temp_image_path = f'{output_path}{unique_id}_{x}_{y}.png'
            await page.screenshot(path=temp_image_path, clip={'x': 0, 'y': 0, 'width': clip_width, 'height': clip_height})
            temp_image_paths.append(temp_image_path)
            
    for temp_image_path in temp_image_paths:
        temp_image = Image.open(temp_image_path)
        x, y = map(int, temp_image_path.replace(output_path, '').replace('.png', '').split('_')[1:])
        stitch_image.paste(temp_image, (x, y))
        
    stitch_image.save(output_path)
    print(f"Large screenshot saved at {output_path}")
    return [output_path, temp_image_paths]

@app.post("/screenshot/")
async def create_screenshot(request: ScreenshotRequest):
    start_time = time.time()
    async with async_playwright() as p:
        try:
            if request.browser_type == "chromium":
                browser = await p.chromium.launch(headless=True)
            elif request.browser_type == "firefox":
                browser = await p.firefox.launch(headless=True)
            elif request.browser_type == "webkit":
                browser = await p.webkit.launch(headless=True)
            else:
                browser = await p.chromium.launch(headless=True)
            
            # Check if the URL already exists in the database
            ExistingCheckTime = time.time()
            existing_entry = check_existing_entry(request.url)
            if existing_entry:
                return {
                    "message": "Screenshot already exists",
                    "path": existing_entry['output_path'],
                    "slices": json.loads(existing_entry['slices'])
                }
            print("Existing Check Time: ", time.time() - ExistingCheckTime)
            output_path = os.path.join(request.output_base_path, "screenshot.png")
            
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})
            page = await context.new_page()
            links, slices = await take_screenshot(page, request.url, output_path, request.full_page)
            await page.close()
            elapsed_time = time.time() - start_time
            print("Try bLock Check time : ",elapsed_time)
            
            # Store the slices in the database
            store_slices_in_db(request.url, output_path, slices, links)
            
            return {"message": "Screenshot taken successfully", "path": output_path, "slices": slices}
        except Exception as e:
            print(f"An error occurred: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            await browser.close()
            elapsed_time = time.time() - start_time
            print("Finally bLock Check time : ",elapsed_time)

async def extract_links(page):
    return await page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a')).map(a => ({
            href: a.href,
            text: a.innerText
        }));
    }''')

def store_slices_in_db(url, output_path, slices, links):
    connection = pymysql.connect(
        host='alldbserver.mysql.database.azure.com',
        user='usman.shabbir@invicttus.com',
        password='Veroke@94',
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
        user='usman.shabbir@invicttus.com',
        password='Veroke@94',
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
        user='usman.shabbir@invicttus.com',
        password='Veroke@94',
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
    
@app.get("/cronjob/")
def cronjob(time: int):
    try:
        print("11111")
        # Get all records older than 2 hours
        old_records = get_old_records(time)
        print("22222")
        for record in old_records:
            # Delete images
            # print(record)
            slices = json.loads(record[1])
            # slices = json.loads(record['slices'])
            # print(slices)
            for slice_path in slices:
                # print(slice_path)
                try:
                    response = s3_client.delete_object(Bucket=f'gsdatasync', Key=slice_path)
                    if response['ResponseMetadata']['HTTPStatusCode'] == 204:
                        print(f"Image successfully deleted from {f'gsdatasync'}/{slice_path}")
                        return True
                    else:
                        print(f"Failed to delete image from {f'gsdatasync'}/{slice_path}. Response: {response}")
                        return False
                except (NoCredentialsError, PartialCredentialsError) as e:
                    print(f"Error deleting from Contabo: {e}")
                    return False
                except Exception as e:
                    print(f"Unexpected error: {e}")
                    return False
                # if os.path.exists(slice_path):
                #     os.remove(slice_path)
                #     print(f"Deleted slice: {slice_path}")

            # Remove record from the database
            delete_record(record[0])

        return {"message": "Old records and associated images deleted successfully"}
    except Exception as e:
        print(f"An error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def get_old_records(time):
    connection = pymysql.connect(
        host='alldbserver.mysql.database.azure.com',
        user='usman.shabbir@invicttus.com',
        password='Veroke@94',
        database='devtest',
        ssl={
            'ca': 'DigiCertGlobalRootCA.crt 1.pem'
        }
    )
    try:
        # with connection.cursor() as cursor:
        #     sql = "SELECT id, slices FROM screenshots WHERE timestamp_column > NOW() - INTERVAL {time} HOUR"
        #     cursor.execute(sql)
        #     result = cursor.fetchall()
        #     return result
        with connection.cursor() as cursor:
            # Use parameterized query to safely insert the time value
            sql = "SELECT id, slices FROM screenshots WHERE timestamp_column < NOW() - INTERVAL %s HOUR"
            cursor.execute(sql, (time,))
            result = cursor.fetchall()
            return result
    finally:
        connection.close()

def delete_record(record_id):
    connection = pymysql.connect(
        host='alldbserver.mysql.database.azure.com',
        user='usman.shabbir@invicttus.com',
        password='Veroke@94',
        database='devtest',
        ssl={
            'ca': 'DigiCertGlobalRootCA.crt 1.pem'
        }
    )
    try:
        with connection.cursor() as cursor:
            sql = "DELETE FROM screenshots WHERE id=%s"
            cursor.execute(sql, (record_id,))
        connection.commit()
    except pymysql.MySQLError as e:
        print(f"Error: {e}")
    finally:
        connection.close()












