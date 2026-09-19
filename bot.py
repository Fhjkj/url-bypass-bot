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


@app.get("/")
def home():
    return "FZ Bypass Bot is running", 200


@app.get("/health")
def health():
    return {"ok": True, "service": "fz-bypass-bot"}, 200


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
            break
        except FloodWait as exc:
            wait_seconds = max(int(getattr(exc, "value", 60)), 60)
            LOGGER.error(
                "Telegram FloodWait during startup; keeping health server alive and "
                "retrying in %s seconds.",
                wait_seconds,
            )
            time.sleep(wait_seconds)
    try:
        idle()
    finally:
        Bypass.stop()