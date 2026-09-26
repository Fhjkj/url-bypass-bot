from pyrogram.filters import create
from pyrogram.enums import ChatType, MessageEntityType
from re import search, match, escape, finditer
from requests import get as rget
from urllib.parse import urlparse, parse_qs
from FZBypass import Config
from FZBypass.core.sudo import authorized_group_override, is_sudo_user


async def auth_topic(_, __, message):
    override = authorized_group_override(message.chat.id)
    if override is False:
        return False
    if override is True:
        return True
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


async def bypass_chat_access(_, client, message):
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        if authorized_group_override(message.chat.id) is False:
            return False
    return await owner_or_sudo(_, client, message) or await auth_topic(_, client, message)


BypassChatAccess = create(bypass_chat_access)


SOCIAL_MEDIA_RE = r"(?i)https?://(?:(?:www|m)\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com|facebook\.com|fb\.watch|instagram\.com)/"
URL_RE = r"https?://[^\s<>]+"
AD_HOST_MARKERS = (
    "arolinks", "gplinks", "vplink", "short4cash", "vipshort", "adsfly",
    "adrinolinks", "surajitlinks", "djbasskingg", "try2link", "gyanilinks",
    "gtlinks", "anlinks", "ronylink", "evolinks", "tnshort", "xpshort",
    "bdnewsx", "techymozo", "lolshort", "onepagelink", "moneykamalo",
    "droplink", "tinyfy", "krownlinks", "du-link", "dulink", "indianshortner",
    "easysky", "tnlink", "link4earn", "shortingly", "short2url", "urlsopen",
    "mdiskshortner", "linkpays", "sklinks", "link1s", "tulinks", "vipurl",
    "indyshare", "linkyearn", "earn4link", "linksly", "rocklinks",
    "mplaylink", "shrinke", "urlspay", "tnvalue", "sxslink", "moneycase",
    "urllinkshort", "dtglinks", "v2links", "kpslink", "tamizhmasters",
    "tglink", "pandaznetwork", "url4earn", "ez4short", "dalink", "omnifly",
    "sheralinks", "bindaaslinks", "viplinks", "shrinkforearn", "bringlifes",
    "linkfly", "earn2me", "vplinks", "narzolinks", "earn2short", "instantearn",
    "linkjust", "pdiskshortener", "publicearn", "modijiurl", "linkshortx",
    "shorito", "ziplinker", "ouo", "shareus", "shrs", "linkvertise", "rslinks",
    "appurl", "surl", "thinfi", "justpaste", "linksxyz", "babylinks",
)
PROVIDER_HOST_MARKERS = (
    "sharer", "hubcloud", "hubdrive", "katdrive", "drivefire", "filepress",
    "filebee", "appdrive", "gdflix", "pressbee", "onlystream", "toonworld4all",
    "cinevood", "skymovieshd", "kayoanime", "sharespark", "terabox", "mediafire",
    "gofile", "dotflix",
)


def _is_bypass_command(client, text: str | None) -> bool:
    if not text:
        return False
    username = getattr(getattr(client, "me", None), "username", None)
    suffix = rf"(?:@{escape(username)})?" if username else ""
    return bool(match(rf"^/(?:bypass|bp){suffix}(?:\s|$)", text, flags=2))


def _has_links(message) -> bool:
    if any(
        entity.type in {MessageEntityType.TEXT_LINK, MessageEntityType.URL}
        for entity in (message.entities or message.caption_entities or [])
    ):
        return True
    return bool(search(URL_RE, message.text or message.caption or ""))


def extract_message_links(text: str, entities=None) -> list[str]:
    """Extract visible and hidden Telegram links once, preserving message order."""
    links = []
    for entity in entities or []:
        if entity.type == MessageEntityType.TEXT_LINK:
            link = entity.url
        else:
            continue
        link = link.rstrip(".,;:!?)]}>")
        if link:
            links.append((entity.offset, link))
    links.extend(
        (match.start(), match.group(0).rstrip(".,;:!?)]}>"))
        for match in finditer(URL_RE, text)
    )
    unique = []
    seen = set()
    for _, link in sorted(links, key=lambda item: item[0]):
        key = link.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(link)
    return unique


def classify_link(link: str) -> str:
    """Classify a link before choosing exactly one processing path."""
    if search(SOCIAL_MEDIA_RE, link):
        return "social_media"
    host = (urlparse(link).hostname or "").lower().removeprefix("www.")
    if any(marker in host for marker in AD_HOST_MARKERS):
        return "ad_shortener"
    if any(marker in host for marker in PROVIDER_HOST_MARKERS):
        return "sharing_or_movie"
    return "generic_resolver"


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
