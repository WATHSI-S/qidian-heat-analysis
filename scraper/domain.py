"""Shared snapshot contracts and read-only normalization of legacy data."""

import json
import logging
import os
import re
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RANK_LABELS = {
    "yuepiao": "月票榜", "hotsales": "畅销榜", "readindex": "阅读指数榜",
    "recom": "推荐榜", "collect": "收藏榜", "newfans": "书友榜",
    "vipup": "更新榜", "signnewbook": "签约新书榜",
}
RANK_WEIGHTS = dict(zip(RANK_LABELS, (1., .95, .85, .8, .75, .6, .5, .7)))
WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_week(week):
    if not isinstance(week, str) or not WEEK_RE.fullmatch(week):
        raise ValueError("Expected ISO week YYYY-WNN")
    date.fromisocalendar(int(week[:4]), int(week[-2:]), 1)
    return week


def adjacent_weeks(first, second):
    def monday(week):
        validate_week(week)
        return date.fromisocalendar(int(week[:4]), int(week[-2:]), 1)
    return monday(second) - monday(first) == timedelta(weeks=1)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def book_key(book):
    return book["title"], book["author"]


def book_url(value):
    if not isinstance(value, str) or not value:
        return None
    parsed = urlparse(urljoin("https://www.qidian.com/", value))
    match = re.fullmatch(r"/book/(\d+)/?", parsed.path)
    if (parsed.scheme not in ("http", "https") or parsed.hostname not in
            ("www.qidian.com", "qidian.com") or parsed.username or parsed.password
            or parsed.port not in (None, 80, 443) or not match):
        return None
    return f"https://www.qidian.com/book/{match[1]}/"


def deduplicate(books):
    result = {}
    for book in books:
        result.setdefault(book_key(book), book)
    return list(result.values())


def normalize_snapshot(raw):
    """Never modify the original dictionary or historical files."""
    week = validate_week(raw["week"])
    legacy = "source" not in raw
    if not legacy and raw["source"] not in ("qidian", "sample"):
        raise ValueError("Unknown snapshot source")
    sample = raw.get("source") == "sample" or (
        legacy and week in {"2026-W20", "2026-W21"})
    books, invalid = [], 0
    seen = set()
    for item in raw.get("books", []):
        rank = item.get("rank")
        if (not isinstance(rank, int) or isinstance(rank, bool) or rank < 1 or
                item.get("rank_type") not in RANK_LABELS or
                not isinstance(item.get("title"), str) or not item["title"].strip() or
                not isinstance(item.get("author"), str) or not item["author"].strip()):
            invalid += 1
            continue
        key = (*book_key(item), item["rank_type"])
        if key in seen:
            invalid += 1
            continue
        seen.add(key)
        book = dict(item)
        try:
            book["url"] = book_url(book.get("url"))
        except ValueError:
            book["url"] = None
        books.append(book)
    ranks = {}
    for rt in RANK_LABELS:
        entries = [b for b in books if b["rank_type"] == rt]
        positions = [b["rank"] for b in entries]
        contiguous = sorted(positions) == list(range(1, len(entries) + 1))
        supplied = raw.get("quality", {}).get("rankings", {}).get(rt, {})
        # Before schema v2 the crawler requested 200 but visited only nine pages.
        expected = supplied.get("requested", 180 if legacy else 200)
        complete = contiguous and bool(entries) and (
            (supplied.get("status") == "complete" and
             (len(entries) >= expected or supplied.get("reason") == "source_end"))
            if not legacy else len(entries) >= 180)
        ranks[rt] = {"definition_id": "signnewbook_legacy" if rt == "signnewbook" else rt + "_v1", **supplied, "requested": expected, "actual": len(entries),
                     "depth": max(positions, default=0),
                     "status": "complete" if complete else "partial" if entries else "missing"}
    return {**raw, "source": "sample" if sample else raw.get("source", "qidian"),
            "books": books, "total": len(books),
            "quality": {"status": "complete" if all(r["status"] == "complete" for r in ranks.values()) and not invalid else "partial",
                        "invalid_records": invalid, "invalid_urls": sum(b["url"] is None for b in books),
                        "legacy": legacy, "rankings": ranks}}


def load_weeks(data_dir=DATA_DIR, through=None, include_sample=False):
    if through:
        validate_week(through)
    weeks = []
    for path in sorted(Path(data_dir).glob("????-W??.json")):
        if through and path.stem > through:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("week") != path.stem:
                raise ValueError("Snapshot week does not match filename")
            snap = normalize_snapshot(raw)
            if include_sample or snap["source"] != "sample":
                weeks.append(snap)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            logger.warning("Skipping invalid snapshot %s: %s", path.name, error)
    return weeks


def load_week(data_dir=DATA_DIR, week=None):
    weeks = load_weeks(data_dir, week)
    if not weeks or (week and weeks[-1]["week"] != week):
        raise ValueError(f"No real snapshot available for {week or 'latest week'}")
    return weeks[-1]


def comparable(first, second):
    """Only compare complete rankings at an identical depth on both sides."""
    depths = {}
    for rt in RANK_LABELS:
        a, b = (s["quality"]["rankings"][rt] for s in (first, second))
        if a["status"] == b["status"] == "complete" and a.get("definition_id") == b.get("definition_id"):
            depths[rt] = min(a["depth"], b["depth"])
    def select(snap):
        return [b for b in snap["books"] if b["rank_type"] in depths and
                b["rank"] <= depths[b["rank_type"]]]
    return select(first), select(second), depths


def build_index(data_dir=DATA_DIR):
    weeks = load_weeks(data_dir)
    books = deduplicate([b for w in weeks for b in w["books"]])
    return {"schema_version": 2, "updated_at": now(), "total_weeks": len(weeks),
            "unique_titles": len(books), "unique_authors": len({b["author"] for b in books}),
            "categories": dict(Counter(b.get("category", "未知") for b in books)),
            "rank_labels": RANK_LABELS,
            "weeks": [{"week": w["week"], "file": w["week"] + ".json", "total": w["total"],
                       "scraped_at": w.get("scraped_at"), "quality": w["quality"]} for w in weeks]}
