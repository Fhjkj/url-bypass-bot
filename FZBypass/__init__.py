from os import getenv
from time import time
from dotenv import load_dotenv
from logging import getLogger, FileHandler, StreamHandler, INFO, ERROR, basicConfig

basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)

getLogger("pyrogram").setLevel(ERROR)
LOGGER = getLogger(__name__)

load_dotenv("config.env", override=True)
BOT_START = time()


class Config:
    BOT_TOKEN = getenv("BOT_TOKEN", "")
    API_HASH = getenv("API_HASH", "")
    API_ID = getenv("API_ID", "")

    if not BOT_TOKEN or not API_HASH or not API_ID:
        LOGGER.warning("Telegram credentials not set; running in web-only mode")

    AUTO_BYPASS = getenv("AUTO_BYPASS", "False").lower() == "true"
    AUTH_CHATS = getenv("AUTH_CHATS", "").split()
    OWNER_ID = int(getenv("OWNER_ID", 0))
    DIRECT_INDEX = getenv("DIRECT_INDEX", "").rstrip("/")
    LARAVEL_SESSION = getenv("LARAVEL_SESSION", "")
    XSRF_TOKEN = getenv("XSRF_TOKEN", "")
    GDTOT_CRYPT = getenv("GDTOT_CRYPT", "")
    DRIVEFIRE_CRYPT = getenv("DRIVEFIRE_CRYPT", "")
    HUBDRIVE_CRYPT = getenv("HUBDRIVE_CRYPT", "")
    KATDRIVE_CRYPT = getenv("KATDRIVE_CRYPT", "")
    TERA_COOKIE = getenv("TERA_COOKIE", "")
    START_IMAGE = getenv("START_IMAGE", "start_banner.jpg")


# Only initialize pyrogram if credentials are available
if Config.BOT_TOKEN and Config.API_HASH and Config.API_ID:
    from pyrogram import Client
    from pyrogram.enums import ParseMode

    Bypass = Client(
        "FZ",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        plugins=dict(root="FZBypass/plugins"),
        parse_mode=ParseMode.HTML,
    )
else:
    Bypass = None