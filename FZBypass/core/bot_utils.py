from pyrogram.filters import create
from pyrogram.enums import ChatType, MessageEntityType
from re import search, match, escape
from requests import get as rget
from urllib.parse import urlparse, parse_qs
from FZBypass import Config
from FZBypass.core.sudo import is_sudo_user


async def auth_topic(_, __, message):
    for chat in Config.AUTH_CHATS:
        if ":" in chat:
            chat_id, topic_id = chat.split(":")
            if (
                int(chat_id) == message.chat.id
                and message.is_topic_message
                and message.topics
                and message.topics.id == int(topic_id)
            ):
                return True
        elif int(chat) == message.chat.id:
            return True
    return False


AuthChatsTopics = create(auth_topic)


async def owner_or_sudo(_, __, message):
    user_id = message.from_user.id if message.from_user else None
    return user_id == Config.OWNER_ID or is_sudo_user(user_id)


OwnerOrSudo = create(owner_or_sudo)


SOCIAL_MEDIA_RE = r"(?i)https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com|facebook\.com|fb\.watch|instagram\.com)/"


def _is_bypass_command(client, text: str | None) -> bool:
    if not text:
        return False
    username = getattr(getattr(client, "me", None), "username", None)
    suffix = rf"(?:@{escape(username)})?" if username else ""
    return bool(match(rf"^/(?:bypass|bp){suffix}(?:\s|$)", text, flags=2))


def _has_links(message) -> bool:
    return any(
        entity.type in {MessageEntityType.TEXT_LINK, MessageEntityType.URL}
        for entity in (message.entities or message.caption_entities or [])
    )


def _has_social_link(message) -> bool:
    text = message.text or message.caption or ""
    if search(SOCIAL_MEDIA_RE, text):
        return True
    reply = message.reply_to_message
    if reply:
        return bool(search(SOCIAL_MEDIA_RE, reply.text or reply.caption or ""))
    return False


async def auto_bypass(_, c, message):
    text = message.text or message.caption or ""
    command = _is_bypass_command(c, text)
    chat_type = message.chat.type
    is_group = chat_type in {ChatType.GROUP, ChatType.SUPERGROUP}
    is_private = chat_type == ChatType.PRIVATE

    if is_group:
        # Never auto-run links from group chatter. A group request must be
        # explicit, and supported social links are handled by one other handler.
        return command and not _has_social_link(message)
    if is_private:
        # Private messages need no command. Social links belong exclusively to
        # the media downloader so AUTO_BYPASS cannot start a second job.
        if _has_social_link(message):
            return False
        return command or _has_links(message)
    return False


async def social_media_message(_, c, message):
    if not _has_social_link(message):
        return False
    chat_type = message.chat.type
    if chat_type == ChatType.PRIVATE:
        return True
    if chat_type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return _is_bypass_command(c, message.text or message.caption or "")
    return False


BypassFilter = create(auto_bypass)
SocialMediaFilter = create(social_media_message)


def get_gdriveid(link):
    if "folders" in link or "file" in link:
        res = search(
            r"https:\/\/drive\.google\.com\/(?:drive(.*?)\/folders\/|file(.*?)?\/d\/)([-\w]+)",
            link,
        )
        return res.group(3)
    parsed = urlparse(link)
    return parse_qs(parsed.query)["id"][0]


def get_dl(link, direct_mode=False):
    if direct_mode and not Config.DIRECT_INDEX:
        return "No Direct Index Added !"
    try:
        return rget(
            f"{Config.DIRECT_INDEX}/generate.aspx?id={get_gdriveid(link)}"
        ).json()["link"]
    except:
        return f"{Config.DIRECT_INDEX}/direct.aspx?id={get_gdriveid(link)}"


def convert_time(seconds):
    mseconds = seconds * 1000
    periods = [("d", 86400000), ("h", 3600000), ("m", 60000), ("s", 1000), ("ms", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if mseconds >= period_seconds:
            period_value, mseconds = divmod(mseconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    if result == "":
        return "0ms"
    return result
