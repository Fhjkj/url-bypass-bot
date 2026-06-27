from pyrogram import Client, filters
import re
import requests
from config import API_ID, API_HASH, BOT_TOKEN

app = Client(
    "BypassBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

URL_REGEX = r"(https?://[^\s]+)"

def bypass_url(url):
    # Placeholder for bypass logic
    return url

@app.on_message(filters.private & filters.command("start"))
async def start(_, message):
    await message.reply_text(
        "👋 Welcome!\n\n"
        "Send me a supported shortlink and I'll try to bypass it."
    )

@app.on_message(filters.private & filters.text)
async def bypass(_, message):
    match = re.search(URL_REGEX, message.text)

    if not match:
        await message.reply_text("❌ Please send a valid URL.")
        return

    url = match.group(0)

    try:
        final = bypass_url(url)

        text = f"""
**Original Link**
{url}

**Bypassed Link**
{final}

⏱ Time Taken: Instant
"""

        await message.reply_text(
            text,
            disable_web_page_preview=True
        )

    except Exception as e:
        await message.reply_text(f"❌ Error:\n`{e}`")

app.run()
