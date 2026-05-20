import os
import re
import asyncio
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
from telegram.constants import ParseMode

from db import init_db, save_result, get_last_result
from scraper import scrape_all

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def extract_username(text: str) -> str | None:
    """Extract Twitter/X username from a URL or @handle."""
    text = text.strip()

    # Handle URLs: twitter.com/username or x.com/username
    url_match = re.search(
        r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,50})", text
    )
    if url_match:
        return url_match.group(1).lower()

    # Handle @username
    at_match = re.match(r"^@?([A-Za-z0-9_]{1,50})$", text)
    if at_match:
        return at_match.group(1).lower()

    return None


def fmt_number(n: int | None) -> str:
    if n is None:
        return "N/A"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_score(s: float | None) -> str:
    if s is None:
        return "N/A"
    return f"{s:.1f}"


def diff_str(current, previous, is_score=False) -> str:
    """Return a change indicator string."""
    if current is None or previous is None:
        return ""
    delta = current - previous
    if delta == 0:
        return " _(no change)_"
    sign = "+" if delta > 0 else ""
    arrow = "↑" if delta > 0 else "↓"
    if is_score:
        return f" {arrow} _{sign}{delta:.1f}_"
    else:
        return f" {arrow} _{sign}{fmt_number(int(delta))}_"


def build_message(username: str, data: dict, prev: dict) -> str:
    gm = data["getmoni"]
    ts = data["twitterscore"]
    pg = prev.get("getmoni")
    pt = prev.get("twitterscore")

    gm_score = gm.get("score")
    gm_sf = gm.get("smart_followers")
    ts_score = ts.get("score")
    ts_sf = ts.get("smart_followers")

    gm_score_diff = diff_str(gm_score, pg["score"] if pg else None, is_score=True)
    gm_sf_diff = diff_str(gm_sf, pg["smart_followers"] if pg else None)
    ts_score_diff = diff_str(ts_score, pt["score"] if pt else None, is_score=True)
    ts_sf_diff = diff_str(ts_sf, pt["smart_followers"] if pt else None)

    gm_err = f"\n⚠️ _{gm['error']}_" if gm.get("error") else ""
    ts_err = f"\n⚠️ _{ts['error']}_" if ts.get("error") else ""

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"📊 *@{username}*",
        f"_{now}_",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🟣 *GetMoni*",
        f"Score: `{fmt_score(gm_score)}`{gm_score_diff}",
        f"Smart Followers: `{fmt_number(gm_sf)}`{gm_sf_diff}",
        f"[View profile]({gm['url']}){gm_err}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🔵 *TwitterScore*",
        f"Score: `{fmt_score(ts_score)}`{ts_score_diff}",
        f"Smart Followers: `{fmt_number(ts_sf)}`{ts_sf_diff}",
        f"[View profile]({ts['url']}){ts_err}",
    ]

    if pg is None and pt is None:
        lines.append("")
        lines.append("_First search — changes will appear next time._")

    return "\n".join(lines)


# ─── Handlers ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Twitter Profile Scorer*\n\n"
        "Send me a Twitter/X profile link or username and I'll fetch:\n"
        "• GetMoni score + smart followers\n"
        "• TwitterScore score + smart followers\n"
        "• Changes since your last search\n\n"
        "Examples:\n"
        "`https://twitter.com/elonmusk`\n"
        "`@vitalikbuterin`\n"
        "`naval`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    username = extract_username(text)

    if not username:
        await update.message.reply_text(
            "❌ Couldn't parse a Twitter username from that.\n"
            "Try: `@username` or `https://twitter.com/username`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.message.reply_text(
        f"🔍 Fetching data for *@{username}*...",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        # Scrape both sites concurrently
        data = await scrape_all(username)

        # Load previous results
        prev = {
            "getmoni": get_last_result(username, "getmoni"),
            "twitterscore": get_last_result(username, "twitterscore"),
        }

        # Save new results
        gm = data["getmoni"]
        ts = data["twitterscore"]

        if not gm.get("error"):
            save_result(username, "getmoni", gm.get("score"), gm.get("smart_followers"), gm)
        if not ts.get("error"):
            save_result(username, "twitterscore", ts.get("score"), ts.get("smart_followers"), ts)

        # Build and send the reply
        reply = build_message(username, data, prev)
        await msg.edit_text(reply, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except Exception as e:
        logger.exception("Error handling message")
        await msg.edit_text(f"❌ Error: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set")

    init_db()
    logger.info("Database initialized")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
