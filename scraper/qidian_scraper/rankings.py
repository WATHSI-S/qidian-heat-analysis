"""
Qidian ranking page scraper — uses Playwright to bypass JS anti-bot probe.
"""

import asyncio
import logging
import math
import random
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential_jitter
from domain import now
from typing import Optional

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, Browser, Page
from domain import RANK_LABELS, book_key, book_url

logger = logging.getLogger(__name__)

BASE_URL = "https://www.qidian.com"

RANK_PAGES = {key: f"/rank/{key}/" for key in RANK_LABELS}

RANK_PAGES["signnewbook"] = "/rank/signNewBkAll/"
RETRYABLE = {"network", "blocked", "rate_limited", "server_error"}

MAX_BOOKS_PER_RANK = 200
PAGE_TIMEOUT = 30000  # ms


async def _new_page(browser: Browser) -> Page:
    """Create a new page with stealth-like settings."""
    context = await browser.new_context(
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


class CollectionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def next_url(current, href, rank_type):
    target = urljoin(current, href)
    parsed = urlparse(target)
    if parsed.scheme != "https" or parsed.netloc != "www.qidian.com" or not parsed.path.startswith(RANK_PAGES[rank_type]):
        raise CollectionError("invalid_pagination")
    return target


async def _scrape_rank_page(browser: Browser, rank_type: str, max_books: int = MAX_BOOKS_PER_RANK,
                            diagnostics=None) -> dict:
    if max_books < 1:
        raise ValueError("max_books must be positive")
    url = BASE_URL + RANK_PAGES[rank_type]
    records, seen, pages = [], set(), set()
    page = await _new_page(browser)
    outcome = {"requested": max_books, "source_url": url, "collected_at": now(),
               "runner": os.getenv("COLLECTION_RUNNER", "local"),
               "definition_id": "signNewBkAll_v1" if rank_type == "signnewbook" else rank_type + "_v1"}
    number, status, attempts = 1, None, 0
    events = []
    try:
        for number in range(1, math.ceil(max_books / 20) + 1):
            async for attempt in AsyncRetrying(stop=stop_after_attempt(3),
                    wait=wait_exponential_jitter(initial=5, max=60), reraise=True,
                    retry=lambda state: isinstance(state.outcome.exception(), CollectionError)
                    and state.outcome.exception().code in RETRYABLE):
                with attempt:
                    attempts += 1
                    try:
                        status = None
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                        status = response.status if response else None
                        if status == 429:
                            raise CollectionError("rate_limited")
                        if status and status >= 500:
                            raise CollectionError("server_error")
                        if status in (401, 403):
                            raise CollectionError("blocked")
                        try:
                            await page.wait_for_selector(".rank-body .book-mid-info, .no-data, .no-result, .null-book", timeout=45000)
                        except Exception:
                            pass
                        html = await page.content()
                        soup = BeautifulSoup(html, "lxml")
                        if "probe.js" in html and not soup.select(".book-mid-info"):
                            raise CollectionError("blocked")
                        if not urlparse(str(page.url)).path.startswith(RANK_PAGES[rank_type]):
                            raise CollectionError("wrong_ranking")
                        if not soup.select_one(".rank-body"):
                            raise CollectionError("invalid_structure")
                    except CollectionError as error:
                        events.append({"url": url, "final_url": str(page.url), "http_status": status,
                                       "page": number, "parsed": len(records), "reason": error.code, "at": now()})
                        raise
                    except Exception:
                        events.append({"url": url, "page": number, "http_status": status,
                                       "reason": "network", "at": now()})
                        raise CollectionError("network")
            items = soup.select(".book-img-text li[data-rid]")
            disabled = soup.select_one(".lbf-pagination-next.lbf-pagination-disabled, .lbf-pagination-next.disabled")
            link = soup.select_one("a.lbf-pagination-next:not(.lbf-pagination-disabled):not(.disabled)")
            if not items:
                if soup.select_one(".no-data, .no-result, .null-book") and not records:
                    outcome.update(status="complete", reason="source_end")
                    break
                raise CollectionError("invalid_structure")
            parsed = []
            for item in items:
                book = _parse_book_item(item, rank_type)
                rank = _text(item.select_one(".rank-tag"))
                if not book or not re.fullmatch(r"[0-9]+", rank):
                    raise CollectionError("invalid_record")
                book["rank"] = int(rank)
                if book["rank"] <= max_books:
                    parsed.append(book)
            fingerprint = tuple(book_key(book) for book in parsed)
            if fingerprint in pages:
                raise CollectionError("duplicate_or_invalid_page")
            pages.add(fingerprint)
            for book in parsed:
                if book_key(book) in seen:
                    raise CollectionError("duplicate_book")
                seen.add(book_key(book))
            records.extend(parsed)
            if [b["rank"] for b in records] != list(range(1, len(records) + 1)):
                raise CollectionError("rank_gaps")
            if len(records) >= max_books or disabled:
                outcome.update(status="complete", reason="requested_limit" if len(records) >= max_books else "source_end")
                break
            if not link or not link.get("href"):
                raise CollectionError("invalid_pagination")
            url = next_url(url, link["href"], rank_type)
            await page.wait_for_timeout(random.randint(2000, 4000))
        else:
            raise CollectionError("page_limit")
    except Exception as error:
        outcome.update(status="partial" if records else "failed",
                       reason=error.code if isinstance(error, CollectionError) else "network")
        events.append({"url": url, "final_url": str(page.url), "page": number,
                       "http_status": status, "parsed": len(records), "reason": outcome["reason"], "at": now()})
        if diagnostics:
            folder = Path(diagnostics) / rank_type
            folder.mkdir(parents=True, exist_ok=True)
            try:
                (folder / "failure.html").write_text(await page.content(), encoding="utf-8")
                await page.screenshot(path=str(folder / "failure.png"))
            except Exception:
                logger.warning("Could not save page snapshot", exc_info=True)
    finally:
        await page.context.close()
    if diagnostics and events:
        from domain import atomic_json
        atomic_json(Path(diagnostics) / rank_type / "events.json", events)
    outcome.update(books=records, actual=len(records), attempts=attempts, collected_at=now())
    return outcome


def scrape_all_rankings(max_per_rank: int = MAX_BOOKS_PER_RANK, ranks=None, diagnostics=None, output=None, week=None) -> dict:
    """Scrape all configured ranking pages. Synchronous entry point."""
    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            all_books, outcomes = [], {}
            rank_types = list(ranks or RANK_PAGES.keys())
            try:
                for i, rank_type in enumerate(rank_types):
                    if i > 0:
                        delay = random.uniform(4, 10)
                        logger.info("Waiting %.1fs before next ranking...", delay)
                        await asyncio.sleep(delay)
                    try:
                        result = await _scrape_rank_page(browser, rank_type, max_books=max_per_rank, diagnostics=diagnostics)
                        logger.info("%s: %s %d/%d (%s)", rank_type, result["status"], result["actual"], max_per_rank, result["reason"])
                        all_books.extend(result["books"])
                        outcomes[rank_type] = {k: v for k, v in result.items() if k != "books"}
                    except Exception as e:
                        outcomes[rank_type] = {"requested": max_per_rank, "actual": 0, "status": "failed", "reason": "network", "collected_at": now()}
                        logger.error("Failed to scrape %s: %s", rank_type, e)
                    if output:
                        from domain import atomic_json
                        atomic_json(output, {"schema_version": 2, "source": "qidian", "week": week, "scraped_at": now(), "books": all_books, "quality": {"rankings": outcomes}})
            finally:
                await browser.close()
            return {"books": all_books, "rankings": outcomes}

    return asyncio.run(_run())
