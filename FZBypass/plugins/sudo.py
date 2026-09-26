"""Owner-only commands for managing persistent sudo users."""
from asyncio import to_thread
from pyrogram.filters import command, user

from FZBypass import Bypass, Config
from FZBypass.core.sudo import add_sudo_user, load_sudo_users, remove_sudo_user


def _parse_user_id(message) -> int | None:
    args = getattr(message, "command", None) or []
    if len(args) != 2:
        return None
    try:
        user_id = int(args[1])
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


@Bypass.on_message(command("addsudo") & user(Config.OWNER_ID))
async def add_sudo(_, message):
    user_id = _parse_user_id(message)
    if user_id is None:
        return await message.reply("Usage: <code>/addsudo telegram_id</code>")
    if user_id == Config.OWNER_ID:
        return await message.reply("You are already the bot owner.")

    # Refresh first so users added while the bot was offline remain authorized.
    await to_thread(load_sudo_users)
    try:
        created = await to_thread(add_sudo_user, user_id, message.from_user.id)
    except Exception as error:
        return await message.reply(
            f"Could not save sudo access to MongoDB ({type(error).__name__}). "
            "Check that MONGODB_URI is configured and reachable."
        )
    status = "Added" if created else "Already had"
    await message.reply(f"{status} sudo access for <code>{user_id}</code>.")


@Bypass.on_message(command("rmsudo") & user(Config.OWNER_ID))
async def remove_sudo(_, message):
    user_id = _parse_user_id(message)
    if user_id is None:
        return await message.reply("Usage: <code>/rmsudo telegram_id</code>")
    if user_id == Config.OWNER_ID:
        return await message.reply("The bot owner cannot be removed from sudo access.")

    await to_thread(load_sudo_users)
    try:
        removed = await to_thread(remove_sudo_user, user_id)
    except Exception as error:
        return await message.reply(
            f"Could not update sudo access in MongoDB ({type(error).__name__}). "
            "Check that MONGODB_URI is configured and reachable."
        )
    status = "Removed" if removed else "No sudo entry found for"
    await message.reply(f"{status} <code>{user_id}</code>.")
