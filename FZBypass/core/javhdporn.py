"""Handler for javhdporn.net video URLs.

Overrides global browser decoding hooks to grab the decrypted
payload right out of cast.js memory before it wraps it inside the player.
"""
import os
import re
import random
import time
import httpx
from FZBypass.core.exceptions import DDLException

# Cache valid Cloudflare bypass credentials to eliminate duplicate
# browser cycles on Render (saves CPU and reduces Solver API load).
CF_COOKIE_CACHE = {
    "cookies": [],
    "user_agent": None,
    "expires_at": 0,
}


async def javhdporn(url: str) -> str:
    """Intercept client-side decryption routines directly in Playwright runtime memory."""
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
            # If the server is completely down or unreachable, bypass immediately
            pass

        # Step 3: Local Fallback - use Playwright to decrypt the data-mpu payload
        # The Solver API returns cookies but the video URL is encrypted in cast.js
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
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0")

    # Step 2: Initialize Playwright Engine
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            channel="chromium",
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--headless=new',
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

        # Spoof navigator.webdriver to avoid bot detection
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)
        video_urls = []

        # Step 3: INJECT RUNTIME MEMORY HOOKS (The Cheat Code)
        # This intercepts the exact moment cast.js decrypts the data-mpu payload string
        await page.add_init_script("""
            window._capturedStreams = [];
            window._capturedUrls = [];
            window._capturedVideos = [];

            // Hook Base64 Decoder - capture ALL decoded strings (we filter later)
            const originalAtob = window.atob;
            window.atob = function(str) {
                try {
                    const decoded = originalAtob(str);
                    if (decoded && decoded.length > 10) {
                        window._capturedStreams.push(decoded);
                    }
                } catch(e) {}
                return originalAtob(str);
            };

            // Hook JSON Parser - capture ALL parsed strings
            const originalParse = JSON.parse;
            JSON.parse = function(text) {
                if (text && text.length > 10) {
                    window._capturedStreams.push(text);
                }
                return originalParse(text);
            };

            // Hook XMLHttpRequest
            const origOpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url) {
                if (url) window._capturedUrls.push(url);
                return origOpen.apply(this, arguments);
            };

            // Hook fetch
            const origFetch = window.fetch;
            window.fetch = function(url, opts) {
                if (url) {
                    var u = typeof url === 'string' ? url : url.href || String(url);
                    window._capturedUrls.push(u);
                }
                return origFetch.apply(this, arguments);
            };

            // Hook video element src setter
            const videoProto = HTMLVideoElement.prototype;
            const origSrc = Object.getOwnPropertyDescriptor(videoProto, 'src');
            if (origSrc && origSrc.set) {
                Object.defineProperty(videoProto, 'src', {
                    set: function(val) {
                        if (val) {
                            window._capturedVideos.push(val);
                            window._capturedUrls.push(val);
                        }
                        return origSrc.set.call(this, val);
                    }
                });
            }

            // Hook iframe src setter
            const iframeProto = HTMLIFrameElement.prototype;
            const iframeSrc = Object.getOwnPropertyDescriptor(iframeProto, 'src');
            if (iframeSrc && iframeSrc.set) {
                Object.defineProperty(iframeProto, 'src', {
                    set: function(val) {
                        if (val) window._capturedUrls.push(val);
                        return iframeSrc.set.call(this, val);
                    }
                });
            }

            // Hook video play() to catch when the main video starts playing
            const origPlay = HTMLVideoElement.prototype.play;
            HTMLVideoElement.prototype.play = function() {
                if (this.src) window._capturedVideos.push(this.src);
                return origPlay.apply(this, arguments);
            };
        """)

        # Network listener as a fallback layer (sync handler to avoid event-loop blocking)
        def handle_response(res):
            try:
                res_url = res.url
                if any(ext in res_url.lower() for ext in ['.m3u8', '.mp4']):
                    if res_url not in video_urls:
                        video_urls.append(res_url)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            # Let the page load its structural frames
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            await browser.close()
            raise DDLException(f"Browser navigation timed out: {str(e)}")

        # Step 2: Force wait for the decryption placeholder to mount
        try:
            await page.wait_for_selector("#video-player, [data-mpu]", timeout=10000)
        except:
            pass

        # Step 3: Hard-trigger synthetic mouse coordinate dispatching
        # Obfuscated files look for bounding coordinate flags to prevent generic scraping loops
        try:
            box = await page.locator("#video-player").first.bounding_box()
            if box:
                await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        except:
            try:
                await page.click("#video-player", timeout=2000)
            except:
                pass

        # Step 4: Robust 30-Second Decryption Verification Loop
        # Gives cast.js ample time to parse atob variables on the single core
        for _ in range(15):
            await page.wait_for_timeout(2000)

            for frame in page.frames:
                try:
                    frame_html = await frame.content()
                    # Deep match for any freshly generated streaming targets post-decryption
                    matches = re.findall(r'(https?://[^\s"\']+\.(?:m3u8|mp4)[^\s"\']*)', frame_html)
                    for match in matches:
                        clean_match = match.replace("&amp;", "&")
                        if clean_match not in video_urls:
                            video_urls.append(clean_match)
                except:
                    pass

        await browser.close()

    # Step 6: SAFE FILTERING (Keeps the real video servers while discarding banners)
    clean_streams = []

    url_parts = url.lower().strip('/').split('/')
    target_code = url_parts[-1].replace('-decensored', '').replace('-uncensored', '')  # e.g. "apak-095"

    for u in video_urls:
        url_lower = u.lower()

        # FIXED: Removed generic 'ads' block string which was breaking the player tracking layer
        if any(bad in url_lower for bad in ['banner', 'ping.m3u8', '300x250', '728x90', 'tracking', 'click', 'popup']):
            continue

        # Target matching: If it is an ad preview loop of an old variant, drop it
        if "apak-" in url_lower and target_code not in url_lower:
            continue

        if u not in clean_streams:
            clean_streams.append(u)

    # Step 7: Direct prioritization loop
    # Filter for the real HLS Master manifest links
    hls_urls = [u for u in clean_streams if '.m3u8' in u]

    # If no HLS manifests captured, look for the unthrottled storage delivery streams
    if not hls_urls:
        hls_urls = [u for u in clean_streams if 'storagexhd' in u.lower() and '.mp4' in u]

    # Step 8: Output string conversion
    if hls_urls and len(hls_urls) > 0:
        return hls_urls[0]  # Grab the top clean asset path string
    else:
        raise DDLException("Ad-filter verified, but the primary movie asset engine did not respond in time.")