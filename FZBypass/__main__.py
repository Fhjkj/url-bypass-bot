from FZBypass import Bypass, LOGGER
from FZBypass.core.sudo import load_sudo_users
from pyrogram import idle
from pyrogram.filters import command
from os import path as ospath, execl
from asyncio import create_subprocess_exec
from sys import executable
from FZBypass.core.bot_utils import OwnerOrSudo


@Bypass.on_message(command("restart") & OwnerOrSudo)
async def restart(client, message):
    restart_message = await message.reply("<i>Restarting...</i>")
    await (await create_subprocess_exec("python3", "update.py")).wait()
    with open(".restartmsg", "w") as f:
        f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")
    try:
        execl(executable, executable, "-m", "FZBypass")
    except Exception:
        execl(executable, executable, "-m", "FZBypassBot/FZBypass")


async def restart():
    if ospath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
        try:
            await Bypass.edit_message_text(
                chat_id=chat_id, message_id=msg_id, text="<i>Restarted !</i>"
            )
        except Exception as e:
            LOGGER.error(e)


load_sudo_users()
Bypass.start()
LOGGER.info("FZ Bot Started!")
Bypass.loop.run_until_complete(restart())
idle()
Bypass.stop()
