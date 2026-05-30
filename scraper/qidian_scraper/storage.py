"""
Data storage layer: save scraped data as weekly JSON snapshots.
"""

import json
import os
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Project root relative to this file: scraper/qidian_scraper/storage.py → repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"


def get_week_label(dt: Optional[date] = None) -> str:
    """Return ISO week label like '2026-W22'."""
    if dt is None:
        dt = date.today()
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def save_weekly_snapshot(books: list[dict], week_label: Optional[str] = None) -> Path:
    """
    Save scraped books to data/{week_label}.json.
    Returns path to saved file.
    """
    if week_label is None:
        week_label = get_week_label()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "week": week_label,
        "scraped_at": datetime.now().isoformat(),
        "total": len(books),
        "books": books,
    }

    filepath = DATA_DIR / f"{week_label}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    logger.info("Saved %d books to %s", len(books), filepath)
    return filepath


def update_index() -> Path:
    """
    Scan data/*.json and rebuild data/index.json.
    The index contains metadata for each week snapshot plus aggregated stats.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    weeks = []
    for fpath in sorted(DATA_DIR.glob("*.json")):
        if fpath.name == "index.json":
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                snap = json.load(f)
            weeks.append({
                "week": snap.get("week", fpath.stem),
                "scraped_at": snap.get("scraped_at", ""),
                "total": snap.get("total", 0),
                "file": fpath.name,
            })
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Skipping %s: %s", fpath.name, e)

    # Compute cumulative stats
    all_titles = set()
    all_authors = set()
    categories: dict[str, int] = {}
    for w in weeks:
        try:
            fpath = DATA_DIR / w["file"]
            with open(fpath, "r", encoding="utf-8") as f:
                snap = json.load(f)
            for book in snap.get("books", []):
                all_titles.add(book.get("title", ""))
                all_authors.add(book.get("author", ""))
                cat = book.get("category", "未知")
                categories[cat] = categories.get(cat, 0) + 1
        except Exception:
            pass

    index = {
        "updated_at": datetime.now().isoformat(),
        "weeks": weeks,
        "total_weeks": len(weeks),
        "unique_titles": len(all_titles),
        "unique_authors": len(all_authors),
        "categories": categories,
    }

    index_path = DATA_DIR / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    logger.info("Index updated: %d weeks", len(weeks))
    return index_path
