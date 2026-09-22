"""Handler for javhdporn.net video URLs.

Clicking .play-button triggers cast.js which decrypts data-mpu and
creates a black.html iframe. The iframe gets banned for headless browsers,
but before that happens, cast.js sends analytics calls to tesorf.com
containing the real video ID (wid). We intercept the wid from the
analytics traffic and construct the HLS URL directly.
"""
import os
import re
import random
import time
import logging
import httpx
from FZBypass.core.exceptions import DDLException

LOGGER = logging.getLogger(__name__)

CF_COOKIE_CACHE = {
    "cookies": [],
    "user_agent": None,
    "expires_at": 0,
}


async def javhdporn(url: str) -> str:
    """Extract HLS stream URL by intercepting the wid from analytics traffic."""
    from playwright.async_api import async_playwright
    global CF_COOKIE_CACHE

    SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-edc7.up.railway.app")

    proxy_pool = os.environ.get("BYPASS_PROXY_POOL", "")
    proxies = [p.strip() for p in proxy_pool.split(",") if p.strip()] if proxy_pool else []

    def get_proxy():
        if proxies:
            return random.choice(proxies)
        return None

    result = None
    current_time = time.time()

    if CF_COOKIE_CACHE["cookies"] and current_time < CF_COOKIE_CACHE["expires_at"]:
        result = {
            "cookies": CF_COOKIE_CACHE["cookies"],
            "user_agent": CF_COOKIE_CACHE["user_agent"],
        }
    else:
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

        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        captured_wids = []
        captured_streams = []

        def handle_request(req):
            try:
                req_url = req.url
                if '.m3u8' in req_url or '.mp4' in req_url:
                    if req_url not in captured_streams:
                        captured_streams.append(req_url)
                # Capture wid from analytics calls
                if 'tesorf.com' in req_url or 'nocrit.com' in req_url:
                    m = re.search(r'[?&]wid=(\d+)', req_url)
                    if m:
                        wid = m.group(1)
                        if wid not in captured_wids:
                            captured_wids.append(wid)
            except Exception:
                pass

        async def handle_response(res):
            try:
                res_url = res.url
                if "doppiocdn" in res_url.lower() or "edge-hls" in res_url.lower() or ".m3u8" in res_url.lower():
                    if any(ext in res_url.lower() for ext in ['.m3u8', '.mp4']):
                        if res_url not in captured_streams:
                            captured_streams.append(res_url)
            except Exception:
                pass

        context.on("request", handle_request)
        context.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        except Exception as e:
            await browser.close()
            raise DDLException(f"Browser navigation failed: {str(e)}")

        try:
            play_btn = page.locator(".play-button").first
            if await play_btn.count() > 0:
                box = await play_btn.boundingBox()
                if box:
                    await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                else:
                    await play_btn.click(timeout=2000, force=True)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
        except Exception as e:
            LOGGER.debug("Play button click error: %s", e)

        try:
            vp = page.locator("#video-player").first
            box = await vp.boundingBox()
            if box:
                await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        except Exception:
            pass

        deadline = time.time() + 30
        final_video_url = None
        while time.time() < deadline:
            await page.wait_for_timeout(2000)

            # If we captured a wid, construct HLS URL directly
            if captured_wids and not final_video_url:
                wid = captured_wids[-1]
                hls_url = f"https://media-hls.doppiocdn.net/b-hls-10/{wid}/{wid}.m3u8?playlistType=lowLatency&preferredVideoCodec=h264"
                LOGGER.info("javhdporn: constructed HLS URL from wid=%s: %s", wid, hls_url)
                final_video_url = hls_url
                break

            clean_targets = [
                u for u in captured_streams
                if 'banner' not in u.lower()
                and 'ping.m3u8' not in u.lower()
                and '300x250' not in u.lower()
                and '728x90' not in u.lower()
            ]

            if clean_targets:
                master_manifests = [u for u in clean_targets if 'master' in u.lower() or '_auto' in u.lower()]
                if len(master_manifests) > 1:
                    final_video_url = master_manifests[-1]
                    break
                elif len(clean_targets) > 1:
                    final_video_url = clean_targets[-1]
                    break
                else:
                    final_video_url = master_manifests[0] if master_manifests else clean_targets[0]

        LOGGER.info("javhdporn: captured %d wids, %d stream URLs, final_url: %s",
                     len(captured_wids), len(captured_streams), final_video_url or "none")

        await browser.close()

        if final_video_url:
            return final_video_url

    raise DDLException("Security gate cleared, but the network layer did not catch the stream request context.")