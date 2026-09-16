from time import time
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
)
from pyrogram.enums import MessageEntityType
from pyrogram.enums import ParseMode
from pyrogram.errors import QueryIdInvalid

from FZBypass import Config, Bypass, BOT_START
from FZBypass.core.bypass_checker import direct_link_checker, is_excep_link
from FZBypass.core.dotflix import DotflixResult
from FZBypass.core.gofile import GofileResult
from FZBypass.core.provider_scrapers import ProviderFileResult
from FZBypass.core.bot_utils import AuthChatsTopics, convert_time, BypassFilter


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
            atasks.append(create_task(wait_for(direct_link_checker(link), timeout=60)))
            link = ""

    ad_domains = (
        "arolinks.com", "gplinks.co", "vplink.in", "short4cash.com",
        "vipshort.in", "adsfly", "adrinolinks", "archive.toonworld4all.me",
    )
    operation = "🔗 Bypassing ads..." if any(any(domain in item.lower() for domain in ad_domains) for item in tlinks) else "🔎 Scraping..."
    if operation != "🔎 Scraping...":
        try:
            await wait_for(wait_msg.edit(f"<i>{operation} please wait</i>"), timeout=10)
        except Exception:
            pass
    completed_tasks = await gather(*atasks, return_exceptions=True)

    parse_data = []
    for result, link in zip(completed_tasks, tlinks):
        source = escape(str(link), quote=True)
        if isinstance(result, Exception):
            bypassed = f"❌ {escape(str(result), quote=True)}"
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
                f"<blockquote>B <a href=\"{source}\">{source}</a></blockquote>\n"
                f"<blockquote>{bypassed}</blockquote>\n\n"
                "<blockquote>━━━━━━━✦✗✦━━━━━━━</blockquote>\n\n"
                "<blockquote><b>Powered By <a href=\"https://t.me/Bypass0_bot\">@Bypass0_bot</a></b> ❞</blockquote>"
            )
        else:
            cards.append(
                "<blockquote>-\n"
                f"/bypass <a href=\"{source}\">{source}</a></blockquote>\n"
                "<blockquote><b>Original Link : </b>❞</blockquote>\n"
                f"<blockquote>✅ <a href=\"{source}\">{source}</a></blockquote>\n"
                "<blockquote><b>Bypassed Link : </b>❞</blockquote>\n"
                f"<blockquote>{bypassed}</blockquote>\n"
                f"<blockquote><b>Time Taken : {escape(elapsed)}</b> ❞</blockquote>\n\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "<blockquote><b>Powered By <a href=\"https://t.me/Bypass0_bot\">@Bypass0_bot</a></b> ❞</blockquote>"
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
