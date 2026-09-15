from threading import Thread

from flask import Flask
from pyrogram import idle

from FZBypass import Bypass

app = Flask(__name__)


@app.get("/")
def home():
    return "FZ Bypass Bot is running", 200


@app.get("/health")
def health():
    return {"ok": True, "service": "fz-bypass-bot"}, 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    Thread(target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False), daemon=True).start()
    Bypass.start()
    idle()
    Bypass.stop()
