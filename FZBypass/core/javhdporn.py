"""Handler for javhdporn.net video URLs.

Overrides global browser decoding hooks to grab the decrypted
payload right out of cast.js memory before it wraps it inside the player.
"""
import os
import re
import random
import httpx
from FZBypass.core.exceptions import DDLException


async def javhdporn(url: str) -> str:
    """Intercept client-side decryption routines directly in Playwright runtime memory."""
    from playwright.async_api import async_playwright

    SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")

    # Proxy pool for hiding solver API calls (use if Render IP gets blocked)
    proxy_pool = os.environ.get("BYPASS_PROXY_POOL", "")
    proxies = [p.strip() for p in proxy_pool.split(",") if p.strip()] if proxy_pool else []

    def get_proxy():
        if proxies:
            return random.choice(proxies)
        return None

    # Step 1: Solve Cloudflare to secure access cookies
    proxy = get_proxy()
    async with httpx.AsyncClient(proxy=proxy, follow_redirects=True, verify=False) as client:
        try:
            response = await client.post(
                f"{SOLVER_API}/solve-challenge",
                json={"siteurl": url, "timeout": 60},
                timeout=120
            )
            if response.status_code != 200:
                raise DDLException(f"Cloudflare bypass dropped: Status {response.status_code}")
            result = response.json()
        except httpx.ConnectError as e:
            raise DDLException(f"Cannot connect to Solver API: {str(e)}")
        except httpx.TimeoutException as e:
            raise DDLException(f"Solver API timeout: {str(e)}")
        except Exception as e:
            raise DDLException(f"Bypass handshake crashed: {type(e).__name__}: {str(e)}")

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

            // Hook Base64 Decoder - capture only strings containing video URLs
            const originalAtob = window.atob;
            window.atob = function(str) {
                try {
                    const decoded = originalAtob(str);
                    if (decoded && (decoded.includes('.m3u8') || decoded.includes('.mp4') || decoded.includes('doppiocdn') || decoded.includes('edge-hls'))) {
                        window._capturedStreams.push(decoded);
                    }
                } catch(e) {}
                return originalAtob(str);
            };

            // Hook JSON Parser
            const originalParse = JSON.parse;
            JSON.parse = function(text) {
                if (text && (text.includes('.m3u8') || text.includes('.mp4') || text.includes('doppiocdn') || text.includes('edge-hls'))) {
                    window._capturedStreams.push(text);
                }
                return originalParse(text);
            };

            // Hook XMLHttpRequest
            const origOpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url) {
                if (url && (url.includes('.m3u8') || url.includes('.mp4') || url.includes('doppiocdn') || url.includes('edge-hls'))) {
                    window._capturedUrls.push(url);
                }
                return origOpen.apply(this, arguments);
            };

            // Hook fetch
            const origFetch = window.fetch;
            window.fetch = function(url, opts) {
                if (url) {
                    var u = typeof url === 'string' ? url : url.href || String(url);
                    if (u.includes('.m3u8') || u.includes('.mp4') || u.includes('doppiocdn') || u.includes('edge-hls')) {
                        window._capturedUrls.push(u);
                    }
                }
                return origFetch.apply(this, arguments);
            };

            // Hook video element src setter
            const videoProto = HTMLVideoElement.prototype;
            const origSrc = Object.getOwnPropertyDescriptor(videoProto, 'src');
            if (origSrc && origSrc.set) {
                Object.defineProperty(videoProto, 'src', {
                    set: function(val) {
                        if (val && (val.includes('.m3u8') || val.includes('.mp4') || val.includes('doppiocdn') || val.includes('edge-hls'))) {
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
                        if (val && (val.includes('.m3u8') || val.includes('.mp4') || val.includes('doppiocdn') || val.includes('edge-hls'))) {
                            window._capturedUrls.push(val);
                        }
                        return iframeSrc.set.call(this, val);
                    }
                });
            }
        """)

        # Network listener as a fallback layer
        async def handle_response(res):
            res_url = res.url
            if any(ext in res_url.lower() for ext in ['.m3u8', '.mp4']):
                if res_url not in video_urls:
                    video_urls.append(res_url)

        page.on("response", handle_response)

        try:
            # Let the page load its structural frames
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            await browser.close()
            raise DDLException(f"Browser navigation timed out: {str(e)}")

        # Step 4: Simulate a genuine interaction on the player area to kick-start cast.js
        try:
            await page.wait_for_selector("#video-player", timeout=5000)
            await page.click("#video-player", timeout=2000)
        except:
            pass

        # Also click the play button specifically
        try:
            await page.click(".play-button", timeout=3000)
        except:
            pass

        # Step 5: Read the decrypted string right out of window memory
        for _ in range(5):
            await page.wait_for_timeout(2000)
            try:
                # Pull whatever strings the injected script caught inside the window runtime
                memory_strings = await page.evaluate("window._capturedStreams")
                for item in memory_strings:
                    matches = re.findall(r'(https?://[^\s"\']+\.(?:m3u8|mp4)[^\s"\']*)', item)
                    for match in matches:
                        clean_url = match.replace("&amp;", "&")
                        if clean_url not in video_urls:
                            video_urls.append(clean_url)

                # Also pull captured URLs from XHR/fetch/video/iframe hooks
                captured_urls = await page.evaluate("window._capturedUrls")
                for u in captured_urls:
                    clean_url = u.replace("&amp;", "&")
                    if clean_url not in video_urls:
                        video_urls.append(clean_url)
            except:
                pass

        # Fallback: scan all frames for HLS/MP4 URLs in raw HTML
        try:
            for frame in page.frames:
                try:
                    frame_html = await frame.content()
                    matches = re.findall(r'(https?://[^\s"\']+\.(?:m3u8|mp4)[^\s"\']*)', frame_html)
                    for match in matches:
                        clean_url = match.replace("&amp;", "&")
                        if clean_url not in video_urls:
                            video_urls.append(clean_url)
                except:
                    pass
        except:
            pass

        await browser.close()

    # Step 6: Strict Filtering & Cleanup
    # Remove obvious ad/tracker noise but keep ALL stream candidates
    clean_streams = [
        u for u in video_urls
        if 'banner' not in u.lower()
        and 'ping.m3u8' not in u.lower()
        and 'ads/' not in u.lower()
        and 'pop' not in u.lower()
    ]

    # Separate HLS streams from MP4 files
    hls_urls = [u for u in clean_streams if '.m3u8' in u]
    mp4_urls = [u for u in clean_streams if '.mp4' in u]

    # Prefer HLS master/adaptive playlists (the actual video stream)
    hls_master = [u for u in hls_urls if 'master' in u.lower() or '_auto' in u.lower()]
    if hls_master:
        return str(hls_master[0])
    if hls_urls:
        return str(hls_urls[0])
    if mp4_urls:
        # Filter out obvious thumbnail/preview MP4s only when we have alternatives
        real_mp4 = [u for u in mp4_urls if 'storagexhd' not in u.lower()
                    and 'thumbnail' not in u.lower()
                    and 'medium' not in u.lower()
                    and 'thumb' not in u.lower()]
        if real_mp4:
            return str(real_mp4[0])
        return str(mp4_urls[0])

    raise DDLException("Page decoded securely, but no active streaming strings were released.")