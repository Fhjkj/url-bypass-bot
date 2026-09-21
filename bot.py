import os
import time
import asyncio
from logging import getLogger
from threading import Thread

from flask import Flask, request, jsonify

from dataclasses import asdict

try:
    from FZBypass import Bypass
    from FZBypass.core.turnstile_solver import solve_sync, SolveResult
    from pyrogram.errors import FloodWait
    from pyrogram import idle
    TELEGRAM_AVAILABLE = True
except SystemExit:
    LOGGER = getLogger(__name__)
    LOGGER.warning("Telegram client disabled - missing credentials")
    Bypass = None
    SolveResult = None
    FloodWait = None
    idle = None
    TELEGRAM_AVAILABLE = False
except Exception as exc:
    LOGGER = getLogger(__name__)
    LOGGER.warning("Telegram client not available: %s", exc)
    Bypass = None
    SolveResult = None
    FloodWait = None
    idle = None
    TELEGRAM_AVAILABLE = False

app = Flask(__name__)
LOGGER = getLogger(__name__)
telegram_ready = False
flood_wait_until = 0.0


@app.get("/")
def home():
    return "FZ Bypass Bot is running", 200


@app.get("/health")
def health():
    remaining = max(0, int(flood_wait_until - time.time())) if flood_wait_until else 0
    return {
        "ok": True,
        "service": "fz-bypass-bot",
        "telegram_ready": telegram_ready,
        "telegram_flood_wait_seconds": remaining,
    }, 200


@app.post("/solve")
@app.post("/solve-challenge")
def solve():
    """Solve a Cloudflare Turnstile challenge for the given URL."""
    if not TELEGRAM_AVAILABLE or SolveResult is None:
        return jsonify({"success": False, "error": "Telegram client not available"}), 503
    payload = request.get_json(silent=True) or {}
    url = payload.get("url") or request.form.get("url")
    if not url:
        return jsonify({"success": False, "error": "Missing 'url' field"}), 400

    try:
        timeout_ms = int(payload.get("timeout_ms", 45000))
    except (TypeError, ValueError):
        timeout_ms = 45000

    headless = payload.get("headless", True)
    if isinstance(headless, str):
        headless = headless.lower() not in {"0", "false", "no", "off"}

    result: SolveResult = solve_sync(url, timeout_ms=timeout_ms, headless=headless)
    return jsonify(asdict(result))


@app.get("/bypass")
def bypass():
    """Bypass Cloudflare and extract video stream URL."""
    url = request.args.get("url")
    if not url:
        return jsonify({"success": False, "error": "Missing 'url' parameter"}), 400

    try:
        result = asyncio.run(_extract_video_url(url))
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


async def _extract_video_url(url):
    """Extract video URL using Playwright after solving Cloudflare."""
    from playwright.async_api import async_playwright
    import httpx

    SOLVER_API = os.environ.get("SOLVER_API", "https://turnstile-solver-production-7e59.up.railway.app")

    # Step 1: Solve CF challenge
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SOLVER_API}/solve-challenge",
            json={"siteurl": url, "timeout": 60},
            timeout=120
        )
        if response.status_code != 200:
            return {"success": False, "error": "Failed to solve CF challenge"}
        result = response.json()

    cookies = result.get("cookies", [])
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

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

        for cookie in cookies:
            await context.add_cookies([cookie])

        video_urls = []
        all_requests = []

        async def handle_request(request):
            req_url = request.url
            all_requests.append(req_url)
            if any(ext in req_url.lower() for ext in ['.m3u8', '.mp4']):
                if req_url not in video_urls:
                    video_urls.append(req_url)

        page.on("request", handle_request)

        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(5000)

        # Try to extract video URL from page JS state
        video_src = await page.evaluate("""() => {
            const video = document.querySelector('video');
            if (video) {
                return video.src || video.currentSrc;
            }
            const wpst = document.querySelector('#wpst-video');
            if (wpst) {
                return wpst.src || wpst.currentSrc;
            }
            const mpuEl = document.querySelector('[data-mpu]');
            if (mpuEl) {
                return mpuEl.getAttribute('data-mpu');
            }
            return null;
        }""")
        if video_src:
            print(f"Video src from page: {video_src}")

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

        # Trigger video play via JS
        try:
            await page.evaluate("""() => {
                const video = document.querySelector('video');
                if (video) {
                    video.play();
                    video.muted = true;
                }
                const wpst = document.querySelector('#wpst-video');
                if (wpst) {
                    wpst.play();
                    wpst.muted = true;
                }
                if (typeof videojs !== 'undefined') {
                    const players = videojs.getPlayers();
                    for (const key in players) {
                        if (players[key]) players[key].play();
                    }
                }
            }""")
            await page.wait_for_timeout(2000)
        except:
            pass

        # Wait for video to load and stream segments
        await page.wait_for_timeout(20000)
        await browser.close()

        # Filter for actual video URLs
        video_urls = [u for u in video_urls if 'banner' not in u.lower() and 'storagexhd' not in u.lower()]

        # Prefer HLS master playlists
        hls_urls = [u for u in video_urls if '.m3u8' in u and 'master' in u.lower()]
        if not hls_urls:
            hls_urls = [u for u in video_urls if '.m3u8' in u]

        if hls_urls:
            return {
                "success": True,
                "video_url": hls_urls[0],
                "all_urls": video_urls[:10]
            }
        elif video_urls:
            return {
                "success": True,
                "video_url": video_urls[0],
                "all_urls": video_urls[:10]
            }
        else:
            return {"success": False, "error": "No video URL found"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    # Start Flask server in background
    flask_thread = Thread(target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False), daemon=True)
    flask_thread.start()
    LOGGER.info(f"Flask server started on port {port}")

    # Try to start Telegram client (optional - Flask endpoints still work without it)
    if TELEGRAM_AVAILABLE:
        try:
            while True:
                try:
                    Bypass.start()
                    telegram_ready = True
                    flood_wait_until = 0.0
                    LOGGER.info("Telegram client started successfully")
                    break
                except FloodWait as exc:
                    wait_seconds = max(int(getattr(exc, "value", 60)), 60)
                    telegram_ready = False
                    flood_wait_until = time.time() + wait_seconds
                    LOGGER.error(
                        "Telegram FloodWait during startup; bot actions are paused for %s seconds.",
                        wait_seconds,
                    )
                    try:
                        if getattr(Bypass, "is_connected", False):
                            Bypass.stop()
                    except Exception as stop_error:
                        LOGGER.warning("Could not reset Telegram client: %s", stop_error)
                    time.sleep(wait_seconds)
                except Exception as exc:
                    LOGGER.error("Telegram client failed to start: %s", exc)
                    telegram_ready = False
                    break
            try:
                idle()
            finally:
                Bypass.stop()
        except Exception as exc:
            LOGGER.warning("Telegram not available, Flask endpoints still work: %s", exc)
            # Keep Flask running
            flask_thread.join()
    else:
        LOGGER.info("Telegram not available, keeping Flask server running")
        flask_thread.join()