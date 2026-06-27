from flask import Flask
from pyrogram import Client, filters
import re
import os

app = Flask(__name__)

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Client(
    "BypassBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

URL_REGEX = r"(https?://[^\s]+)"

@app.route("/")
def home():
    return "Bot is running"

@bot.on_message(filters.private & filters.command("start"))
async def start(_, message):
    await message.reply("Hi!")

@bot.on_message(filters.private & filters.text)
async def handler(_, message):
    match = re.search(URL_REGEX, message.text)
    if match:
        await message.reply(match.group(0))

if __name__ == "__main__":
    from threading import Thread

    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    bot.run()
