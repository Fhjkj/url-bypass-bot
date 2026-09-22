"""Handler for javhdporn.net video URLs.

Clicking .play-button navigates to stripchat.com which loads the HLS
stream from doppiocdn.net. We intercept the master .m3u8 playlist URL
the moment it appears in network traffic.
"""
import os
import re
import random
import time
import logging
import httpx
from FZBypass.core.exceptions import DDLException

LOGGER = logging.getLogger(__name__)

# Cache valid Cloudflare bypass credentials to eliminate duplicate
# browser cycles on Render (saves CPU and reduces Solver API load).
CF_COOKIE_CACHE = {
    "cookies": [],
    "user_agent": None,
    "expires_at": 0,
}


async def javhdporn(url: str) -> str:
    """Extract HLS stream URL by clicking .play-button and intercepting network traffic."""
    from playwright.async_api import async_playwright
    global CF_COOKIE_CACHE

    SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-edc7.up.railway.app")

    # Proxy pool for hiding solver API calls (optional)
    proxy_pool = os.environ.get("BYPASS_PROXY_POOL", "")
    proxies = [p.strip() for p in proxy_pool.split(",") if p.strip()] if proxy_pool else []

    def get_proxy():
        if proxies:
            return random.choice(proxies)
        return None

    result = None
    current_time = time.time()

    # Step 1: Check if we have unexpired valid cookies cached in memory
    if CF_COOKIE_CACHE["cookies"] and current_time < CF_COOKIE_CACHE["expires_at"]:
        result = {
            "cookies": CF_COOKIE_CACHE["cookies"],
            "user_agent": CF_COOKIE_CACHE["user_agent"],
        }
    else:
        # Step 2: Rapid external API call with short timeout
        try:
            proxy = get_proxy()
            async with httpx.AsyncClient(proxy=proxy, follow_redirects=True, verify=False) as client:
                response = await client.post(
                    f"{SOLVER_API}/solve-challenge",
                    json={"siteurl": url, "timeout": 30},
                    timeout=12,
                )
                if response.status_code == 200:
                    result = response.json()
                else:
                    raise DDLException(f"External infrastructure returned status: {response.status_code}")
        except httpx.RequestError:
            pass

        # Step 3: Local Fallback - use Playwright to decrypt the data-mpu payload
        if not result:
            from FZBypass.core.turnstile_solver import solve_challenge
            local_result = await solve_challenge(url, timeout_ms=30000)
            if local_result.success:
                result = {
                    "cookies": local_result.cookies,
                    "user_agent": local_result.user_agent,
                }
                CF_COOKIE_CACHE["cookies"] = local_result.cookies
                CF_COOKIE_CACHE["user_agent"] = local_result.user_agent
                CF_COOKIE_CACHE["expires_at"] = current_time + 3600
            else:
                raise DDLException(f"Cloudflare bypass failed: {local_result.error}")

    cookies = result.get("cookies", [])
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

    # Step 4: Initialize Playwright Engine
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-blink-features=AutomationControlled',
            ]
        )
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=user_agent,
        )

        # Insert Cloudflare authorization credentials
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        # Intercept ALL network requests for .m3u8 URLs
        hls_urls = []
        mp4_urls = []

        def handle_request(req):
            try:
                req_url = req.url
                if '.m3u8' in req_url:
                    if req_url not in hls_urls:
                        hls_urls.append(req_url)
                elif '.mp4' in req_url:
                    if req_url not in mp4_urls:
                        mp4_urls.append(req_url)
            except Exception:
                pass

        page.on("request", handle_request)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        except Exception as e:
            await browser.close()
            raise DDLException(f"Browser navigation failed: {str(e)}")

        # Step 5: Click .play-button to trigger navigation to stripchat.com
        # This is the critical step - clicking play navigates to the streaming
        # platform which then loads the HLS stream from doppiocdn.net
        try:
            play_btn = page.locator(".play-button").first
            if await play_btn.count() > 0:
                box = await play_btn.boundingBox()
                if box:
                    await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                else:
                    await play_btn.click(timeout=2000, force=True)
        except Exception as e:
            LOGGER.debug("Play button click error: %s", e)

        # Also try clicking #video-player as fallback
        try:
            vp = page.locator("#video-player").first
            box = await vp.boundingBox()
            if box:
                await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        except Exception:
            pass

        # Step 6: Wait for HLS stream to load
        # The play button click navigates to stripchat.com which loads
        # the HLS stream. We poll for up to 45 seconds (Render Free Tier
        # is slow - single core, limited memory).
        deadline = time.time() + 45
        while time.time() < deadline:
            # Check if we have a master playlist URL
            master_urls = [u for u in hls_urls if 'master' in u.lower() or '_auto' in u.lower()]
            if master_urls:
                break
            await page.wait_for_timeout(1000)

        await browser.close()

    # Step 7: Filter and prioritize
    # Remove ad/tracker ping URLs
    clean_hls = [u for u in hls_urls if 'ping.m3u8' not in u.lower()]

    # Prioritize master playlists (contain 'master' or '_auto')
    master_urls = [u for u in clean_hls if 'master' in u.lower() or '_auto' in u.lower()]

    if master_urls:
        return master_urls[0]

    # Fallback: any HLS URL
    if clean_hls:
        return clean_hls[0]

    # Last resort: any MP4 from doppiocdn
    clean_mp4 = [u for u in mp4_urls if 'doppiocdn' in u.lower() and 'banner' not in u.lower()]
    if clean_mp4:
        return clean_mp4[0]

    raise DDLException("Security gate cleared, but the network layer did not catch the stream request context.")