from time import time
from html import escape
from pathlib import Path
from asyncio import create_task, gather, sleep as asleep
from pyrogram.filters import command, user
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from pyrogram.enums import MessageEntityType
from pyrogram.errors import QueryIdInvalid

from FZBypass import Config, Bypass, BOT_START
from FZBypass.core.bypass_checker import direct_link_checker, is_excep_link
from FZBypass.core.bot_utils import AuthChatsTopics, convert_time, BypassFilter


@Bypass.on_message(command("start"))
async def start_msg(client, message):
    caption = "🌺 <b>Hey, I'm A Bypasser Bot Specially Coded For <a href=\"https://t.me/nickupdates\">@nickupdates</a> ✅</b>"
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Channel", url=Config.CHANNEL_URL)]]
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

    wait_msg = await message.reply("<i>Bypassing...</i>")
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
            atasks.append(create_task(direct_link_checker(link)))
            link = ""

    completed_tasks = await gather(*atasks, return_exceptions=True)

    parse_data = []
    for result, link in zip(completed_tasks, tlinks):
        source = escape(str(link), quote=True)
        if isinstance(result, Exception):
            bypassed = f"❌ {escape(str(result), quote=True)}"
        elif isinstance(result, list):
            links = [str(item) for item in result]
            bypassed = "\n".join(f"✅ <a href=\"{escape(item, quote=True)}\">{escape(item)}</a>" for item in links)
        elif is_excep_link(link):
            bypassed = escape(str(result), quote=True)
        else:
            result_text = escape(str(result), quote=True)
            bypassed = f"✅ <a href=\"{result_text}\">{result_text}</a>"
        parse_data.append((source, bypassed))

    end = time()
    elapsed = f"{end - start:.0f} seconds"
    cards = []
    for source, bypassed in parse_data:
        cards.append(
            f"-\n/bypass <a href=\"{source}\">{source}</a>\n\n"
            "<b>Original Link : </b>💬\n"
            f"✅ {source}\n"
            "<b>Bypassed Link : </b>💬\n"
            f"{bypassed}\n"
            f"<b>Time Taken : {escape(elapsed)}</b> 💬\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Powered By <a href=\"https://t.me/Bypass0_bot\">@Bypass0_bot</a></b> 💬"
        )
    tg_txt = "\n\n".join(cards)
    if tg_txt:
        tg_txt += f"\n\n<code>Total Links: {no}</code>"
    if len(tg_txt) > 4000:
        chunks = [tg_txt[index : index + 3900] for index in range(0, len(tg_txt), 3900)]
        await wait_msg.edit(chunks[0], disable_web_page_preview=True)
        for chunk in chunks[1:]:
            wait_msg = await message.reply(chunk, reply_to_message_id=wait_msg.id)
            await asleep(0.5)
    elif tg_txt:
        await wait_msg.edit(tg_txt, disable_web_page_preview=True)
    else:
        await wait_msg.edit("<i>No links found.</i>")


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
