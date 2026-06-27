from flask import Flask
from pyrogram import Client, filters
import re
import threading

app = Flask(__name__)

bot = Client("BypassBot")

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

def run_flask():
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    # START BOT FIRST (IMPORTANT)
    bot.start()

    # THEN RUN FLASK IN THREAD
    threading.Thread(target=run_flask).start()

    # KEEP MAIN THREAD ALIVE
    bot.idle()
