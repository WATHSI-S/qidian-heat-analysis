#!/usr/bin/env python3
"""
Analysis pipeline: orchestrates text mining and LLM analysis.

Usage:
    python pipeline.py              # Run both text mining and LLM analysis
    python pipeline.py --text-only  # Run only text mining (no API key needed)
    python pipeline.py --skip-text-mining  # Run only LLM analysis
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.text_mining import run_text_mining
from analysis.llm_analyzer import run_llm_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def main():
    parser = argparse.ArgumentParser(description="Run text mining + LLM analysis")
    parser.add_argument("--week", type=str, help="Week label (e.g. 2026-W27)")
    parser.add_argument("--text-only", action="store_true", help="Run only text mining")
    parser.add_argument("--skip-text-mining", action="store_true", help="Skip text mining, run only LLM analysis")
    args = parser.parse_args()

    data_dir = DATA_DIR
    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_text_mining:
        # ── LLM only ──
        logger.info("=== LLM Analysis ===")
        try:
            result = run_llm_analysis(data_dir, args.week)
            logger.info("LLM done: %s", result)
        except Exception as e:
            logger.error("LLM analysis failed: %s", e)
            logger.info("Pipeline continues (LLM is non-blocking)")
        return

    # ── Text mining ──
    logger.info("=== Text Mining ===")
    try:
        tm_result = run_text_mining(data_dir, args.week)
        logger.info(
            "Text mining done: %d books, %d keywords, %d categories, %d genre tags",
            tm_result.get("n_books", 0),
            tm_result.get("n_keywords", 0),
            tm_result.get("n_categories", 0),
            tm_result.get("n_genre_tags", 0),
        )
    except Exception as e:
        logger.error("Text mining failed: %s", e)
        sys.exit(1)

    if args.text_only:
        logger.info("Text-only mode: skipping LLM analysis")
        return

    # ── LLM analysis ──
    logger.info("=== LLM Analysis ===")
    try:
        llm_result = run_llm_analysis(data_dir, args.week)
        logger.info("LLM done: %s", llm_result)
    except Exception as e:
        logger.error("LLM analysis failed: %s", e)
        logger.info("Pipeline continues (LLM is non-blocking)")


if __name__ == "__main__":
    main()
