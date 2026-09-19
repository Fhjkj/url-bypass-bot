import os
import time
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
