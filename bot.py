import os
import time
from logging import getLogger
from threading import Thread

from flask import Flask
from pyrogram import idle
from pyrogram.errors import FloodWait

from FZBypass import Bypass

app = Flask(__name__)
LOGGER = getLogger(__name__)


@app.get("/")
def home():
    return "FZ Bypass Bot is running", 200


@app.get("/health")
def health():
    return {"ok": True, "service": "fz-bypass-bot"}, 200


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
