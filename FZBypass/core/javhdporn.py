"""Handler for javhdporn.net video URLs.

Uses Playwright + Turnstile Solver to bypass Cloudflare and extract
the HLS video URL from the encrypted page.
"""
import os
import asyncio
import httpx
from FZBypass.core.exceptions import DDLException


async def javhdporn(url: str) -> str:
    """Extract video URL from javhdporn.net.

    Steps:
    1. Call Turnstile Solver API to get Cloudflare clearance cookies
    2. Use Playwright to load the page with those cookies
    3. Click play button to trigger video decryption
    4. Intercept network requests for .m3u8 / .mp4 URLs
    5. Return the HLS master playlist URL
    """
    from playwright.async_api import async_playwright

    SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")

    # Step 1: Solve CF challenge
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SOLVER_API}/solve-challenge",
            json={"siteurl": url, "timeout": 60},
            timeout=120
        )
        if response.status_code != 200:
            raise DDLException("Failed to solve CF challenge")
        result = response.json()

    cookies = result.get("cookies", [])
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0")

    # Step 2: Use Playwright to load page and trigger video decryption
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage'
                ]
            )
        except Exception:
            # Fallback: try to install browsers at runtime
            import subprocess
            import sys
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium", "chromium-headless-shell"],
                env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/render/project/src/.cache/ms-playwright")},
                check=False,
            )
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage'
                ]
            )
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=user_agent
        )
        page = await context.new_page()

        for cookie in cookies:
            await context.add_cookies([cookie])

        video_urls = []

        async def handle_request(request):
            req_url = request.url
            if any(ext in req_url.lower() for ext in ['.m3u8', '.mp4']):
                if req_url not in video_urls:
                    video_urls.append(req_url)

        page.on("request", handle_request)

        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # Click play button to trigger decryption
        try:
            await page.click(".play-button", timeout=5000)
            await page.wait_for_timeout(2000)
        except:
            pass

        # Also try clicking video player area
        try:
            await page.click("#video-player", position={"x": 400, "y": 300}, timeout=5000)
            await page.wait_for_timeout(2000)
        except:
            pass

        # Wait for video to load and stream segments
        await page.wait_for_timeout(10000)
        await browser.close()

    # Filter out ads and banners
    video_urls = [u for u in video_urls if 'banner' not in u.lower() and 'storagexhd' not in u.lower() and 'ping.m3u8' not in u.lower()]

    # Prefer HLS master playlists
    hls_urls = [u for u in video_urls if '.m3u8' in u and 'master' in u.lower()]
    if not hls_urls:
        hls_urls = [u for u in video_urls if '.m3u8' in u and '_auto' in u.lower()]
    if not hls_urls:
        hls_urls = [u for u in video_urls if '.m3u8' in u]

    if hls_urls:
        return hls_urls[0]
    elif video_urls:
        return video_urls[0]
    else:
        raise DDLException("No video URL found on the page")