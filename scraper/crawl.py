#!/usr/bin/env python3
"""
Qidian Heat Analysis — weekly crawler entry point.

Usage:
    python crawl.py          # scrape all rankings, save snapshot
    python crawl.py --dry-run  # test run without saving

Called weekly by GitHub Actions to collect ~1000 book records.
"""

import argparse
import logging
import sys
from pathlib import Path

# Allow running from repo root or scraper/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qidian_scraper.rankings import scrape_all_rankings
from qidian_scraper.storage import save_weekly_snapshot, update_index, get_week_label
from domain import RANK_LABELS, validate_week

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crawl")


def main():
    parser = argparse.ArgumentParser(description="Qidian ranking crawler")
    parser.add_argument("--dry-run", action="store_true", help="Run without saving data")
    parser.add_argument("--max-per-rank", type=int, default=200,
                        help="Max books per ranking list (default: 200)")
    parser.add_argument("--ranks", nargs="+", choices=list(RANK_LABELS))
    parser.add_argument("--week", type=validate_week, default=get_week_label())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    logger.info("Starting weekly crawl (dry_run=%s, max_per_rank=%d)",
                args.dry_run, args.max_per_rank)

    if args.max_per_rank < 1:
        parser.error("--max-per-rank must be positive")
    result = scrape_all_rankings(max_per_rank=args.max_per_rank, ranks=args.ranks,
                                diagnostics=args.output.parent / "diagnostics" if args.output else None,
                                output=args.output, week=args.week)
    books = result["books"]
    logger.info("Total books scraped: %d", len(books))

    if args.dry_run:
        logger.info("Dry run — displaying sample:")
        for b in books[:5]:
            logger.info("  #%d %s — %s [%s]", b.get("rank", 0), b["title"], b["author"], b["rank_type"])
        return

    if args.output:
        return

    if not books:
        logger.error("No books scraped — check network or page selectors")
        sys.exit(1)

    saved_path = save_weekly_snapshot(books, week_label=args.week, rankings=result["rankings"])
    for rank, outcome in result["rankings"].items():
        logger.info("%s: %s (%d/%d), %s", rank, outcome["status"], outcome["actual"], outcome["requested"], outcome["reason"])
    if saved_path.parent.name == "partial":
        logger.error("Incomplete crawl archived at %s; existing snapshots retained", saved_path)
        sys.exit(1)
    update_index()
    logger.info("Done. Data saved to %s", saved_path)


if __name__ == "__main__":
    main()
