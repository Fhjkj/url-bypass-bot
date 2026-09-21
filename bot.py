import os
import time
import asyncio
from logging import getLogger
from threading import Thread

from flask import Flask, request, jsonify
from pyrogram import idle
from pyrogram.errors import FloodWait

from dataclasses import asdict

from FZBypass import Bypass
from FZBypass.core.turnstile_solver import solve_sync, SolveResult

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
    """Solve a Cloudflare Turnstile challenge for the given URL.

    Request body (JSON):
        url: str            - protected page URL (required)
        timeout_ms: int     - navigation timeout in ms (optional, default 45000)
        headless: bool      - run browser headless (optional, default true)

    Response (JSON):
        success, url, final_url, token, cookies, clearance_cookie,
        error, elapsed_ms
    """
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
    """Bypass Cloudflare and extract video stream URL.

    Query params:
        url: str - protected page URL (required)

    Returns:
        success, video_url, all_urls
    """
    url = request.args.get("url")
    if not url:
        return jsonify({"success": False, "error": "Missing 'url' parameter"}), 400

    try:
        result = asyncio.run(_extract_video_url(url))
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


async def _extract_video_url(url):
    """Extract video URL by solving CF challenge and using Playwright."""
    from playwright.async_api import async_playwright
    import httpx

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
                return {"success": False, "error": f"Solver API returned status {response.status_code}"}
            result = response.json()
        except httpx.ConnectError as e:
            return {"success": False, "error": f"Cannot connect to Solver API: {str(e)}"}
        except httpx.TimeoutException as e:
            return {"success": False, "error": f"Solver API timeout: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Solver API error: {type(e).__name__}: {str(e)}"}

    cookies = result.get("cookies", [])
    user_agent = result.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0")

    # Step 2: Use Playwright to load page and trigger video decryption
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=user_agent
        )
        page = await context.new_page()

        if cookies:
            await context.add_cookies(cookies)

        video_urls = []

        async def handle_response(response):
            res_url = response.url
            if any(ext in res_url.lower() for ext in ['.m3u8', '.mp4']):
                if res_url not in video_urls:
                    video_urls.append(res_url)

        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            await browser.close()
            return {"success": False, "error": f"Page loading timed out: {str(e)}"}

        await page.wait_for_timeout(5000)

        # Traverse inside iframes to hit embedded video host players
        frames = page.frames
        for frame in frames:
            try:
                await frame.click("video", timeout=2000)
            except:
                pass
            try:
                await frame.evaluate("""() => {
                    const v = document.querySelector('video');
                    if(v) { v.play(); v.muted = true; }
                }""")
            except:
                pass

        # Global playback click fallback
        try:
            await page.click(".play-button", timeout=3000)
        except:
            pass

        # Allow stream links to buffer and reveal themselves in responses
        await page.wait_for_timeout(10000)
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
        return {"success": False, "error": "No playable streaming video source detected on the page context."}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    Thread(target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False), daemon=True).start()
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
                "Telegram FloodWait during startup; bot actions are paused for %s seconds. "
                "Keeping health server alive and retrying after cooldown.",
                wait_seconds,
            )
            try:
                if getattr(Bypass, "is_connected", False):
                    Bypass.stop()
            except Exception as stop_error:
                LOGGER.warning("Could not reset Telegram client after FloodWait: %s", stop_error)
            time.sleep(wait_seconds)
    try:
        idle()
    finally:
        Bypass.stop()
