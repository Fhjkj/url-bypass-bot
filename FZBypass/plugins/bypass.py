import os
from time import monotonic, time
from html import escape
from pathlib import Path
from asyncio import create_task, gather, sleep as asleep, wait_for
from pyrogram import filters
from pyrogram.filters import command, user
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InputMediaPhoto,
    InputMediaDocument,
)
from pyrogram.enums import MessageEntityType
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, QueryIdInvalid

from FZBypass import Config, Bypass, BOT_START, LOGGER
from FZBypass.core.bypass_checker import direct_link_checker, is_excep_link
from FZBypass.core.dotflix import DotflixResult
from FZBypass.core.gofile import GofileResult
from FZBypass.core.provider_scrapers import ProviderFileResult
from FZBypass.core.bot_utils import AuthChatsTopics, convert_time, BypassFilter
from FZBypass.core.social_media import cleanup_social_media, download_social_media, find_social_urls

BYPASS_TASK_TIMEOUT_SECONDS = max(70, int(os.getenv("BYPASS_TASK_TIMEOUT_SECONDS", "150")))
SOCIAL_MEDIA_TIMEOUT_SECONDS = max(30, int(os.getenv("SOCIAL_MEDIA_TIMEOUT_SECONDS", "120")))
SOCIAL_MAX_FILES = max(1, min(50, int(os.getenv("SOCIAL_MAX_FILES", "20"))))
SOCIAL_SEND_AS_DOCUMENT = os.getenv("SOCIAL_SEND_AS_DOCUMENT", "false").lower() not in {"0", "false", "no", "off"}
SOCIAL_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SOCIAL_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts", ".avi", ".flv"}
SOCIAL_STATUS_EDIT_INTERVAL_SECONDS = 4.0
SOCIAL_PHOTO_CAPTION = os.getenv("SOCIAL_PHOTO_CAPTION", "🎵 TikTok Photos\n\n━━━━━━━━━━━━\n\n⚡ Downloaded via @Bypass0_bot")


async def _upload_progress(current: int, total: int, wait_msg, state: dict[str, float], label: str):
    percent = int(max(0, min(100, current * 100 / total))) if total else 0
    now = monotonic()
    if now < state.get("disabled_until", 0):
        return
    if now - state.get("updated_at", 0) < SOCIAL_STATUS_EDIT_INTERVAL_SECONDS:
        return
    state["percent"] = percent
    state["updated_at"] = now
    try:
        await wait_msg.edit(f"<i>⬆️ Uploading {label}... {percent}%</i>")
    except FloodWait as error:
        state["disabled_until"] = now + max(60, int(getattr(error, "value", 60)))
        LOGGER.warning("Telegram flood limit reached for upload status; pausing edits")
    except Exception:
        pass


async def _send_social_video(message, path: Path, caption: str | None = None, wait_msg=None, upload_state=None):
    upload_kwargs = {}
    if wait_msg is not None:
        upload_kwargs = {"progress": _upload_progress, "progress_args": (wait_msg, upload_state or {}, "video")}
    try:
        return await message.reply_video(str(path), caption=caption, quote=True, supports_streaming=True, **upload_kwargs)
    except Exception as error:
        LOGGER.warning("Telegram video upload failed for %s; retrying as document: %s", path, error)
        document_kwargs = {}
        if wait_msg is not None:
            document_kwargs = {"progress": _upload_progress, "progress_args": (wait_msg, upload_state or {}, "file")}
        return await message.reply_document(str(path), caption=caption, quote=True, **document_kwargs)


async def _send_social_file(message, path: Path, caption: str | None = None, wait_msg=None, upload_state=None):
    """Prefer a rendered photo, but fall back to a document for Telegram-incompatible bytes."""
    progress_kwargs = {}
    if wait_msg is not None:
        progress_kwargs = {"progress": _upload_progress, "progress_args": (wait_msg, upload_state or {}, "photo" if path.suffix.lower() in SOCIAL_PHOTO_EXTENSIONS else "file")}
    if path.suffix.lower() in SOCIAL_PHOTO_EXTENSIONS and not SOCIAL_SEND_AS_DOCUMENT:
        try:
            return await message.reply_photo(str(path), caption=caption, quote=True, **progress_kwargs)
        except Exception as error:
            LOGGER.warning("Telegram photo upload failed for %s; retrying as document: %s", path, error)
    return await message.reply_document(str(path), caption=caption, quote=True, **progress_kwargs)


