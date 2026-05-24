# Moni Score Telegram Bot

Fetches the **Moni Score** and **Level** from [GetMoni](https://discover.getmoni.io) for any Twitter/X profile. Works in private chats and groups.

---

## What it does

Send a Twitter/X profile link and the bot replies with:
- 🟣 **Moni Score** (e.g. `729`)
- 📈 **Level** (e.g. `3. Developing`)
- 🧠 **Smart Followers** (e.g. `65`)
- 👥 **Total Followers** (e.g. `13.62K`)
- 🔼/🔽 Change in each since the last search for that profile

In **groups**, it auto-triggers whenever someone posts a `twitter.com` / `x.com` profile link, and stays silent otherwise.

---

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
export BOT_TOKEN="your_token_from_botfather"
python bot.py
```

See `INSTRUCTIONS.txt` for full Railway deployment + group setup.

---

## Group setup (important)

For the bot to read links in groups you must disable privacy mode:
1. Message @BotFather → `/setprivacy` → pick your bot → **Disable**
2. Add the bot to the group (re-add it if it was added before disabling)

---

## Score note

The Moni Score is **not** a 0-100 value. It ranges from 0 to 25000+, with levels:
`0, 100, 500, 2000, 4000, 8000, 15000, 25000, ∞`

If GetMoni changes its page layout and scores stop parsing, edit the regex patterns in `scraper.py` (`scrape_getmoni`).

---

## Files

```
tg-twitter-bot/
├── bot.py            # Telegram bot + group auto-trigger
├── scraper.py        # GetMoni scraper (score + level)
├── db.py             # SQLite history for change tracking
├── requirements.txt
├── Procfile          # Railway start command
├── Dockerfile        # Playwright + Chromium for Railway
├── .gitignore
├── INSTRUCTIONS.txt  # Full step-by-step deploy guide
└── README.md
```
