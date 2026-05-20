# Twitter Profile Scorer — Telegram Bot

Fetches scores and smart follower counts from **GetMoni** and **TwitterScore** for any Twitter/X profile, and tracks changes between searches.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the steps
3. Copy the bot token

### 3. Configure the token

Set the `BOT_TOKEN` environment variable:

```bash
# Linux / macOS
export BOT_TOKEN="your_token_here"

# Or create a .env file and load it
echo 'BOT_TOKEN=your_token_here' > .env
```

### 4. Run the bot

```bash
python bot.py
```

---

## Usage

Send any of these to the bot:

```
https://twitter.com/elonmusk
https://x.com/naval
@vitalikbuterin
elonmusk
```

The bot replies with a single message:

```
📊 @elonmusk
2024-01-15 10:23 UTC

━━━━━━━━━━━━━━━━━━━━
🟣 GetMoni
Score: 87.5 ↑ +2.1
Smart Followers: 1.2M ↑ +15K
View profile

━━━━━━━━━━━━━━━━━━━━
🔵 TwitterScore
Score: 91.0 (no change)
Smart Followers: 980K ↓ -3K
View profile
```

---

## Selector Tuning

If a site updates its layout and scores stop parsing, open `scraper.py` and:

1. Run the bot with `DEBUG=1` to see raw page text
2. Update the regex patterns in `scrape_getmoni()` or `scrape_twitterscore()`
3. Add/update the CSS selectors in the fallback selector lists

---

## File Structure

```
tg-twitter-bot/
├── bot.py          # Telegram bot logic
├── scraper.py      # Playwright scrapers for both sites
├── db.py           # SQLite history storage
├── requirements.txt
├── README.md
└── data.db         # Created automatically on first run
```

---

## Running as a background service (Linux)

```bash
# Create a systemd service
sudo nano /etc/systemd/system/tg-twitter-bot.service
```

```ini
[Unit]
Description=Twitter Scorer Telegram Bot
After=network.target

[Service]
WorkingDirectory=/path/to/tg-twitter-bot
ExecStart=/usr/bin/python3 bot.py
Environment=BOT_TOKEN=your_token_here
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tg-twitter-bot
sudo systemctl start tg-twitter-bot
```
