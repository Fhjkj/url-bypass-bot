import os

def must_get(name):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing env var: {name}")
    return value.strip()

API_ID = int(must_get("API_ID"))
API_HASH = must_get("API_HASH")
BOT_TOKEN = must_get("BOT_TOKEN")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
