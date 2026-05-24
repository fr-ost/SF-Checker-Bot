import os
import re
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

from db import init_db, save_result, get_last_result
from scraper import scrape_getmoni


def fmt_number(n) -> str:
    if n is None:
        return "N/A"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.2f}K"
    return str(n)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Matches twitter.com/x.com profile URLs
URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,30})",
    re.IGNORECASE,
)
# Matches a bare @handle or username (used only in private chats)
HANDLE_RE = re.compile(r"^@?([A-Za-z0-9_]{1,30})$")

# Paths that aren't real profiles
RESERVED = {
    "home", "explore", "notifications", "messages", "i", "search",
    "settings", "compose", "intent", "share", "hashtag",
}


def extract_username(text: str, is_group: bool) -> str | None:
    """
    In groups: only react to actual twitter/x URLs (avoids noise).
    In private chats: also accept @handle or bare username.
    """
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


def fmt_change(current, previous, pretty=False) -> str:
    if current is None or previous is None:
        return ""
    delta = current - previous
    if delta == 0:
        return "  (no change)"
    arrow = "🔼" if delta > 0 else "🔽"
    sign = "+" if delta > 0 else "-"
    val = fmt_number(abs(delta)) if pretty else abs(delta)
    return f"  {arrow} {sign}{val}"


def build_message(username: str, data: dict, prev: dict | None) -> str:
    score = data.get("score")
    level = data.get("level")
    smarts = data.get("smarts")
    followers = data.get("followers")
    name = data.get("name")
    url = data.get("url")

    if data.get("error"):
        return (
            f"📊 *@{username}*\n"
            f"⚠️ Could not fetch right now: _{data['error']}_\n"
            f"[Open on GetMoni]({url})"
        )

    if score is None and smarts is None and followers is None:
        return (
            f"📊 *@{username}*\n"
            f"⚠️ No data found for this profile.\n"
            f"[Open on GetMoni]({url})"
        )

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    title = f"📊 *{name}* (@{username})" if name else f"📊 *@{username}*"

    p_score = prev["score"] if prev else None
    p_smarts = prev["smarts"] if prev else None
    p_foll = prev["followers"] if prev else None

    lines = [title, f"_{now}_", ""]

    if score is not None:
        lines.append(f"🟣 *Moni Score:* `{score}`{fmt_change(score, p_score)}")
    if level:
        lines.append(f"📈 *Level:* {level}")
    if smarts is not None:
        lines.append(f"🧠 *Smart Followers:* `{smarts}`{fmt_change(smarts, p_smarts)}")
    if followers is not None:
        lines.append(
            f"👥 *Followers:* `{fmt_number(followers)}`{fmt_change(followers, p_foll, pretty=True)}"
        )

    lines.append("")
    lines.append(f"[View on GetMoni]({url})")

    if prev is None:
        lines.append("")
        lines.append("_First search — changes show next time._")

    return "\n".join(lines)


async def _process(update: Update, username: str):
    chat_action = update.effective_chat.send_action
    try:
        await chat_action(ChatAction.TYPING)
    except Exception:
        pass

    data = await scrape_getmoni(username)
    prev = get_last_result(username)

    has_data = any(data.get(k) is not None for k in ("score", "smarts", "followers"))
    if not data.get("error") and has_data:
        save_result(
            username,
            data.get("score"),
            data.get("level"),
            data.get("smarts"),
            data.get("followers"),
        )

    reply = build_message(username, data, prev)
    await update.message.reply_text(
        reply,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Moni Score Bot*\n\n"
        "Send a Twitter/X profile link and I'll reply with its "
        "*Moni Score* and *Level* from GetMoni.\n\n"
        "Works in groups too — just drop a profile link and I'll auto-reply.\n\n"
        "Examples:\n"
        "`https://x.com/0x_nation`\n"
        "`@0x_nation`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    username = extract_username(update.message.text, is_group=False)
    if not username:
        await update.message.reply_text(
            "❌ Send a valid X/Twitter link or `@username`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await _process(update, username)


async def handle_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Silent unless a real profile link is present (no noise in groups)
    if not update.message or not update.message.text:
        return
    username = extract_username(update.message.text, is_group=True)
    if not username:
        return
    await _process(update, username)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set")

    init_db()
    logger.info("Database initialized")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))

    # Private chats: accept links AND bare usernames
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_private,
    ))
    # Groups / supergroups: auto-trigger only on profile links
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_group,
    ))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
