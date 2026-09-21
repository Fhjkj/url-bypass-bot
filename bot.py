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
    """Extract video URL by solving CF challenge and parsing HTML."""
    import httpx
    import re

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

    html = result.get("html", "")
    if not html:
        return {"success": False, "error": "No HTML returned from Solver API"}

    # Step 2: Extract video URL directly from HTML
    hls_urls = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
    hls_urls = [
        u for u in hls_urls
        if 'banner' not in u.lower()
        and 'storagexhd' not in u.lower()
        and 'ping.m3u8' not in u.lower()
        and 'ads' not in u.lower()
        and 'doppiocdn' in u.lower()
    ]

    master_urls = [u for u in hls_urls if 'master' in u.lower()]
    if not master_urls:
        master_urls = [u for u in hls_urls if '_auto' in u.lower()]
    if not master_urls:
        master_urls = hls_urls

    if master_urls:
        return {
            "success": True,
            "video_url": master_urls[0],
            "all_urls": hls_urls[:10]
        }

    mp4_urls = re.findall(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', html)
    mp4_urls = [
        u for u in mp4_urls
        if 'banner' not in u.lower()
        and 'storagexhd' not in u.lower()
        and 'ads' not in u.lower()
    ]
    if mp4_urls:
        return {
            "success": True,
            "video_url": mp4_urls[0],
            "all_urls": mp4_urls[:10]
        }

    return {"success": False, "error": "No playable streaming video source detected in page HTML."}


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
