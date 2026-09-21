"""Analyze javhdporn.net page to find how video URL is loaded."""
import asyncio
import os
import httpx
from playwright.async_api import async_playwright

SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")
URL = "https://www.javhdporn.net/video/apak-095-decensored/"


async def analyze():
    # Step 1: Solve CF challenge
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SOLVER_API}/solve-challenge",
            json={"siteurl": URL, "timeout": 60},
            timeout=120
        )
        result = response.json()
        print(f"Solver response keys: {list(result.keys())}")
        print(f"Success: {result.get('success')}")
        print(f"Final URL: {result.get('final_url')}")

    cookies = result.get("cookies", [])
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    # Step 2: Use Playwright to analyze page
    async with async_playwright() as p:
        chromium_path = os.environ.get("CHROMIUM_PATH")
        launch_options = {"headless": False, "slow_mo": 500}
        if chromium_path and os.path.isfile(chromium_path):
            launch_options["executable_path"] = chromium_path
        browser = await p.chromium.launch(**launch_options)
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=user_agent
        )
        page = await context.new_page()

        for cookie in cookies:
            await context.add_cookies([cookie])

        # Collect all network requests
        all_requests = []
        all_responses = []

        async def handle_request(request):
            req_url = request.url
            all_requests.append(req_url)
            print(f"REQUEST: {req_url}")

        async def handle_response(response):
            resp_url = response.url
            try:
                body = await response.text()
                all_responses.append({"url": resp_url, "body": body[:2000]})
            except:
                pass

        page.on("request", handle_request)
        page.on("response", handle_response)

        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # Get page HTML
        html = await page.content()
        with open("/tmp/jav_page.html", "w") as f:
            f.write(html)

        # Look for video-related elements
        print("\n=== Page title ===")
        print(await page.title())

        print("\n=== Looking for video elements ===")
        video_elements = await page.query_selector_all("video")
        for v in video_elements:
            src = await v.get_attribute("src")
            print(f"Video src: {src}")

        print("\n=== Looking for #wpst-video ===")
        wpst = await page.query_selector("#wpst-video")
        if wpst:
            print(f"Found #wpst-video: {await wpst.get_attribute('src')}")
            print(f"Inner HTML: {await wpst.inner_html()}")

        print("\n=== Looking for #video-player ===")
        vp = await page.query_selector("#video-player")
        if vp:
            print(f"Found #video-player")
            print(f"Outer HTML: {await vp.outer_html()[:2000]}")

        print("\n=== Looking for data-mpu ===")
        mpu_els = await page.query_selector_all("[data-mpu]")
        for el in mpu_els:
            print(f"data-mpu: {await el.get_attribute('data-mpu')}")

        print("\n=== Looking for scripts ===")
        scripts = await page.query_selector_all("script")
        for i, s in enumerate(scripts):
            src = await s.get_attribute("src")
            if src:
                print(f"Script {i}: src={src}")

        print("\n=== Clicking play button ===")
        try:
            await page.click(".play-button", timeout=5000)
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Play button click failed: {e}")

        print("\n=== Clicking video player ===")
        try:
            await page.click("#video-player", position={"x": 400, "y": 300}, timeout=5000)
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Video player click failed: {e}")

        print("\n=== All requests after clicks ===")
        for req in all_requests:
            if any(ext in req.lower() for ext in ['.m3u8', '.mp4', '.ajax', 'getvideo', 'play', 'video']):
                print(f"  {req}")

        # Wait more and check for new requests
        await page.wait_for_timeout(5000)

        print("\n=== Final video element check ===")
        video_elements = await page.query_selector_all("video")
        for v in video_elements:
            src = await v.get_attribute("src")
            print(f"Video src: {src}")

        print("\n=== Checking for any m3u8/mp4 in all requests ===")
        for req in all_requests:
            if '.m3u8' in req or '.mp4' in req:
                print(f"  {req}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(analyze())