@Bypass.on_message(command("start"))
async def start_msg(client, message):
    caption = "🌺 <b>Hey, I'm A Bypasser Bot Specially Coded For <a href=\"https://t.me/Bypass0_bot\">@Bypass0_bot</a> ✅</b>"
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Channel", callback_data="start_channel_placeholder")]]
    )
    image_path = Path(Config.START_IMAGE)
    if image_path.is_file():
        await message.reply_photo(
            photo=str(image_path),
            caption=caption,
            quote=True,
            reply_markup=keyboard,
        )
    else:
        await message.reply(caption, quote=True, reply_markup=keyboard)


@Bypass.on_callback_query(filters.regex("^start_channel_placeholder$"))
async def channel_placeholder(_, query):
    await query.answer()


@Bypass.on_message((user(Config.OWNER_ID) | AuthChatsTopics) & filters.regex(r"(?i)https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com|facebook\.com|fb\.watch|instagram\.com)/"))
async def social_media_photos(client, message):
    """Send public TikTok/Facebook media without re-encoding the source files."""
    message_text = message.text or message.caption or ""
    # /bypass and /bp are handled by the generic resolver; do not run this
    # social-media handler a second time for the same Telegram update.
    if message_text.lstrip().lower().startswith(("/bypass", "/bp")):
        return
    urls = find_social_urls(message_text)
    if not urls:
        return

    wait_msg = await message.reply("<i>📷 Downloading original media... 0%</i>", quote=True)
    root = None
    progress = {"percent": 0.0}
    upload_state = {"percent": -1.0, "updated_at": 0.0}
    download_task = create_task(download_social_media(urls[0], progress))
    status_task = create_task(_social_progress_status(wait_msg, progress, download_task))
    try:
        result, root = await wait_for(
            download_task, timeout=SOCIAL_MEDIA_TIMEOUT_SECONDS
        )
        try:
            await wait_msg.edit("<i>📷 Downloading original media... 100%</i>")
        except FloodWait:
            pass
        except Exception:
            pass
        files = result.files[:SOCIAL_MAX_FILES]
        if result.is_photo_post:
            files = [path for path in files if path.suffix.lower() in SOCIAL_PHOTO_EXTENSIONS]
        if not files:
            raise RuntimeError("No media files were found")

        caption = SOCIAL_PHOTO_CAPTION if result.is_photo_post else f"📷 <b>{escape(result.title, quote=True)}</b>\n\n✅ Original source file"
        if SOCIAL_SEND_AS_DOCUMENT and not result.is_photo_post:
            for start in range(0, len(files), 10):
                batch = files[start : start + 10]
                if len(batch) == 1:
                    await _send_social_file(message, batch[0], caption if start == 0 else None, wait_msg, upload_state)
                else:
                    media = [
                        InputMediaDocument(str(path), caption=caption if index == 0 and start == 0 else None)
                        for index, path in enumerate(batch)
                    ]
                    await client.send_media_group(
                        chat_id=message.chat.id,
                        media=media,
                        reply_to_message_id=message.id,
                    )
        elif all(path.suffix.lower() in SOCIAL_PHOTO_EXTENSIONS for path in files) and not SOCIAL_SEND_AS_DOCUMENT:
            for start in range(0, len(files), 10):
                batch = files[start : start + 10]
                if len(batch) == 1:
                    await _send_social_file(message, batch[0], caption if start == 0 else None, wait_msg, upload_state)
                else:
                    media = [
                        InputMediaPhoto(str(path), caption=caption if index == 0 and start == 0 else None)
                        for index, path in enumerate(batch)
                    ]
                    try:
                        await client.send_media_group(
                            chat_id=message.chat.id,
                            media=media,
                            reply_to_message_id=message.id,
                        )
                    except Exception as error:
                        LOGGER.warning("Telegram photo album upload failed; retrying as documents: %s", error)
                        for index, path in enumerate(batch):
                            await _send_social_file(
                                message, path, caption if index == 0 and start == 0 else None, wait_msg, upload_state
                            )
        elif any(path.suffix.lower() in SOCIAL_VIDEO_EXTENSIONS for path in files):
            # Send video files natively like Facebook. Only non-video leftovers
            # use document upload; never wrap a video in an archive-style upload.
            for path in files:
                item_caption = caption if path == files[0] else None
                if path.suffix.lower() in SOCIAL_VIDEO_EXTENSIONS:
                    await _send_social_video(message, path, item_caption, wait_msg, upload_state)
                else:
                    await _send_social_file(message, path, item_caption, wait_msg, upload_state)
        else:
            for path in files:
                await _send_social_file(message, path, caption if path == files[0] else None, wait_msg, upload_state)

        await wait_msg.delete()
    except Exception as error:
        LOGGER.warning("Social media download failed for %s: %s", urls[0], error)
        try:
            await wait_msg.edit(f"❌ Could not download the public media: {escape(str(error), quote=True)}")
        except Exception:
            pass
    finally:
        status_task.cancel()
        if root is not None:
            cleanup_social_media(root)


