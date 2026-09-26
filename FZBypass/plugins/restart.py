"""Owner/sudo command to restart the bot process."""
from pyrogram.filters import command

from FZBypass import Bypass
from FZBypass.core.bot_utils import OwnerOrSudo
from FZBypass.core.restart import restart_process


@Bypass.on_message(command("restart") & OwnerOrSudo)
async def restart_bot(_, message):
    await restart_process(message)
