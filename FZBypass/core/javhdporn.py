"""Handler for javhdporn.net video URLs.

Overrides global browser decoding hooks to grab the decrypted
payload right out of cast.js memory before it wraps it inside the player.
"""
import os
import re
import httpx
from FZBypass.core.exceptions import DDLException


async def javhdporn(url: str) -> str:
    """Intercept client-side decryption routines directly in Playwright runtime memory."""
    from playwright.async_api import async_playwright

    SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")

    # Step 1: Solve Cloudflare to secure access cookies
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
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
                '--headless=new'
            ]
        )
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=user_agent
        )

        # Insert Cloudflare authorization credentials
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()
        video_urls = []

        # Step 3: INJECT RUNTIME MEMORY HOOK (The Cheat Code)
        # This intercepts the exact moment cast.js decrypts the data-mpu payload string
        await page.add_init_script("""
            window._capturedStreams = [];

            // Hook Base64 Decoder
            const originalAtob = window.atob;
            window.atob = function(str) {
                const decoded = originalAtob(str);
                if (decoded.includes('.m3u8') || decoded.includes('.mp4')) {
                    window._capturedStreams.push(decoded);
                }
                return decoded;
            };

            // Hook JSON Parser (In case it unpacks into a config object)
            const originalParse = JSON.parse;
            JSON.parse = function(text) {
                if (text.includes('.m3u8') || text.includes('.mp4')) {
                    window._capturedStreams.push(text);
                }
                return originalParse(text);
            };
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
            except:
                pass

        await browser.close()

    # Step 6: Strict Filtering & Cleanup
    # Exclude ad/banner/tracking noise and related-video thumbnails
    clean_streams = [
        u for u in video_urls
        if 'banner' not in u.lower()
        and 'ping.m3u8' not in u.lower()
        and 'ads' not in u.lower()
        and 'pop' not in u.lower()
        and 'storagexhd' not in u.lower()
        and 'thumbnail' not in u.lower()
        and 'medium' not in u.lower()
        and 'thumb' not in u.lower()
    ]

    # Prioritize HLS master playlists (the actual video stream)
    hls_urls = [u for u in clean_streams if '.m3u8' in u and ('master' in u.lower() or '_auto' in u.lower())]
    if not hls_urls:
        hls_urls = [u for u in clean_streams if '.m3u8' in u]
    if not hls_urls:
        hls_urls = [u for u in clean_streams if '.mp4' in u]

    # Return a solid string back to the Telegram Handler framework
    if hls_urls and len(hls_urls) > 0:
        return str(hls_urls[0])
    else:
        raise DDLException("Page decoded securely, but no active streaming strings were released.")