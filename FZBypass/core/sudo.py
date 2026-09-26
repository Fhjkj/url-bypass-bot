"""Persistent bot sudo-user storage backed by MongoDB."""
from pymongo import MongoClient
from pymongo.errors import ConfigurationError

from FZBypass import Config, LOGGER

_COLLECTION = None
_CLIENT = None
_SUDO_USERS: set[int] = set()


def _collection():
    global _CLIENT, _COLLECTION
    if _COLLECTION is not None:
        return _COLLECTION
    if not Config.MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not configured")

    client = MongoClient(
        Config.MONGODB_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    client.admin.command("ping")
    if Config.MONGODB_DATABASE:
        database = client[Config.MONGODB_DATABASE]
    else:
        try:
            database = client.get_default_database()
        except ConfigurationError:
            database = client["fzbypass"]
    _CLIENT = client
    _COLLECTION = database["sudo_users"]
    return _COLLECTION


def load_sudo_users() -> set[int]:
    """Load authorized user IDs once at startup; the bot still starts if DB is down."""
    if not Config.MONGODB_URI:
        LOGGER.warning("MONGODB_URI is not configured; persistent sudo commands are disabled")
        return set(_SUDO_USERS)
    try:
        loaded_users = {
            int(row["_id"]) for row in _collection().find({}, {"_id": 1})
        }
        _SUDO_USERS.clear()
        _SUDO_USERS.update(loaded_users)
        LOGGER.info("Loaded %s persistent sudo user(s)", len(_SUDO_USERS))
    except Exception as error:
        LOGGER.error("Could not load sudo users from MongoDB (%s)", type(error).__name__)
    return set(_SUDO_USERS)


def is_sudo_user(user_id: int | None) -> bool:
    return user_id is not None and int(user_id) in _SUDO_USERS


def add_sudo_user(user_id: int, added_by: int) -> bool:
    """Persist an ID before making it effective in this process."""
    user_id = int(user_id)
    if user_id <= 0:
        raise ValueError("Telegram user ID must be a positive integer")
    result = _collection().update_one(
        {"_id": user_id},
        {"$setOnInsert": {"added_by": int(added_by)}},
        upsert=True,
    )
    _SUDO_USERS.add(user_id)
    return result.upserted_id is not None


def remove_sudo_user(user_id: int) -> bool:
    """Remove persisted authorization and revoke it immediately in this process."""
    user_id = int(user_id)
    result = _collection().delete_one({"_id": user_id})
    _SUDO_USERS.discard(user_id)
    return result.deleted_count > 0
