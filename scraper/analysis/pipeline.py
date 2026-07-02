#!/usr/bin/env python3
"""
Analysis pipeline: orchestrates text mining, LLM analysis, data mining, and AI agent.

Usage:
    python pipeline.py                  # Run all four modules
    python pipeline.py --text-only      # Run only text mining
    python pipeline.py --skip-text-mining  # Run only LLM analysis
    python pipeline.py --data-mining-only  # Run only data mining
    python pipeline.py --agent-only     # Run only AI agent analysis
    python pipeline.py --skip-data-mining  # Skip data mining
    python pipeline.py --skip-agent     # Skip AI agent analysis
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.text_mining import run_text_mining
from analysis.llm_analyzer import run_llm_analysis
from analysis.data_mining import run_data_mining
from analysis.agent import run_agent_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def main():
    parser = argparse.ArgumentParser(description="Run text mining + LLM + data mining + agent analysis")
    parser.add_argument("--week", type=str, help="Week label (e.g. 2026-W27)")
    parser.add_argument("--text-only", action="store_true", help="Run only text mining")
    parser.add_argument("--skip-text-mining", action="store_true", help="Skip text mining")
    parser.add_argument("--data-mining-only", action="store_true", help="Run only data mining")
    parser.add_argument("--agent-only", action="store_true", help="Run only AI agent analysis")
    parser.add_argument("--skip-data-mining", action="store_true", help="Skip data mining")
    parser.add_argument("--skip-agent", action="store_true", help="Skip AI agent analysis")
    args = parser.parse_args()

    data_dir = DATA_DIR
    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # ── Data mining only ──
    if args.data_mining_only:
        logger.info("=== Data Mining ===")
        try:
            dm_result = run_data_mining(data_dir, args.week)
            logger.info("Data mining done: %s", dm_result)
        except Exception as e:
            logger.error("Data mining failed: %s", e)
        return

    # ── Agent only ──
    if args.agent_only:
        logger.info("=== AI Agent Analysis ===")
        try:
            ag_result = run_agent_analysis(data_dir, args.week)
            logger.info("Agent done: %s", ag_result)
        except Exception as e:
            logger.error("Agent analysis failed: %s", e)
            logger.info("Pipeline continues (Agent is non-blocking)")
        return

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
        logger.info("Text-only mode: skipping LLM, data mining, and agent analysis")
        return

    # ── Data mining ──
    if not args.skip_data_mining:
        logger.info("=== Data Mining ===")
        try:
            dm_result = run_data_mining(data_dir, args.week)
            logger.info("Data mining done: %s", dm_result)
        except Exception as e:
            logger.error("Data mining failed: %s", e)
            logger.info("Pipeline continues (Data mining is non-blocking)")

    # ── LLM analysis ──
    logger.info("=== LLM Analysis ===")
    try:
        llm_result = run_llm_analysis(data_dir, args.week)
        logger.info("LLM done: %s", llm_result)
    except Exception as e:
        logger.error("LLM analysis failed: %s", e)
        logger.info("Pipeline continues (LLM is non-blocking)")

    # ── AI Agent analysis ──
    if not args.skip_agent:
        logger.info("=== AI Agent Analysis ===")
        try:
            ag_result = run_agent_analysis(data_dir, args.week)
            logger.info("Agent done: %s", ag_result)
        except Exception as e:
            logger.error("Agent analysis failed: %s", e)
            logger.info("Pipeline continues (Agent is non-blocking)")


if __name__ == "__main__":
    main()
