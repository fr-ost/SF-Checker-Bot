import os
import re
import html
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode, ChatAction

from scraper import scrape_all

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,30})",
    re.IGNORECASE,
)
HANDLE_RE = re.compile(r"^@?([A-Za-z0-9_]{1,30})$")
RESERVED = {"home", "explore", "notifications", "messages", "i", "search",
            "settings", "compose", "intent", "share", "hashtag"}

DIVIDER = "──────────────────────────"


def extract_username(text: str, is_group: bool) -> str | None:
    text = text.strip()
    m = URL_RE.search(text)
    if m:
        u = m.group(1).lower()
        return None if u in RESERVED else u
    if not is_group:
        m = HANDLE_RE.match(text)
        if m:
            u = m.group(1).lower()
            return None if u in RESERVED else u
    return None


def _val(x):
    return x if x not in (None, "") else "N/A"


def _link(label, url):
    return f'<a href="{html.escape(url)}">{label}</a>'


def build_message(username: str, data: dict) -> str:
    gm = data.get("getmoni", {})
    sorsa = data.get("sorsa", {})
    ts = data.get("twitterscore", {})

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    u = html.escape(username)

    # Header (from Sorsa)
    followers = _val(sorsa.get("followers"))
    following = _val(sorsa.get("following"))
    joined = _val(sorsa.get("joined"))
    posts = _val(sorsa.get("tweets"))

    lines = [
        f"📊 <b>Analysing @{u}</b>",
        now,
        "",
        f"👥 <b>Followers:</b> {html.escape(str(followers))}  | 👥 <b>Following:</b> {html.escape(str(following))}",
        f"🤝 <b>Joined:</b> {html.escape(str(joined))}  | 📄 <b>Total Posts:</b> {html.escape(str(posts))}",
        DIVIDER,
    ]

    # GetMoni
    lines += [
        f"🟣 <b>Moni Score:</b> {_val(gm.get('score'))}",
        f"📈 <b>Level:</b> {html.escape(str(_val(gm.get('level'))))}",
        f"🧠 <b>Smart Followers:</b> {_val(gm.get('smarts'))}",
        _link("View on GetMoni", gm.get("url", "https://discover.getmoni.io/")),
        DIVIDER,
    ]

    # Sorsa
    lines += [
        f"🟣 <b>Sorsa Score:</b> {_val(sorsa.get('score'))}",
        f"📈 <b>Tier:</b> {html.escape(str(_val(sorsa.get('tier'))))}",
        f"🧠 <b>Top Followers:</b> {_val(sorsa.get('smarts'))}",
        _link("View on Sorsa", sorsa.get("url", "https://app.sorsa.io/")),
        DIVIDER,
    ]

    # TwitterScore
    lines += [
        f"🟣 <b>TwitterScore:</b> {_val(ts.get('score'))}",
        f"📈 <b>Status:</b> {html.escape(str(_val(ts.get('status'))))}",
        f"🧠 <b>Smart Followers:</b> {_val(ts.get('smarts'))}",
        _link("View on TwitterScore", ts.get("url", "https://twitterscore.io/")),
    ]

    return "\n".join(lines)


async def _process(update: Update, username: str):
    try:
        await update.effective_chat.send_action(ChatAction.TYPING)
    except Exception:
        pass

    status_msg = await update.message.reply_text(f"🔍 Analysing @{username}… (this can take ~20s)")

    try:
        data = await scrape_all(username)
        reply = build_message(username, data)
        await status_msg.edit_text(
            reply, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception as e:
        logger.exception("processing error")
        await status_msg.edit_text(f"❌ Error: {html.escape(str(e))}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Profile Score Bot</b>\n\n"
        "Send a Twitter/X profile link and I'll pull scores from "
        "<b>GetMoni</b>, <b>Sorsa</b> and <b>TwitterScore</b> in one message.\n\n"
        "Works in groups too — just drop a profile link.\n\n"
        "Examples:\nhttps://x.com/0x_nation\n@0x_nation",
        parse_mode=ParseMode.HTML,
    )


async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    username = extract_username(update.message.text, is_group=False)
    if not username:
        await update.message.reply_text("❌ Send a valid X/Twitter link or @username.")
        return
    await _process(update, username)


async def handle_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    username = extract_username(update.message.text, is_group=True)
    if not username:
        return
    await _process(update, username)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_private))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, handle_group))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()