async def _social_progress_status(wait_msg, progress: dict[str, float], download_task) -> None:
    last_percent = -1
    last_edit = 0.0
    disabled_until = 0.0
    while not download_task.done():
        now = monotonic()
        percent = max(0, min(99, int(progress.get("percent", 0))))
        if percent != last_percent and now >= disabled_until and now - last_edit >= SOCIAL_STATUS_EDIT_INTERVAL_SECONDS:
            try:
                await wait_msg.edit(f"<i>📷 Downloading original media... {percent}%</i>")
                last_percent = percent
                last_edit = now
            except FloodWait as error:
                disabled_until = now + max(60, int(getattr(error, "value", 60)))
                LOGGER.warning("Telegram flood limit reached for download status; pausing edits")
            except Exception:
                pass
        await asleep(SOCIAL_STATUS_EDIT_INTERVAL_SECONDS)


@Bypass.on_message(BypassFilter & (user(Config.OWNER_ID) | AuthChatsTopics))
async def bypass_check(client, message):
    uid = message.from_user.id
    if (reply_to := message.reply_to_message) and (
        reply_to.text is not None or reply_to.caption is not None
    ):
        txt = reply_to.text or reply_to.caption
        entities = reply_to.entities or reply_to.caption_entities
    elif Config.AUTO_BYPASS or len(message.text.split()) > 1:
        txt = message.text
        entities = message.entities
    else:
        return await message.reply("<i>No Link Provided!</i>")

    wait_msg = await message.reply("<i>🔎 Scraping... please wait</i>")
    start = time()

    link, tlinks, no = "", [], 0
    atasks = []
    for enty in entities:
        if enty.type == MessageEntityType.URL:
            link = txt[enty.offset : (enty.offset + enty.length)]
        elif enty.type == MessageEntityType.TEXT_LINK:
            link = enty.url

        if link:
            no += 1
            tlinks.append(link)
            atasks.append(create_task(wait_for(direct_link_checker(link), timeout=BYPASS_TASK_TIMEOUT_SECONDS)))
            link = ""

    ad_domains = (
        "arolinks.com", "gplinks.co", "vplink.in", "short4cash.com",
        "vipshort.in", "adsfly", "adrinolinks", "archive.toonworld4all.me",
        "softurl.in", "surajitlinks.in", "surajitmodz.", "djbasskingg.com",
    )
    operation = "🔗 Bypassing ads..." if any(any(domain in item.lower() for domain in ad_domains) for item in tlinks) else "🔎 Scraping..."
    if operation != "🔎 Scraping...":
        try:
            await wait_for(wait_msg.edit(f"<i>{operation} please wait</i>"), timeout=10)
        except Exception:
            pass
    try:
        completed_tasks = await wait_for(
            gather(*atasks, return_exceptions=True), timeout=BYPASS_TASK_TIMEOUT_SECONDS + 10
        )
    except Exception as error:
        completed_tasks = [error for _ in tlinks]

    parse_data = []
    for result, link in zip(completed_tasks, tlinks):
        source = escape(str(link), quote=True)
        if isinstance(result, BaseException):
            error_text = str(result).strip() or result.__class__.__name__
            bypassed = f"❌ {escape(error_text, quote=True)}"
        elif isinstance(result, GofileResult):
            filename = escape(result.filename, quote=True)
            total_size = escape(result.total_size, quote=True)
            download_links = " | ".join(
                f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'
                for label, url in result.links
            )
            bypassed = (
                f"📚 <b>File Name :-</b> {filename}\n"
                f"│\n├ 💾 <b>Total Size :-</b> {total_size}\n"
                f"│\n├ 🧩 <b>Files :-</b> {result.file_count}\n"
                f"│\n└ 🔗 <b>Links :-</b> {download_links}"
            )
        elif isinstance(result, DotflixResult):
            filename = escape(result.filename, quote=True)
            size = escape(result.size, quote=True)
            provider_links = " | ".join(
                f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'
                for label, url in result.providers
            )
            bypassed = (
                f"📚 <b>File Name :-</b>\n{filename}\n"
                f"│\n├ 💾 <b>Size :-</b> {size}\n"
                f"│\n└ 🔗 <b>Links :-</b> {provider_links}"
            )
        elif isinstance(result, ProviderFileResult):
            filename = escape(result.filename, quote=True)
            size = escape(result.size, quote=True)
            provider_links = " | ".join(
                f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'
                for label, url in result.links
            )
            bypassed = (
                f"📚 <b>File Name :-</b> {filename}\n"
                f"│\n├ 💾 <b>Size :-</b> {size}\n"
                f"│\n└ 🔗 <b>Links :-</b> {provider_links}"
            )
        elif isinstance(result, list):
            links = [str(item) for item in result]
            bypassed = "\n".join(f"✅ <a href=\"{escape(item, quote=True)}\">{escape(item)}</a>" for item in links)
        elif is_excep_link(link):
            bypassed = str(result)
        else:
            result_text = escape(str(result), quote=True)
            bypassed = f"✅ <a href=\"{result_text}\">{result_text}</a>"
        card_kind = "gofile" if isinstance(result, GofileResult) else "dotflix" if isinstance(result, DotflixResult) else "provider" if isinstance(result, ProviderFileResult) else ""
        parse_data.append((source, bypassed, card_kind))

    end = time()
    elapsed = f"{end - start:.0f} seconds"
    cards = []
    for source, bypassed, card_kind in parse_data:
        if card_kind:
            cards.append(
                f"<blockquote>/bypass <a href=\"{source}\">{source}</a></blockquote>\n"
                f"<blockquote>{bypassed}</blockquote>\n\n"
                "<blockquote>━━━━━━━✦✗✦━━━━━━━</blockquote>\n\n"
                "<blockquote><b>Powered By <a href=\"https://t.me/Bypass0_bot\">@Bypass0_bot</a></b></blockquote>"
            )
        else:
            cards.append(
                "<blockquote>-\n"
                f"/bypass <a href=\"{source}\">{source}</a></blockquote>\n"
                "<blockquote><b>Original Link :</b></blockquote>\n"
                f"<blockquote>✅ <a href=\"{source}\">{source}</a></blockquote>\n"
                "<blockquote><b>Bypassed Link :</b></blockquote>\n"
                f"<blockquote>{bypassed}</blockquote>\n"
                f"<blockquote><b>Time Taken : {escape(elapsed)}</b></blockquote>\n\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "<blockquote><b>Powered By <a href=\"https://t.me/Bypass0_bot\">@Bypass0_bot</a></b></blockquote>"
            )
    tg_txt = "\n\n".join(cards)
    try:
        if len(tg_txt) > 4000:
            chunks = [tg_txt[index : index + 3900] for index in range(0, len(tg_txt), 3900)]
            await wait_for(message.reply(chunks[0], reply_to_message_id=message.id, parse_mode=ParseMode.HTML, disable_web_page_preview=True), timeout=15)
            for chunk in chunks[1:]:
                await wait_for(message.reply(chunk, reply_to_message_id=message.id, parse_mode=ParseMode.HTML), timeout=15)
                await asleep(0.5)
        elif tg_txt:
            await wait_for(message.reply(tg_txt, reply_to_message_id=message.id, parse_mode=ParseMode.HTML, disable_web_page_preview=True), timeout=15)
        else:
            await wait_for(message.reply("<i>No links found.</i>", reply_to_message_id=message.id), timeout=15)
        try:
            await wait_for(wait_msg.delete(), timeout=10)
        except Exception:
            pass
    except Exception as error:
        fallback = "\n\n".join(
            f"{source}\n{bypassed.replace('<', '').replace('>', '')}" for source, bypassed, _ in parse_data
        ) or "No links found."
        try:
            await wait_for(wait_msg.edit(f"Scrape completed, but formatted output failed: {escape(str(error))}\n\n{fallback[:3500]}"), timeout=15)
        except Exception:
            await wait_for(message.reply(f"Scrape completed.\n\n{fallback[:3500]}", reply_to_message_id=message.id), timeout=15)


