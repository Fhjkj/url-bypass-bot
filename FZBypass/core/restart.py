"""Restart helpers shared by every bot launcher."""
from os import execv
from pathlib import Path
from sys import executable, orig_argv, argv

from FZBypass import Bypass, LOGGER

_RESTART_STATE = Path(".restartmsg")


async def restart_process(message) -> None:
    """Save a notice, then re-execute this bot with its original launch command."""
    notice = await message.reply("<i>Restarting bot...</i>")
    _RESTART_STATE.write_text(f"{notice.chat.id}\n{notice.id}\n")
    launch_args = list(orig_argv[1:]) if orig_argv else list(argv)
    try:
        execv(executable, [executable, *launch_args])
    except Exception:
        _RESTART_STATE.unlink(missing_ok=True)
        LOGGER.exception("Bot restart failed")
        await notice.edit("❌ Restart failed. Check the bot logs.")


async def notify_restart() -> None:
    """Update the previous restart notice after Telegram reconnects."""
    if not _RESTART_STATE.is_file():
        return
    try:
        chat_id, message_id = map(int, _RESTART_STATE.read_text().splitlines()[:2])
        await Bypass.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="<i>Bot restarted successfully.</i>",
        )
    except Exception:
        LOGGER.exception("Could not update the restart status message")
    finally:
        _RESTART_STATE.unlink(missing_ok=True)
