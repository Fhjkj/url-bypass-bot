"""Handler for javhdporn.net video URLs.

Uses Turnstile Solver API + Playwright to bypass Cloudflare and extract
the HLS video URL from the encrypted page.
"""
import os
import re
import httpx
from FZBypass.core.exceptions import DDLException


async def javhdporn(url: str) -> str:
    """Extract video URL from javhdporn.net."""
    from playwright.async_api import async_playwright

    SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")

    # Step 1: Solve CF challenge
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        try:
            response = await client.post(
                f"{SOLVER_API}/solve-challenge",
                json={"siteurl": url, "timeout": 60},
                timeout=120
            )
            if response.status_code != 200:
                raise DDLException(f"Solver API returned status {response.status_code}")
            result = response.json()
        except httpx.ConnectError as e:
            raise DDLException(f"Cannot connect to Solver API: {str(e)}")
        except httpx.TimeoutException as e:
            raise DDLException(f"Solver API timeout: {str(e)}")
        except Exception as e:
            raise DDLException(f"Solver API error: {type(e).__name__}: {str(e)}")

    cookies = result.get("cookies", [])
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0")

    # Step 2: Use Playwright to load page and trigger video decryption
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
        page = await context.new_page()

        if cookies:
            await context.add_cookies(cookies)

        video_urls = []
        all_requests = []

        async def handle_request(request):
            req_url = request.url
            all_requests.append(req_url)
            if any(ext in req_url.lower() for ext in ['.m3u8', '.mp4']):
                if req_url not in video_urls:
                    video_urls.append(req_url)

        async def handle_response(response):
            res_url = response.url
            if any(ext in res_url.lower() for ext in ['.m3u8', '.mp4']):
                if res_url not in video_urls:
                    video_urls.append(res_url)

        page.on("request", handle_request)
        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            await browser.close()
            raise DDLException(f"Page loading timed out: {str(e)}")

        await page.wait_for_timeout(4000)

        # UPDATED ACTION BLOCK: Target the modern player containers and video components
        try:
            # 1. Target standard play overlay wrappers
            await page.click(".player-container, .play-wrapper, .vjs-big-play-button", timeout=2000)
        except:
            pass

        try:
            # 2. Click directly on the video render surface if available
            await page.click("video", position={"x": 100, "y": 100}, timeout=2000)
        except:
            pass

        # Step 3: Loop inside any iframe layers to force underlying players open
        frames = page.frames
        for frame in frames:
            try:
                # Force click video nodes inside embeds
                await frame.click("video, .play-button, .player-poster", timeout=1500)
            except:
                pass
            try:
                # Execute a universal playback event loop directly inside the window context
                await frame.evaluate("""() => {
                    const videos = document.querySelectorAll('video');
                    videos.forEach(v => { v.play(); v.muted = true; });
                }""")
            except:
                pass

        # Give the decrypted streams 10 seconds to generate chunk keys and manifests
        await page.wait_for_timeout(10000)

        # Try to extract video URL from page JS state as fallback
        try:
            video_src = await page.evaluate("""() => {
                // Check all video elements
                const videos = document.querySelectorAll('video');
                for (const v of videos) {
                    if (v.src && (v.src.includes('.m3u8') || v.src.includes('.mp4'))) {
                        return v.src;
                    }
                    if (v.currentSrc && (v.currentSrc.includes('.m3u8') || v.currentSrc.includes('.mp4'))) {
                        return v.currentSrc;
                    }
                }
                // Check videojs players
                if (typeof videojs !== 'undefined') {
                    const players = videojs.getPlayers();
                    for (const key in players) {
                        const player = players[key];
                        if (player && player.src) {
                            const src = player.src();
                            if (src && (src.includes('.m3u8') || src.includes('.mp4'))) {
                                return src;
                            }
                        }
                    }
                }
                return null;
            }""")
            if video_src and video_src not in video_urls:
                video_urls.append(video_src)
        except:
            pass

        await browser.close()

    # Filter out advertising domains & tracking noise
    video_urls = [
        u for u in video_urls
        if 'banner' not in u.lower()
        and 'storagexhd' not in u.lower()
        and 'ping.m3u8' not in u.lower()
        and 'ads' not in u.lower()
    ]

    # Prioritize master index manifests
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
        raise DDLException("No playable streaming video source detected on the page context.")