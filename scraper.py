import asyncio
import re
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


GETMONI_URL = "https://discover.getmoni.io/twitter/{username}"
TWITTERSCORE_URL = "https://twitterscore.io/twitter/{username}/"

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def parse_number(text: str) -> int | None:
    """Parse numbers like '12.3K', '1.2M', '5,432' into integers."""
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


async def scrape_getmoni(username: str) -> dict:
    """
    Scrape score and smart followers from discover.getmoni.io.
    Returns dict with keys: score, smart_followers, error (optional)
    """
    url = GETMONI_URL.format(username=username)
    result = {"score": None, "smart_followers": None, "url": url}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(extra_http_headers=HEADERS)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Wait for content to load
            await page.wait_for_timeout(4000)

            # Try to extract score — inspect the page for the actual selector
            # Common patterns on GetMoni:
            score_selectors = [
                "[data-testid='score']",
                ".score-value",
                "text=/Score/",
                "[class*='score']",
            ]

            page_text = await page.inner_text("body")

            # Score: look for pattern like "Score\n85" or "85/100"
            score_match = re.search(
                r"(?:score|Score)[^\d]*(\d+(?:\.\d+)?)", page_text
            )
            if score_match:
                result["score"] = float(score_match.group(1))

            # Smart followers
            sf_match = re.search(
                r"(?:smart\s+follower|Smart\s+Follower)[^\d]*([\d,.]+[KkMmBb]?)",
                page_text,
                re.IGNORECASE,
            )
            if sf_match:
                result["smart_followers"] = parse_number(sf_match.group(1))

            # Fallback: try direct selectors
            if result["score"] is None:
                for sel in [
                    "[data-testid*='score']",
                    "[class*='Score']",
                    "[class*='score']",
                ]:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            t = await el.inner_text()
                            m = re.search(r"(\d+(?:\.\d+)?)", t)
                            if m:
                                result["score"] = float(m.group(1))
                                break
                    except Exception:
                        continue

        except PlaywrightTimeout:
            result["error"] = "Timed out loading page"
        except Exception as e:
            result["error"] = str(e)
        finally:
            await browser.close()

    return result


async def scrape_twitterscore(username: str) -> dict:
    """
    Scrape score and smart followers from twitterscore.io.
    Returns dict with keys: score, smart_followers, error (optional)
    """
    url = TWITTERSCORE_URL.format(username=username)
    result = {"score": None, "smart_followers": None, "url": url}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(extra_http_headers=HEADERS)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(4000)

            page_text = await page.inner_text("body")

            # TwitterScore typically shows a numeric score prominently
            score_match = re.search(
                r"(?:twitter\s*score|Score)[^\d]*(\d+(?:\.\d+)?)",
                page_text,
                re.IGNORECASE,
            )
            if score_match:
                result["score"] = float(score_match.group(1))

            # Try a broader pattern if score is still None
            if result["score"] is None:
                # Look for a large number that could be a score (0-100)
                score_match2 = re.search(
                    r"\b(\d{1,3}(?:\.\d+)?)\s*/\s*100\b", page_text
                )
                if score_match2:
                    result["score"] = float(score_match2.group(1))

            # Smart followers
            sf_match = re.search(
                r"(?:smart\s+follower|Smart\s+Follower)[^\d]*([\d,.]+[KkMmBb]?)",
                page_text,
                re.IGNORECASE,
            )
            if sf_match:
                result["smart_followers"] = parse_number(sf_match.group(1))

            # Fallback selectors
            if result["score"] is None:
                for sel in [
                    ".score",
                    "[class*='score']",
                    "[class*='Score']",
                    "h1",
                    "h2",
                ]:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            t = await el.inner_text()
                            m = re.search(r"(\d+(?:\.\d+)?)", t)
                            if m and float(m.group(1)) <= 100:
                                result["score"] = float(m.group(1))
                                break
                    except Exception:
                        continue

        except PlaywrightTimeout:
            result["error"] = "Timed out loading page"
        except Exception as e:
            result["error"] = str(e)
        finally:
            await browser.close()

    return result


async def scrape_all(username: str) -> dict:
    """Run both scrapers concurrently."""
    getmoni_task = scrape_getmoni(username)
    twitterscore_task = scrape_twitterscore(username)
    getmoni_result, twitterscore_result = await asyncio.gather(
        getmoni_task, twitterscore_task
    )
    return {
        "getmoni": getmoni_result,
        "twitterscore": twitterscore_result,
    }
