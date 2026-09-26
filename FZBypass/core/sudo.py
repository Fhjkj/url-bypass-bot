"""Persistent bot sudo-user storage backed by MongoDB."""
from pymongo import MongoClient
from pymongo.errors import ConfigurationError

from FZBypass import Config, LOGGER

_COLLECTION = None
_GROUP_COLLECTION = None
_CLIENT = None
_SUDO_USERS: set[int] = set()
_AUTHORIZED_GROUPS: dict[int, bool] = {}


def _database():
    global _CLIENT
    if _CLIENT is not None:
        if Config.MONGODB_DATABASE:
            return _CLIENT[Config.MONGODB_DATABASE]
        try:
            return _CLIENT.get_default_database()
        except ConfigurationError:
            return _CLIENT["fzbypass"]
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
    return database


def _collection():
    global _COLLECTION
    if _COLLECTION is None:
        _COLLECTION = _database()["sudo_users"]
    return _COLLECTION


def _group_collection():
    global _GROUP_COLLECTION
    if _GROUP_COLLECTION is None:
        _GROUP_COLLECTION = _database()["authorized_groups"]
    return _GROUP_COLLECTION


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


def load_authorized_groups() -> set[int]:
    """Restore group authorization from MongoDB without blocking bot startup."""
    if not Config.MONGODB_URI:
        LOGGER.warning("MONGODB_URI is not configured; persistent group authorization is disabled")
        return {chat_id for chat_id, allowed in _AUTHORIZED_GROUPS.items() if allowed}
    try:
        loaded_groups = {
            int(row["_id"]): bool(row.get("allowed", True))
            for row in _group_collection().find({}, {"_id": 1, "allowed": 1})
        }
        _AUTHORIZED_GROUPS.clear()
        _AUTHORIZED_GROUPS.update(loaded_groups)
        count = sum(_AUTHORIZED_GROUPS.values())
        LOGGER.info("Loaded %s persistent authorized group(s)", count)
    except Exception as error:
        LOGGER.error("Could not load authorized groups from MongoDB (%s)", type(error).__name__)
    return {chat_id for chat_id, allowed in _AUTHORIZED_GROUPS.items() if allowed}


def is_sudo_user(user_id: int | None) -> bool:
    return user_id is not None and int(user_id) in _SUDO_USERS


def authorized_group_override(chat_id: int | None) -> bool | None:
    """Return a persisted allow/deny override, or None for config fallback."""
    return _AUTHORIZED_GROUPS.get(int(chat_id)) if chat_id is not None else None


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


def add_authorized_group(chat_id: int, added_by: int) -> bool:
    """Persist a Telegram group/supergroup ID as an authorized chat."""
    chat_id = int(chat_id)
    if chat_id >= 0:
        raise ValueError("A group or supergroup ID must be negative")
    result = _group_collection().update_one(
        {"_id": chat_id},
        {"$set": {"allowed": True, "changed_by": int(added_by)}},
        upsert=True,
    )
    created = result.upserted_id is not None
    _AUTHORIZED_GROUPS[chat_id] = True
    return created or bool(result.modified_count)


def remove_authorized_group(chat_id: int) -> bool:
    """Remove a group's persisted authorization and revoke it immediately."""
    chat_id = int(chat_id)
    if chat_id >= 0:
        raise ValueError("A group or supergroup ID must be negative")
    result = _group_collection().update_one(
        {"_id": chat_id},
        {"$set": {"allowed": False}},
        upsert=True,
    )
    changed = result.upserted_id is not None or bool(result.modified_count)
    _AUTHORIZED_GROUPS[chat_id] = False
    return changed
