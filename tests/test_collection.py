import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup

from domain import RANK_LABELS, atomic_json, load_weeks, normalize_snapshot
from qidian_scraper import rankings
from qidian_scraper.storage import get_week_label, save_weekly_snapshot


def item(rank, malformed=False):
    heading = "" if malformed else f'<h2><a href="//www.qidian.com/book/{rank}/">Book {rank}</a></h2>'
    return f'<li data-rid="{rank}">{heading}<p class="author"><a class="name">Author</a><a href="//www.qidian.com/xuanhuan">Fantasy</a><span>ongoing</span></p><p class="intro">Introduction</p></li>'


def run_inline(coro):
    # All browser and sleep operations are mocked; no network or event loop is needed.
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("Unexpected real asynchronous operation")


def crawl(pages, limit=200):
    page = AsyncMock()
    page.content.side_effect = pages
    page.context = AsyncMock()
    with patch.object(rankings, "_new_page", return_value=page), patch.object(rankings.asyncio, "sleep", new=AsyncMock()):
        result = run_inline(rankings._scrape_rank_page(None, "yuepiao", limit))
    return result, page


def test_book_link_not_category_link():
    book = rankings._parse_book_item(BeautifulSoup(item(1), "lxml").li, "yuepiao")
    assert book["url"] == "https://www.qidian.com/book/1/"
    assert book["book_id"] == "1"


def test_tenth_page_is_visited_and_context_is_closed():
    pages = ["<ul>" + "".join(item(n) for n in range(p * 20 + 1, p * 20 + 21)) + "</ul>" for p in range(10)]
    result, page = crawl(pages)
    assert result["status"] == "complete"
    assert len(result["books"]) == 200
    assert page.goto.call_args_list[-1].args[0].endswith("?page=10")
    page.context.close.assert_awaited_once()


def test_duplicate_page_is_partial():
    page_html = "<ul>" + "".join(item(n) for n in range(1, 21)) + "</ul>"
    result, _ = crawl([page_html] * 6)
    assert result["status"] == "partial"
    assert result["actual"] == 20
    assert result["reason"] == "duplicate_or_invalid_page"


def test_full_last_page_with_disabled_next_confirms_source_end():
    html = '<ul>' + ''.join(item(n) for n in range(1, 21)) + '</ul><div class="lbf-pagination"><a class="lbf-pagination-next lbf-pagination-disabled"></a></div>'
    result, _ = crawl([html])
    assert result["status"] == "complete"
    assert result["actual"] == 20
    assert result["reason"] == "source_end"


def test_parse_failure_does_not_renumber():
    html = "<ul>" + item(1) + item(2, malformed=True) + item(3) + "</ul>"
    result, _ = crawl([html] * 3, 3)
    assert [b["rank"] for b in result["books"]] == [1, 3]
    assert result["status"] == "partial"


@pytest.mark.parametrize("html,expected", [("<html>probe.js</html>", "failed"), ('<div class="no-data"></div>', "complete")])
def test_empty_state_must_be_explicit(html, expected):
    result, _ = crawl([html] * 3, 20)
    assert result["status"] == expected


def test_iso_year_boundary():
    assert get_week_label(date(2021, 1, 1)) == "2020-W53"


def test_partial_run_does_not_overwrite_snapshot(tmp_path):
    path = tmp_path / "2026-W44.json"
    path.write_text('{"original": true}', encoding="utf-8")
    result = save_weekly_snapshot([], "2026-W44", {}, tmp_path)
    assert result.parent.name == "partial"
    assert json.loads(path.read_text())["original"]


def test_sample_source_and_real_small_snapshot(tmp_path):
    for week, source, total in [("2026-W43", "sample", 1280), ("2026-W44", "qidian", 20)]:
        atomic_json(tmp_path / f"{week}.json", {"week": week, "source": source, "total": total, "books": []})
    assert [w["week"] for w in load_weeks(tmp_path)] == ["2026-W44"]
    (tmp_path / "2026-W42.json").write_text("invalid", encoding="utf-8")
    assert len(load_weeks(tmp_path)) == 1


def test_legacy_bad_links_are_normalized_without_mutation():
    book = {"title": "Book", "author": "Author", "rank": 1, "rank_type": "yuepiao", "url": "//www.qidian.com/xianxia"}
    raw = {"week": "2026-W27", "books": [book]}
    assert normalize_snapshot(raw)["books"][0]["url"] is None
    assert raw["books"][0]["url"].endswith("xianxia")


def test_complete_snapshot_requires_all_rankings(tmp_path):
    books = [{"title": rt, "author": "A", "rank_type": rt, "rank": 1} for rt in RANK_LABELS]
    quality = {rt: {"status": "complete", "requested": 1, "reason": "requested_limit"} for rt in RANK_LABELS}
    path = save_weekly_snapshot(books, "2026-W44", quality, tmp_path)
    assert path.parent == tmp_path
    assert json.loads(path.read_text(encoding="utf-8"))["quality"]["status"] == "complete"
