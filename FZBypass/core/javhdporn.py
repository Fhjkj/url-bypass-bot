"""Handler for javhdporn.net video URLs.

Overrides global browser decoding hooks to grab the decrypted
payload right out of cast.js memory before it wraps it inside the player.
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
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0")

    # Step 4: Initialize Playwright Engine with strict resource limits
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--single-process',
                '--no-zygote',
                '--disable-extensions',
                '--disable-software-rasterizer',
                '--memory-limit=128',
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
        video_urls = []

        # LIGHTWEIGHT EVENT LISTENER: Catches the link instantly in background network traffic
        # This completely replaces the heavy frame.content() string parsing loops!
        def handle_response(res):
            try:
                res_url = res.url
                if any(ext in res_url.lower() for ext in ['.m3u8', '.mp4']):
                    if res_url not in video_urls:
                        video_urls.append(res_url)
            except Exception:
                pass

        page.on("response", handle_response)

        # Also capture ALL network response URLs (not just .m3u8/.mp4) so we
        # can see what the player is actually requesting.
        all_network_urls = []
        def handle_response_all(res):
            try:
                u = res.url
                if u not in all_network_urls:
                    all_network_urls.append(u)
            except Exception:
                pass
        page.on("response", handle_response_all)

        # RUNTIME MEMORY HOOKS: cast.js decrypts the data-mpu payload and
        # assigns the result directly into JS variables / video.src without
        # firing a network request. The response listener above would never
        # see it. These hooks intercept the decrypted URL the moment it
        # appears in memory. We capture ALL strings (not just .m3u8/.mp4)
        # because the decrypted URL may be a redirect or a different format.
        await page.add_init_script("""
            (() => {
                const captured = [];
                const isUrl = (s) => typeof s === 'string' && s.startsWith('http');

                function record(url) {
                    if (isUrl(url) && !captured.includes(url)) {
                        captured.push(url);
                    }
                }

                // Hook HTMLVideoElement.prototype.src setter
                const origSrc = Object.getOwnPropertyDescriptor(HTMLVideoElement.prototype, 'src');
                if (origSrc && origSrc.set) {
                    Object.defineProperty(HTMLVideoElement.prototype, 'src', {
                        set: function(v) { record(v); origSrc.set.call(this, v); },
                        configurable: true,
                    });
                }

                // Hook HTMLMediaElement.setAttribute for src
                const origSetAttr = HTMLElement.prototype.setAttribute;
                HTMLElement.prototype.setAttribute = function(name, value) {
                    if (name.toLowerCase() === 'src') record(value);
                    return origSetAttr.call(this, name, value);
                };

                // Hook window.atob (cast.js uses base64 decoding)
                const origAtob = window.atob;
                window.atob = function(s) {
                    const out = origAtob(s);
                    try { record(out); } catch(e) {}
                    return out;
                };

                // Hook fetch
                const origFetch = window.fetch;
                window.fetch = function(...args) {
                    if (args[0]) record(String(args[0]));
                    return origFetch.apply(this, args);
                };

                // Hook XMLHttpRequest open
                const origOpen = XMLHttpRequest.prototype.open;
                XMLHttpRequest.prototype.open = function(method, url) {
                    record(String(url));
                    return origOpen.apply(this, arguments);
                };

                // Hook video.play / video.srcObject
                const origPlay = HTMLVideoElement.prototype.play;
                HTMLVideoElement.prototype.play = function() {
                    if (this.src) record(this.src);
                    return origPlay.apply(this, arguments);
                };

                // Expose captured list for later polling
                window.__video_urls_captured = captured;
            })();
        """)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            # NOTE: Do NOT wait_for_selector here. Playwright's wait_for_selector
            # with state="attached" can still time out even when the element is
            # present (the call log proves #video-player is in the DOM with
            # data-mpu populated). Proceeding directly to the click avoids the
            # spurious timeout and lets cast.js decryption run.
        except Exception as e:
            await browser.close()
            raise DDLException(f"Browser navigation failed: {str(e)}")

        # RE-INJECT HOOKS AFTER PAGE LOAD: Some sites load cast.js in a way
        # that runs before add_init_script takes effect. Re-applying the
        # hooks after navigation ensures they're active when decryption runs.
        try:
            await page.evaluate("""
                (() => {
                    if (window.__video_hooks_applied) return;
                    window.__video_hooks_applied = true;
                    const captured = window.__video_urls_captured || [];
                    const isUrl = (s) => typeof s === 'string' && s.startsWith('http');

                    function record(url) {
                        if (isUrl(url) && !captured.includes(url)) {
                            captured.push(url);
                        }
                    }

                    const origSrc = Object.getOwnPropertyDescriptor(HTMLVideoElement.prototype, 'src');
                    if (origSrc && origSrc.set) {
                        Object.defineProperty(HTMLVideoElement.prototype, 'src', {
                            set: function(v) { record(v); origSrc.set.call(this, v); },
                            configurable: true,
                        });
                    }

                    const origSetAttr = HTMLElement.prototype.setAttribute;
                    HTMLElement.prototype.setAttribute = function(name, value) {
                        if (name.toLowerCase() === 'src') record(value);
                        return origSetAttr.call(this, name, value);
                    };

                    const origAtob = window.atob;
                    window.atob = function(s) {
                        const out = origAtob(s);
                        try { record(out); } catch(e) {}
                        return out;
                    };

                    const origFetch = window.fetch;
                    window.fetch = function(...args) {
                        if (args[0]) record(String(args[0]));
                        return origFetch.apply(this, args);
                    };

                    const origOpen = XMLHttpRequest.prototype.open;
                    XMLHttpRequest.prototype.open = function(method, url) {
                        record(String(url));
                        return origOpen.apply(this, arguments);
                    };

                    const origPlay = HTMLVideoElement.prototype.play;
                    HTMLVideoElement.prototype.play = function() {
                        if (this.src) record(this.src);
                        return origPlay.apply(this, arguments);
                    };

                    window.__video_urls_captured = captured;
                })();
            """)
        except Exception:
            pass

        # Step 5: Trigger synthetic mouse events to unpack the _0x3fe11f listener hooks
        try:
            box = await page.locator("#video-player").first.bounding_box()
            if box:
                await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            else:
                await page.click("#video-player", timeout=1500, force=True)
        except:
            try:
                await page.click("#video-player", timeout=1500, force=True)
            except:
                pass

        # Step 6: Low-Overhead Idle Sleep
        # Poll the runtime memory hooks every 2 seconds to capture the
        # decrypted URL as soon as cast.js assigns it. The 35-second ceiling
        # gives the single-core CPU plenty of time to run the decryption.
        deadline = time.time() + 35
        while time.time() < deadline:
            try:
                captured = await page.evaluate("() => window.__video_urls_captured || []")
                for u in captured:
                    if u not in video_urls:
                        video_urls.append(u)
            except Exception:
                pass
            # Early exit: stop waiting once we have a valid stream URL
            if any(('.m3u8' in u or ('.mp4' in u and 'doppiocdn' in u.lower())) for u in video_urls):
                break
            await page.wait_for_timeout(2000)

        # Merge in any network URLs we captured (for diagnostics)
        for u in all_network_urls:
            if u not in video_urls:
                video_urls.append(u)

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
        # Debug dump: show what we actually captured so we can diagnose
        # why filtering dropped everything.
        from FZBypass import LOGGER
        LOGGER.warning("javhdporn: captured %d raw URLs: %s", len(video_urls), video_urls[:20])
        raise DDLException("Ad-filter verified, but the primary movie asset engine did not respond in time.")