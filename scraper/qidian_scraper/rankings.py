"""
Qidian ranking page scraper — uses Playwright to bypass JS anti-bot probe.
"""

import asyncio
import logging
import math
import random
from typing import Optional

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, Browser, Page
from domain import RANK_LABELS, book_key, book_url

logger = logging.getLogger(__name__)

BASE_URL = "https://www.qidian.com"

RANK_PAGES = {key: f"/rank/{key}/" for key in RANK_LABELS}

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
    try:
        page = await context.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,ico}", lambda route: route.abort())
        return page
    except Exception:
        await context.close()
        raise


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
        href = book_url(name_tag.get("href", ""))
        if not title or not href:
            return None

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
                category_href = a.get("href", "")
                cls = a.get("class", [])
                # Skip the author link and sub-category link
                if "name" not in cls and "go-sub-type" not in cls and "/author/" not in category_href:
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
        intro = _text(intro_tag)
        if not author:
            return None

        return {
            "title": title,
            "author": author,
            "category": category,
            "status": status,
            "intro": intro,
            "url": href,
            "book_id": href.rstrip("/").split("/")[-1],
            "rank_type": rank_type,
        }
    except Exception:
        logger.debug("Failed to parse book item", exc_info=True)
        return None


async def _scrape_rank_page(browser: Browser, rank_type: str, max_books: int = MAX_BOOKS_PER_RANK) -> dict:
    """Return records and an explicit per-ranking collection outcome."""
    if max_books < 1:
        raise ValueError("max_books must be positive")
    url = BASE_URL + RANK_PAGES[rank_type]
    best = {"books": [], "requested": max_books, "actual": 0,
            "status": "failed", "reason": "not_started"}
    for attempt in range(3):
        page = None
        records, seen, pages = [], set(), set()
        reason, complete = "page_limit", False
        try:
            page = await _new_page(browser)
            for number in range(1, math.ceil(max_books / 20) + 1):
                await page.goto(url if number == 1 else f"{url}?page={number}",
                                wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                try:
                    await page.wait_for_selector("li[data-rid]", timeout=20000)
                except Exception:
                    pass  # Validate rendered content below, including explicit empty states.
                soup = BeautifulSoup(await page.content(), "lxml")
                selector = _find_working_selector(soup)
                items = soup.select(selector) if selector else []
                pagination = soup.select_one(".lbf-pagination, .pagination")
                next_link = soup.select_one("a.lbf-pagination-next:not(.lbf-pagination-disabled):not(.disabled)")
                disabled_next = soup.select_one(".lbf-pagination-next.lbf-pagination-disabled, .lbf-pagination-next.disabled, [aria-label='下一页'][aria-disabled='true']")
                if not items:
                    complete = bool(soup.select_one(".no-data, .no-result, .null-book"))
                    reason = "source_end" if complete else "invalid_or_probe_page"
                    break
                parsed = []
                for offset, item in enumerate(items):
                    book = _parse_book_item(item, rank_type)
                    if not book:
                        continue
                    position = item.get("data-rid", "")
                    book["rank"] = int(position) if str(position).isdigit() else (number - 1) * 20 + offset + 1
                    if book["rank"] <= max_books:
                        parsed.append(book)
                fingerprint = tuple(book_key(book) for book in parsed)
                if not parsed or fingerprint in pages:
                    reason = "duplicate_or_invalid_page"
                    break
                pages.add(fingerprint)
                if any(book_key(book) in seen for book in parsed):
                    reason = "duplicate_book"
                    break
                for book in parsed:
                    seen.add(book_key(book))
                    records.append(book)
                positions = sorted(b["rank"] for b in records)
                contiguous = positions == list(range(1, len(records) + 1))
                if len(records) >= max_books:
                    complete, reason = contiguous, "requested_limit" if contiguous else "rank_gaps"
                    break
                if disabled_next or (len(items) < 20 and pagination and not next_link):
                    complete, reason = contiguous, "source_end" if contiguous else "rank_gaps"
                    break
                if number < math.ceil(max_books / 20):
                    await page.wait_for_timeout(random.randint(2000, 4000))
            outcome = {"books": records, "requested": max_books, "actual": len(records),
                       "status": "complete" if complete else "partial" if records else "failed",
                       "reason": reason, "attempts": attempt + 1}
        except Exception as error:
            outcome = {"books": records, "requested": max_books, "actual": len(records),
                       "status": "partial" if records else "failed", "reason": str(error),
                       "attempts": attempt + 1}
        finally:
            if page is not None:
                await page.context.close()
        if outcome["status"] == "complete":
            return outcome
        if len(outcome["books"]) >= len(best["books"]):
            best = outcome
        logger.warning("%s attempt %d: %s (%d records)", rank_type, attempt + 1,
                       outcome["reason"], outcome["actual"])
        if attempt < 2:
            await asyncio.sleep(2 * (attempt + 1))
    return best


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
        if items and any(_parse_book_item(item, "yuepiao") for item in items):
            logger.info("Using selector: %s (matched %d items)", sel, len(items))
            return sel
    return ""


def scrape_all_rankings(max_per_rank: int = MAX_BOOKS_PER_RANK) -> dict:
    """Scrape all configured ranking pages. Synchronous entry point."""
    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            all_books, outcomes = [], {}
            rank_types = list(RANK_PAGES.keys())
            try:
                for i, rank_type in enumerate(rank_types):
                    if i > 0:
                        delay = random.uniform(4, 10)
                        logger.info("Waiting %.1fs before next ranking...", delay)
                        await asyncio.sleep(delay)
                    try:
                        result = await _scrape_rank_page(browser, rank_type, max_books=max_per_rank)
                        all_books.extend(result["books"])
                        outcomes[rank_type] = {k: v for k, v in result.items() if k != "books"}
                    except Exception as e:
                        outcomes[rank_type] = {"requested": max_per_rank, "actual": 0, "status": "failed", "reason": str(e)}
                        logger.error("Failed to scrape %s: %s", rank_type, e)
            finally:
                await browser.close()
            return {"books": all_books, "rankings": outcomes}

    return asyncio.run(_run())
