from flask import Flask
from pyrogram import Client, filters
import re
import threading
from config import API_ID, API_HASH, BOT_TOKEN

app = Flask(__name__)

bot = Client(
    "BypassBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

URL_REGEX = r"(https?://[^\s]+)"

def bypass_url(url):
    return url  # placeholder

@app.route("/")
def home():
    return "Bot is running"

@bot.on_message(filters.private & filters.command("start"))
async def start(_, message):
    await message.reply_text(
        "👋 Welcome!\nSend me a link."
    )

@bot.on_message(filters.private & filters.text)
async def bypass(_, message):
    match = re.search(URL_REGEX, message.text)

    if not match:
        await message.reply_text("❌ Invalid URL")
        return

    url = match.group(0)
    final = bypass_url(url)

    await message.reply_text(f"Bypassed:\n{final}")

def run_bot():
    bot.run()

threading.Thread(target=run_bot).start()

app.run(host="0.0.0.0", port=10000)
