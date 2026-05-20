import asyncio
import re
import json
import logging
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# ── Corrected URLs ────────────────────────────────────────────────────────────
GETMONI_URL     = "https://discover.getmoni.io/{username}"
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
    """Parse '12.3K', '1.2M', '5,432' → int."""
    if not text:
        return None
    text = text.strip().replace(",", "").replace(" ", "")
    m = re.match(r"^([\d.]+)([KkMmBb]?)$", text)
    if not m:
        return None
    num = float(m.group(1))
    suffix = m.group(2).upper()
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(num * multipliers.get(suffix, 1))


def extract_score_from_text(text: str, min_val: float = 1.0) -> float | None:
    """
    Find a score value in page text. Ignores 0 (likely a loading artifact).
    Tries common patterns in priority order.
    """
    patterns = [
        # "Score\n85" or "Score: 85"
        r"Score[\s:]+(\d{1,3}(?:\.\d+)?)",
        # "85 / 100" or "85/100"
        r"(\d{1,3}(?:\.\d+)?)\s*/\s*100",
        # standalone integer 1-100 on its own line (last resort)
        r"(?:^|\n)\s*(\d{1,3})\s*(?:\n|$)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE | re.MULTILINE):
            val = float(m.group(1))
            if min_val <= val <= 100:
                return val
    return None


# ── GetMoni ───────────────────────────────────────────────────────────────────

async def scrape_getmoni(username: str) -> dict:
    url = GETMONI_URL.format(username=username)
    result = {"score": None, "smart_followers": None, "url": url}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(extra_http_headers=HEADERS)

        # Intercept API responses that carry score / follower data
        api_data: dict = {}

        async def capture_response(response):
            try:
                if any(kw in response.url for kw in ["score", "profile", "user", "stats"]):
                    if "json" in response.headers.get("content-type", ""):
                        body = await response.json()
                        api_data.update({"_raw": body, "_url": response.url})
            except Exception:
                pass

        page = await context.new_page()
        page.on("response", capture_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
            await page.wait_for_timeout(5000)

            page_text = await page.inner_text("body")
            logger.debug("GetMoni page_text[:500]: %s", page_text[:500])

            # 1. Try API data captured from network
            if api_data.get("_raw"):
                raw = api_data["_raw"]
                raw_str = json.dumps(raw).lower()
                # look for score key
                score_m = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', raw_str)
                sf_m    = re.search(r'"smart_?followers?"\s*:\s*(\d+)', raw_str)
                if score_m:
                    val = float(score_m.group(1))
                    if val >= 1:
                        result["score"] = val
                if sf_m:
                    result["smart_followers"] = int(sf_m.group(1))

            # 2. Fallback: page text
            if result["score"] is None:
                result["score"] = extract_score_from_text(page_text)

            if result["smart_followers"] is None:
                sf_match = re.search(
                    r"smart\s+followers?\s*[:\-]?\s*([\d,.]+[KkMmBb]?)",
                    page_text, re.IGNORECASE,
                )
                if sf_match:
                    result["smart_followers"] = parse_number(sf_match.group(1))

            # 3. CSS selector fallbacks
            if result["score"] is None:
                for sel in ["[class*='score' i]", "[class*='Score']", "[data-testid*='score' i]"]:
                    try:
                        els = await page.query_selector_all(sel)
                        for el in els:
                            t = await el.inner_text()
                            val = extract_score_from_text(t)
                            if val:
                                result["score"] = val
                                break
                    except Exception:
                        continue
                    if result["score"]:
                        break

        except PlaywrightTimeout:
            result["error"] = "Timed out loading GetMoni page"
        except Exception as e:
            result["error"] = str(e)
            logger.exception("GetMoni scrape error")
        finally:
            await browser.close()

    return result


# ── TwitterScore ──────────────────────────────────────────────────────────────

async def scrape_twitterscore(username: str) -> dict:
    url = TWITTERSCORE_URL.format(username=username)
    result = {"score": None, "smart_followers": None, "url": url}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(extra_http_headers=HEADERS)

        api_data: dict = {}

        async def capture_response(response):
            try:
                if any(kw in response.url for kw in ["score", "profile", "user", "stats", "twitter"]):
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        api_data.update({"_raw": body, "_url": response.url})
            except Exception:
                pass

        page = await context.new_page()
        page.on("response", capture_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
            # Give JS more time to render the score counter animation
            await page.wait_for_timeout(6000)

            page_text = await page.inner_text("body")
            logger.debug("TwitterScore page_text[:500]: %s", page_text[:500])

            # 1. Try intercepted API data
            if api_data.get("_raw"):
                raw_str = json.dumps(api_data["_raw"]).lower()
                score_m = re.search(r'"(?:twitter_?)?score"\s*:\s*(\d+(?:\.\d+)?)', raw_str)
                sf_m    = re.search(r'"smart_?followers?"\s*:\s*(\d+)', raw_str)
                if score_m:
                    val = float(score_m.group(1))
                    if val >= 1:
                        result["score"] = val
                if sf_m:
                    result["smart_followers"] = int(sf_m.group(1))

            # 2. Page text — explicit "Score" label then number, skip 0
            if result["score"] is None:
                result["score"] = extract_score_from_text(page_text, min_val=1.0)

            # 3. Smart followers from text
            if result["smart_followers"] is None:
                sf_match = re.search(
                    r"smart\s+followers?\s*[:\-]?\s*([\d,.]+[KkMmBb]?)",
                    page_text, re.IGNORECASE,
                )
                if sf_match:
                    result["smart_followers"] = parse_number(sf_match.group(1))

            # 4. CSS selector fallbacks — grab every candidate and pick the
            #    first plausible score (1-100, not 0)
            if result["score"] is None:
                for sel in [
                    "[class*='score' i]",
                    "[class*='Score']",
                    "[data-testid*='score' i]",
                    "h1", "h2",
                ]:
                    try:
                        els = await page.query_selector_all(sel)
                        for el in els:
                            t = (await el.inner_text()).strip()
                            val = extract_score_from_text(t, min_val=1.0)
                            if val:
                                result["score"] = val
                                break
                    except Exception:
                        continue
                    if result["score"]:
                        break

        except PlaywrightTimeout:
            result["error"] = "Timed out loading TwitterScore page"
        except Exception as e:
            result["error"] = str(e)
            logger.exception("TwitterScore scrape error")
        finally:
            await browser.close()

    return result


# ── Combined ──────────────────────────────────────────────────────────────────

async def scrape_all(username: str) -> dict:
    getmoni_result, twitterscore_result = await asyncio.gather(
        scrape_getmoni(username),
        scrape_twitterscore(username),
    )
    return {
        "getmoni": getmoni_result,
        "twitterscore": twitterscore_result,
    }
