"""
Qidian ranking page scraper — uses Playwright to bypass JS anti-bot probe.
"""

import asyncio
import logging
import random
from typing import Optional

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, Browser, Page

logger = logging.getLogger(__name__)

BASE_URL = "https://www.qidian.com"

RANK_PAGES = {
    "yuepiao": "/rank/yuepiao/",          # 月票榜
    "hotsales": "/rank/hotsales/",         # 畅销榜
    "readindex": "/rank/readindex/",       # 阅读指数榜
    "recom": "/rank/recom/",               # 推荐榜
    "collect": "/rank/collect/",           # 收藏榜
    "newfans": "/rank/newfans/",           # 书友榜
    "vipup": "/rank/vipup/",               # 更新榜
    "signnewbook": "/rank/signnewbook/",   # 签约作者新书榜
}

MAX_BOOKS_PER_RANK = 200
PAGE_TIMEOUT = 30000  # ms


async def _new_page(browser: Browser) -> Page:
    """Create a new page with stealth-like settings."""
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="zh-CN",
        viewport={"width": 1920, "height": 1080},
    )
    page = await context.new_page()
    # Block images & fonts to speed up scraping
    await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,ico}", lambda route: route.abort())
    return page


def _text(el: Optional[Tag], default: str = "") -> str:
    if el is None:
        return default
    return el.get_text(strip=True)


def _parse_book_item(el: Tag, rank_type: str) -> Optional[dict]:
    """Parse a single book DOM node into a dict."""
    try:
        # Book name + link
        name_tag = (
            el.select_one("h2 a")
            or el.select_one("h4 a")
            or el.select_one("a[data-bid]")
            or el.select_one("a.book-name")
            or el.select_one("a[href*='/book/']")
        )
        if not name_tag:
            return None

        title = _text(name_tag)
        href = name_tag.get("href", "")
        if href and not href.startswith("http"):
            href = "https:" + href if href.startswith("//") else BASE_URL + href

        # Author — <a class="name"> inside <p class="author">
        author_tag = (
            el.select_one("a.name")
            or el.select_one("p.author a.name")
            or el.select_one("a.author")
            or el.select_one("[class*='author'] a")
        )
        author = _text(author_tag)

        # Category — <a> after the first <em> inside <p class="author">
        # Structure: <a class="name">AUTHOR</a><em>|</em><a>CATEGORY</a><i>·</i>...
        cat_tag = None
        author_p = el.select_one("p.author")
        if author_p:
            cat_links = author_p.select("a")
            for a in cat_links:
                href = a.get("href", "")
                cls = a.get("class", [])
                # Skip the author link and sub-category link
                if "name" not in cls and "go-sub-type" not in cls and "/author/" not in href:
                    cat_tag = a
                    break
        category = _text(cat_tag)

        # Status — <span> inside <p class="author">, after <em> separators
        status = ""
        intro = ""
        if author_p:
            status_span = author_p.select_one("span")
            status = _text(status_span)

        # Intro
        intro_tag = el.select_one("p.intro") or el.select_one(".intro") or el.select_one("[class*='desc']")
        intro = _text(intro_tag)[:120]

        return {
            "title": title,
            "author": author,
            "category": category,
            "status": status,
            "intro": intro,
            "url": href,
            "rank_type": rank_type,
        }
    except Exception:
        logger.debug("Failed to parse book item", exc_info=True)
        return None


