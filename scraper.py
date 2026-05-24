import asyncio
import re
import json
import logging
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

GETMONI_URL = "https://discover.getmoni.io/{username}"

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


async def scrape_getmoni(username: str) -> dict:
    """
    Scrape from discover.getmoni.io/{username}:
      score   -> Moni Score (0 .. 25000+, NOT 0-100)
      level   -> e.g. "3. Developing"
      smarts  -> smart followers count (e.g. 65)
      followers -> total followers (e.g. 13620 for 13.62K)
      name    -> display name (optional)
    """
    url = GETMONI_URL.format(username=username)
    result = {
        "score": None, "level": None, "smarts": None,
        "followers": None, "name": None, "url": url,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(extra_http_headers=HEADERS)

        api_payloads: list = []

        async def capture_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct and any(
                    kw in response.url.lower()
                    for kw in ["score", "profile", "twitter", "account", "user", "smart", "follow"]
                ):
                    api_payloads.append(await response.json())
            except Exception:
                pass

        page = await context.new_page()
        page.on("response", capture_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35_000)

            # Wait until the REAL score has loaded near the "Moni Score" label
            # (avoids reading a "Level: 1. Stealth" placeholder before data loads)
            try:
                await page.wait_for_function(
                    """() => {
                        const t = document.body.innerText;
                        const m = t.match(/Moni\\s*Score[\\s\\S]{0,80}?(\\d{2,})/i);
                        return m && parseInt(m[1], 10) > 0;
                    }""",
                    timeout=18_000,
                )
            except Exception:
                pass
            # small settle so the level text updates from placeholder to real
            await page.wait_for_timeout(2500)

            page_text = await page.inner_text("body")
            logger.debug("GetMoni text[:800]: %s", page_text[:800])

            # ── 1. API JSON first (score / smarts / followers only) ──
            #    Level is intentionally NOT taken from JSON — it was returning
            #    the wrong tier. The visible badge (step 2) is authoritative.
            for payload in api_payloads:
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

            # ── 2. LEVEL: grab the exact visible badge element ──
            #    The badge's whole text is literally "Level: 3. Developing".
            #    This avoids the (?) tooltip legend that lists "1. Stealth, 2..., 3...".
            if result["level"] is None:
                try:
                    badge = await page.evaluate(
                        """() => {
                            const re = /^Level:\\s*(\\d+)\\s*\\.?\\s*([A-Za-z]+)$/;
                            const nodes = Array.from(
                                document.querySelectorAll('span,div,p,td,li,strong,b,small')
                            );
                            // pass 1: visible elements whose ENTIRE text is the badge
                            for (const el of nodes) {
                                const t = (el.textContent || '').trim();
                                if (re.test(t) && el.offsetParent !== null) return t;
                            }
                            // pass 2: any element matching exactly (hidden ok)
                            for (const el of nodes) {
                                const t = (el.textContent || '').trim();
                                if (re.test(t)) return t;
                            }
                            return null;
                        }"""
                    )
                    if badge:
                        m = re.search(r"Level:\s*(\d+)\s*\.?\s*([A-Za-z]+)", badge)
                        if m:
                            result["level"] = f"{m.group(1)}. {m.group(2)}"
                except Exception:
                    logger.exception("level DOM query failed")

            # Fallback level: regex requiring the colon ("Level:"), nearest Moni Score.
            # The colon is mandatory so the tooltip legend ("Level\n1. Stealth") can't match.
            if result["level"] is None:
                lvl = re.search(
                    r"Moni\s*Score[\s\S]{0,120}?Level:\s*(\d+)\s*\.?\s*([A-Za-z]+)",
                    page_text, re.IGNORECASE,
                )
                if lvl:
                    result["level"] = f"{lvl.group(1)}. {lvl.group(2)}"

            # ── 3. SCORE: number right after the level badge, else after "Moni Score" ──
            if result["score"] is None:
                m = re.search(
                    r"Moni\s*Score[\s\S]{0,120}?Level:\s*\d+\s*\.?\s*[A-Za-z]+\s+"
                    r"(\d{1,3}(?:[ ,]\d{3})*|\d+)",
                    page_text, re.IGNORECASE,
                )
                if m:
                    result["score"] = _clean_int(m.group(1))
            if result["score"] is None:
                m = re.search(r"Moni\s*Score[^\d]*(\d{1,3}(?:[ ,]\d{3})*|\d+)",
                              page_text, re.IGNORECASE)
                if m:
                    result["score"] = _clean_int(m.group(1))

            # ── 4. Smarts: heading "Smarts 65" ──
            if result["smarts"] is None:
                # the standalone "Smarts <n>" heading (not "Moni smarts"/"Submit Smart")
                m = re.search(r"(?<!Moni )\bSmarts\s+(\d[\d,]*)\b", page_text)
                if m:
                    result["smarts"] = _clean_int(m.group(1))

            # ── 5. Total Followers: "Followers 13.62K +7" ──
            if result["followers"] is None:
                # prefer the one followed by a +/- change indicator
                m = re.search(
                    r"Followers\s+([\d.,]+\s*[KkMmBb]?)\s*[+\-]\d",
                    page_text,
                )
                if not m:
                    # else first "Followers <num with K/M/B>"
                    m = re.search(r"Followers\s+([\d.,]+\s*[KkMmBb])", page_text)
                if m:
                    result["followers"] = parse_number(m.group(1))

            # ── 6. Display name ──
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

            # guard against grabbing scale ticks as the score
            if result["score"] in (0, 100, 500, 2000, 4000, 8000, 15000, 25000) and result["level"] is None:
                result["score"] = None

        except PlaywrightTimeout:
            result["error"] = "Timed out loading GetMoni"
        except Exception as e:
            result["error"] = str(e)
            logger.exception("GetMoni scrape error")
        finally:
            await browser.close()

    return result
