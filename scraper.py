import asyncio
import re
import json
import logging
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

GETMONI_URL      = "https://discover.getmoni.io/{username}"
SORSA_URL        = "https://app.sorsa.io/profile/{username}"
TWITTERSCORE_URL = "https://twitterscore.io/twitter/{username}/"

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def parse_number(text: str) -> int | None:
    """'13.62K' / '1.2M' / '227' / '12 500' / '1,200' -> int."""
    if not text:
        return None
    t = text.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^([\d.]+)([KkMmBb]?)$", t)
    if not m:
        return None
    num = float(m.group(1))
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(num * mult.get(m.group(2).upper(), 1))


def _clean_int(raw: str) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def _make_capture(store: list, keywords: list[str]):
    async def capture(response):
        try:
            ct = response.headers.get("content-type", "")
            if "json" in ct and any(k in response.url.lower() for k in keywords):
                store.append(await response.json())
        except Exception:
            pass
    return capture


# ───────────────────────── GetMoni ─────────────────────────

async def scrape_getmoni(context, username: str) -> dict:
    url = GETMONI_URL.format(username=username)
    result = {"score": None, "level": None, "smarts": None,
              "followers": None, "name": None, "url": url}
    page = await context.new_page()
    api = []
    page.on("response", _make_capture(api, ["score", "profile", "twitter", "account", "user", "smart", "follow"]))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
        try:
            await page.wait_for_function(
                """() => {
                    const t = document.body.innerText;
                    const m = t.match(/Moni\\s*Score[\\s\\S]{0,80}?(\\d{2,})/i);
                    return m && parseInt(m[1],10) > 0;
                }""",
                timeout=18_000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(2500)
        text = await page.inner_text("body")

        for payload in api:
            blob = json.dumps(payload).lower()
            if result["score"] is None:
                m = re.search(r'"(?:moni_?score|smart_?score|score)"\s*:\s*(\d+(?:\.\d+)?)', blob)
                if m and float(m.group(1)) >= 1:
                    result["score"] = int(float(m.group(1)))
            if result["smarts"] is None:
                m = re.search(r'"(?:smarts?|smart_?followers?)"\s*:\s*(\d+)', blob)
                if m:
                    result["smarts"] = int(m.group(1))
            if result["followers"] is None:
                m = re.search(r'"(?:followers_?count|followers)"\s*:\s*(\d+)', blob)
                if m:
                    result["followers"] = int(m.group(1))

        # Level: exact visible badge (ignores the (?) tooltip legend)
        try:
            badge = await page.evaluate(
                """() => {
                    const re = /^Level:\\s*(\\d+)\\s*\\.?\\s*([A-Za-z]+)$/;
                    const nodes = Array.from(document.querySelectorAll('span,div,p,td,li,strong,b,small'));
                    for (const el of nodes){const t=(el.textContent||'').trim();
                        if(re.test(t)&&el.offsetParent!==null)return t;}
                    for (const el of nodes){const t=(el.textContent||'').trim();
                        if(re.test(t))return t;}
                    return null;
                }"""
            )
            if badge:
                m = re.search(r"Level:\s*(\d+)\s*\.?\s*([A-Za-z]+)", badge)
                if m:
                    result["level"] = f"{m.group(1)}. {m.group(2)}"
        except Exception:
            pass
        if result["level"] is None:
            m = re.search(r"Moni\s*Score[\s\S]{0,120}?Level:\s*(\d+)\s*\.?\s*([A-Za-z]+)", text, re.I)
            if m:
                result["level"] = f"{m.group(1)}. {m.group(2)}"

        if result["score"] is None:
            m = re.search(r"Moni\s*Score[\s\S]{0,120}?Level:\s*\d+\s*\.?\s*[A-Za-z]+\s+(\d{1,3}(?:[ ,]\d{3})*|\d+)", text, re.I)
            if m:
                result["score"] = _clean_int(m.group(1))
        if result["score"] is None:
            m = re.search(r"Moni\s*Score[^\d]*(\d{1,3}(?:[ ,]\d{3})*|\d+)", text, re.I)
            if m:
                result["score"] = _clean_int(m.group(1))

        if result["smarts"] is None:
            m = re.search(r"(?<!Moni )\bSmarts\s+(\d[\d,]*)\b", text)
            if m:
                result["smarts"] = _clean_int(m.group(1))

        if result["followers"] is None:
            m = re.search(r"Followers\s+([\d.,]+\s*[KkMmBb]?)\s*[+\-]\d", text)
            if not m:
                m = re.search(r"Followers\s+([\d.,]+\s*[KkMmBb])", text)
            if m:
                result["followers"] = parse_number(m.group(1))

        try:
            for sel in ["h1", "[class*='name' i]", "[class*='title' i]"]:
                el = await page.query_selector(sel)
                if el:
                    t = (await el.inner_text()).strip()
                    if t and len(t) < 60 and "score" not in t.lower():
                        result["name"] = t
                        break
        except Exception:
            pass
    except PlaywrightTimeout:
        result["error"] = "Timed out loading GetMoni"
    except Exception as e:
        result["error"] = str(e)
        logger.exception("GetMoni error")
    finally:
        await page.close()
    return result


# ───────────────────────── Sorsa ─────────────────────────

async def scrape_sorsa(context, username: str) -> dict:
    url = SORSA_URL.format(username=username)
    result = {"score": None, "tier": None, "smarts": None,
              "followers": None, "following": None, "tweets": None,
              "joined": None, "url": url}
    page = await context.new_page()
    api = []
    page.on("response", _make_capture(api, ["score", "profile", "twitter", "user", "tier", "follow", "sorsa"]))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
        try:
            await page.wait_for_function(
                """() => /Tier\\s*\\d/i.test(document.body.innerText)
                       || /Score[\\s\\S]{0,20}\\d{2,}/i.test(document.body.innerText)""",
                timeout=18_000,
            )
        except Exception:
            pass

        # The "Top followers by score tiers" count loads late and sits lower on
        # the page — scroll down to trigger it, then wait for the number to render.
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        try:
            await page.wait_for_function(
                """() => {
                    const t = document.body.innerText;
                    const m = t.match(/score tiers[\\s\\S]{0,50}?(\\d{2,6})/i);
                    return m && parseInt(m[1], 10) > 0;
                }""",
                timeout=20_000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(2500)
        text = await page.inner_text("body")

        # JSON first (score only — the "Top followers by score tiers" count
        # is taken from the visible number below, which is the 326 you marked)
        for payload in api:
            blob = json.dumps(payload).lower()
            if result["score"] is None:
                m = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', blob)
                if m and float(m.group(1)) >= 1:
                    result["score"] = int(float(m.group(1)))

        # Header data (clean labels on Sorsa)
        m = re.search(r"Followers:\s*([\d.,]+\s*[KkMmBb]?)", text)
        if m: result["followers"] = m.group(1).strip()
        m = re.search(r"Follows:\s*([\d.,]+\s*[KkMmBb]?)", text)
        if m: result["following"] = m.group(1).strip()
        m = re.search(r"Tweets:\s*([\d.,]+\s*[KkMmBb]?)", text)
        if m: result["tweets"] = m.group(1).strip()
        m = re.search(r"Joined:\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})", text)
        if m: result["joined"] = re.sub(r"\s+", " ", m.group(1)).strip()

        # Score: "359 +6" right before the slider scale "100 500 1000 1500 2000"
        if result["score"] is None:
            m = re.search(r"Score\s+(\d{2,5})\s*\+?\s*\d*\s*[↗➚↑\s]*?100\s+500\s+1000", text, re.I)
            if not m:
                m = re.search(r"Score\s+(\d{2,5})\b", text, re.I)
            if m:
                result["score"] = _clean_int(m.group(1))

        # Tier: "Tier 2. Noted"
        m = re.search(r"Tier\s+(\d+)\s*\.?\s*([A-Za-z]+)", text)
        if m:
            result["tier"] = f"{m.group(1)}. {m.group(2)}"

        # Smart/Top followers: "Top followers by score tiers" big number,
        # else "TOP followers N"
        if result["smarts"] is None:
            m = re.search(r"score\s*tiers[\s\S]{0,50}?(\d{2,6})", text, re.I)
            if not m:
                m = re.search(r"TOP\s*followers\s+(\d{2,6})", text, re.I)
            if m:
                result["smarts"] = _clean_int(m.group(1))
    except PlaywrightTimeout:
        result["error"] = "Timed out loading Sorsa"
    except Exception as e:
        result["error"] = str(e)
        logger.exception("Sorsa error")
    finally:
        await page.close()
    return result


# ───────────────────────── TwitterScore ─────────────────────────

async def scrape_twitterscore(context, username: str) -> dict:
    url = TWITTERSCORE_URL.format(username=username)
    result = {"score": None, "status": None, "smarts": None, "url": url}
    page = await context.new_page()
    api = []
    page.on("response", _make_capture(api, ["score", "profile", "twitter", "user", "smart", "follow", "rank"]))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40_000)
        # TwitterScore is slow — wait until the gauge score number appears
        try:
            await page.wait_for_function(
                """() => {
                    const t = document.body.innerText;
                    const m = t.match(/Twitter Score[\\s\\S]{0,60}?(\\d+(?:\\.\\d+)?)/i);
                    return m && parseFloat(m[1]) > 0;
                }""",
                timeout=25_000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(3500)
        text = await page.inner_text("body")

        for payload in api:
            blob = json.dumps(payload).lower()
            if result["score"] is None:
                m = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', blob)
                if m and float(m.group(1)) > 0:
                    result["score"] = float(m.group(1))
            if result["status"] is None:
                m = re.search(r'"(?:status|rank|grade)"\s*:\s*"?([A-Za-z ]+?)"?[,}]', blob)
                if m:
                    result["status"] = m.group(1).strip().title()
            if result["smarts"] is None:
                m = re.search(r'"(?:smart_?followers?(?:_?count)?)"\s*:\s*(\d+)', blob)
                if m:
                    result["smarts"] = int(m.group(1))

        # Gauge: status word + score number, anchored to the "Twitter Score" label
        if result["score"] is None or result["status"] is None:
            m = re.search(
                r"Twitter Score[\s\S]{0,60}?([A-Z][a-zA-Z]*(?:\s[A-Z][a-zA-Z]*)?)\s+(\d{1,4}(?:\.\d+)?)",
                text,
            )
            if m:
                if result["status"] is None:
                    result["status"] = m.group(1).strip()
                if result["score"] is None:
                    result["score"] = float(m.group(2))

        # Total smart followers: "Smart Followers – 430"
        if result["smarts"] is None:
            m = re.search(r"Smart\s*Followers\s*[–—\-]\s*(\d[\d,]*)", text, re.I)
            if m:
                result["smarts"] = _clean_int(m.group(1))

        # normalise score: drop trailing .0
        if isinstance(result["score"], float) and result["score"].is_integer():
            result["score"] = int(result["score"])
    except PlaywrightTimeout:
        result["error"] = "Timed out loading TwitterScore"
    except Exception as e:
        result["error"] = str(e)
        logger.exception("TwitterScore error")
    finally:
        await page.close()
    return result


# ───────────────────────── Orchestrator ─────────────────────────

async def scrape_all(username: str) -> dict:
    """One browser, three tabs, scraped concurrently."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(extra_http_headers=HEADERS)
        try:
            gm, sorsa, ts = await asyncio.gather(
                scrape_getmoni(context, username),
                scrape_sorsa(context, username),
                scrape_twitterscore(context, username),
                return_exceptions=True,
            )
        finally:
            await browser.close()

    def _safe(r, url):
        if isinstance(r, Exception):
            logger.error("scraper crashed: %s", r)
            return {"error": str(r), "url": url}
        return r

    return {
        "getmoni":      _safe(gm,    GETMONI_URL.format(username=username)),
        "sorsa":        _safe(sorsa, SORSA_URL.format(username=username)),
        "twitterscore": _safe(ts,    TWITTERSCORE_URL.format(username=username)),
    }