@Bypass.on_message(command("log") & user(Config.OWNER_ID))
async def send_logs(client, message):
    await message.reply_document("log.txt", quote=True)


@Bypass.on_inline_query()
async def inline_query(client, query):
    answers = []
    string = query.query.lower()
    if string.startswith("!bp "):
        link = string.strip("!bp ")
        start = time()
        try:
            bp_link = await direct_link_checker(link, True)
            end = time()

            if not is_excep_link(link):
                bp_link = (
                    f"┎ <b>Source Link:</b> {link}\n┃\n┖ <b>Bypass Link:</b> {bp_link}"
                )
            answers.append(
                InlineQueryResultArticle(
                    title="✅️ Bypass Link Success !",
                    input_message_content=InputTextMessageContent(
                        f"{bp_link}\n\n✎﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏\n\n🧭 <b>Took Only <code>{convert_time(end - start)}</code></b>",
                        disable_web_page_preview=True,
                    ),
                    description=f"Bypass via !bp {link}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "Bypass Again",
                                    switch_inline_query_current_chat="!bp ",
                                )
                            ]
                        ]
                    ),
                )
            )
        except Exception as e:
            bp_link = f"<b>Bypass Error:</b> {e}"
            end = time()

            answers.append(
                InlineQueryResultArticle(
                    title="❌️ Bypass Link Error !",
                    input_message_content=InputTextMessageContent(
                        f"┎ <b>Source Link:</b> {link}\n┃\n┖ {bp_link}\n\n✎﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏\n\n🧭 <b>Took Only <code>{convert_time(end - start)}</code></b>",
                        disable_web_page_preview=True,
                    ),
                    description=f"Bypass via !bp {link}",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "Bypass Again",
                                    switch_inline_query_current_chat="!bp ",
                                )
                            ]
                        ]
                    ),
                )
            )

    else:
        answers.append(
            InlineQueryResultArticle(
                title="♻️ Bypass Usage: In Line",
                input_message_content=InputTextMessageContent(
                    """<b><i>FZ Bypass Bot!</i></b>
    
    <i>A Powerful Elegant Multi Threaded Bot written in Python... which can Bypass Various Shortener Links, Scrape links, and More ... </i>
    
🎛 <b>Inline Use :</b> !bp [Single Link]""",
                ),
                description="Bypass via !bp [link]",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "FZ Channel", url="https://t.me/FXTorrentz"
                            ),
                            InlineKeyboardButton(
                                "Try Bypass", switch_inline_query_current_chat="!bp "
                            ),
                        ]
                    ]
                ),
            )
        )
    try:
        await query.answer(results=answers, cache_time=0)
    except QueryIdInvalid:
        pass