async def _scrape_rank_page(browser: Browser, rank_type: str, max_books: int = MAX_BOOKS_PER_RANK) -> list[dict]:
    """Scrape a single ranking page, including pagination. Retries on anti-bot probe."""
    rank_path = RANK_PAGES[rank_type]
    url = BASE_URL + rank_path
    logger.info("Scraping %s: %s", rank_type, url)

    import asyncio as aio

    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        page = await _new_page(browser)
        results = []

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

            # Wait for real book list items to render (anti-bot probe may delay this)
            try:
                await page.wait_for_selector("li[data-rid]", timeout=20000)
            except Exception:
                # Check if we got the anti-bot probe page
                html = await page.content()
                if "probe" in html.lower():
                    logger.warning("%s: anti-bot probe page detected, retry %d/%d",
                                   rank_type, attempt + 1, MAX_RETRIES)
                    await page.close()
                    await aio.sleep(2 * (attempt + 1))
                    continue
                logger.warning("%s: selector wait timed out, trying fallback...", rank_type)

            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            book_selector = _find_working_selector(soup)

            # If fallback-only matched and no real books found, likely probe
            if book_selector == "li":
                sample = soup.select("li")
                has_books = any(
                    item.select_one("h2 a") or item.select_one("p.author")
                    for item in sample[:20]
                )
                if not has_books and attempt < MAX_RETRIES - 1:
                    logger.warning("%s: page has no book items, probe likely, retry %d/%d",
                                   rank_type, attempt + 1, MAX_RETRIES)
                    await page.close()
                    await aio.sleep(2 * (attempt + 1))
                    continue

            for page_num in range(1, 10):  # max 10 pages
                if page_num > 1:
                    await page.goto(f"{url}?page={page_num}", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                    await page.wait_for_timeout(2000 + random.randint(0, 2000))
                    html = await page.content()
                    soup = BeautifulSoup(html, "lxml")

                items = soup.select(book_selector)
                if not items:
                    break

                for item in items:
                    if len(results) >= max_books:
                        break
                    book = _parse_book_item(item, rank_type)
                    if book:
                        book["rank"] = len(results) + 1
                        results.append(book)

                logger.info("  Page %d: %d books (total: %d)", page_num, len(items), len(results))

                if len(items) < 20 or len(results) >= max_books:
                    break

            # Success — got real data
            if results:
                logger.info("Scraped %d books from %s ranking", len(results), rank_type)
                return results

            # No results but no probe detected — maybe empty page
            if attempt < MAX_RETRIES - 1:
                logger.warning("%s: 0 results without probe detection, retry %d/%d",
                               rank_type, attempt + 1, MAX_RETRIES)
            else:
                logger.warning("Scraped %d books from %s ranking (all attempts exhausted)",
                               len(results), rank_type)

        except Exception as e:
            logger.error("Error scraping %s (attempt %d/%d): %s",
                         rank_type, attempt + 1, MAX_RETRIES, e)
        finally:
            await page.close()

        if attempt < MAX_RETRIES - 1:
            await aio.sleep(2 * (attempt + 1))

    logger.error("Failed to scrape %s after %d retries, returning 0 results", rank_type, MAX_RETRIES)
    return []


def _find_working_selector(soup: BeautifulSoup) -> str:
    """Find a CSS selector that matches book list items on the page."""
    candidates = [
        "li[data-rid]",
        "div.rank-list ul li",
        "div.rank-list li",
        "div.rank-list > ul > li",
        "ul.rank-list li",
        "div.rank-wrap li",
        "div[class*='rank'] ul li",
        "div.rank-list div[class*='item']",
        "div.rank-body li",
        "div.book-list li",
        "#rank-list li",
        "div.rank-list ol li",
    ]
    for sel in candidates:
        items = soup.select(sel)
        if len(items) >= 10:
            logger.info("Using selector: %s (matched %d items)", sel, len(items))
            return sel
    logger.warning("No good selector found, falling back to generic 'li'")
    return "li"


def scrape_all_rankings(max_per_rank: int = MAX_BOOKS_PER_RANK) -> list[dict]:
    """Scrape all configured ranking pages. Synchronous entry point."""
    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            all_books = []
            rank_types = list(RANK_PAGES.keys())
            try:
                for i, rank_type in enumerate(rank_types):
                    if i > 0:
                        delay = random.uniform(4, 10)
                        logger.info("Waiting %.1fs before next ranking...", delay)
                        await asyncio.sleep(delay)
                    try:
                        books = await _scrape_rank_page(browser, rank_type, max_books=max_per_rank)
                        all_books.extend(books)
                    except Exception as e:
                        logger.error("Failed to scrape %s: %s", rank_type, e)
            finally:
                await browser.close()
            return all_books

    return asyncio.run(_run())
