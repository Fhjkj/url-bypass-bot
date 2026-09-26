from FZBypass import Bypass, LOGGER
from FZBypass.core.sudo import load_authorized_groups, load_sudo_users
from FZBypass.core.restart import notify_restart
from pyrogram import idle
load_sudo_users()
load_authorized_groups()
Bypass.start()
LOGGER.info("FZ Bot Started!")
Bypass.loop.run_until_complete(notify_restart())
idle()
Bypass.stop()
