"""Handler for javhdporn.net video URLs.

Clicking .play-button navigates to stripchat.com which loads the HLS
stream from doppiocdn.net. We intercept the master .m3u8 playlist URL
the moment it appears in network traffic.
"""
import re
import time
import logging
import httpx
from FZBypass import Config
from FZBypass.core.exceptions import DDLException
from FZBypass.core.proxy_pool import configured_proxies

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

    SOLVER_API = Config.SOLVER_API.rstrip("/")

    result = None
    current_time = time.time()

    # Step 1: Check if we have unexpired valid cookies cached in memory
    if CF_COOKIE_CACHE["cookies"] and current_time < CF_COOKIE_CACHE["expires_at"]:
        result = {
            "cookies": CF_COOKIE_CACHE["cookies"],
            "user_agent": CF_COOKIE_CACHE["user_agent"],
        }
    else:
        # Step 2: Try the shared deployment proxy pool for the external solver,
        # then direct as a fallback. Compose/host environment is the same for
        # ToonWorld, social downloads, provider scrapers, and this handler.
        proxies = configured_proxies()
        solver_attempts = [*proxies, None] if proxies else [None]
        for proxy in solver_attempts:
            try:
                async with httpx.AsyncClient(proxy=proxy, follow_redirects=True, verify=False) as client:
                    response = await client.post(
                        f"{SOLVER_API}/solve-challenge",
                        json={"siteurl": url, "timeout": 30},
                        timeout=12,
                    )
                    if response.status_code == 200:
                        result = response.json()
                        break
            except httpx.RequestError:
                continue

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
                # Wait for navigation to complete (stripchat.com loads)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
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

        # Step 6: Passive Monitoring Interval with Sequence Array Interception
        # Wipes out SSAI 20-second dynamic ad wrappers completely
        # Monitor the stream layout for up to 60 seconds to allow the ad
        # token swap to finish (Render Free Tier is slow).
        deadline = time.time() + 60
        final_video_url = None
        while time.time() < deadline:
            await page.wait_for_timeout(2000)

            # Clean out obvious banner overlays and tracking pixels
            clean_targets = [
                u for u in hls_urls
                if 'banner' not in u.lower()
                and 'ping.m3u8' not in u.lower()
                and '300x250' not in u.lower()
                and '728x90' not in u.lower()
            ]

            if clean_targets:
                # Isolate the high-definition multi-bitrate master manifests
                master_manifests = [u for u in clean_targets if 'master' in u.lower() or '_auto' in u.lower()]

                # CRITICAL SELECTION LAYER:
                # When the site runs without adblock, it injects the 20s ad manifest FIRST.
                # Once the ad segment passes its buffer check, the player creates a SECOND distinct master URL.
                # The second master link generated contains the actual full-length 1080p content.
                if len(master_manifests) > 1:
                    # Select the absolute latest manifest registered in the pipeline array
                    final_video_url = master_manifests[-1]
                    break
                elif len(clean_targets) > 1:
                    # Fallback if the manifest layout wraps files differently
                    final_video_url = clean_targets[-1]
                    break
                else:
                    # Temporary storage assignment if only one link has rendered so far
                    final_video_url = master_manifests[0] if master_manifests else clean_targets[0]

        # Log what we captured for debugging
        LOGGER.info("javhdporn: captured %d HLS URLs, %d MP4 URLs, final page: %s, final_url: %s",
                     len(hls_urls), len(mp4_urls), page.url[:200], final_video_url or "none")

        await browser.close()

        if final_video_url:
            return final_video_url

    raise DDLException("Security gate cleared, but the network layer did not catch the stream request context.")
