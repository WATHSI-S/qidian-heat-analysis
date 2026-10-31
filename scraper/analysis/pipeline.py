#!/usr/bin/env python3
"""Explicit analysis stages; default all excludes optional agent exploration."""
import argparse
import importlib
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from domain import DATA_DIR, atomic_json, load_week

STAGES = {
    "summary": ("metrics", "build_summary"),
    "text": ("text_mining", "run_text_mining"),
    "data": ("data_mining", "run_data_mining"),
    "llm": ("llm_analyzer", "run_llm_analysis"),
    "report": ("llm_analyzer", "run_report"),
    "agent": ("agent", "run_agent_analysis"),
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", nargs="?", choices=["all", *STAGES])
    parser.add_argument("--week")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    only = parser.add_mutually_exclusive_group()
    for flag in ("text-only", "data-mining-only", "agent-only", "skip-text-mining"):
        only.add_argument("--" + flag, action="store_true")
    parser.add_argument("--skip-data-mining", action="store_true")
    parser.add_argument("--skip-agent", action="store_true")
    args = parser.parse_args(argv)
    legacy = [(args.text_only, "text"), (args.data_mining_only, "data"),
              (args.agent_only, "agent"), (args.skip_text_mining, "llm")]
    chosen = next((stage for enabled, stage in legacy if enabled), None)
    if chosen and args.stage:
        parser.error("Do not combine a stage with legacy mode flags")
    args.stage = chosen or args.stage or "all"
    if args.skip_data_mining and args.stage != "all":
        parser.error("--skip-data-mining is only valid with all")
    if args.skip_agent and args.stage == "agent":
        parser.error("Conflicting agent options")
    if chosen:
        logging.warning("Legacy mode flag is deprecated; use stage %s", chosen)
    return args


def main(argv=None):
    args = parse_args(argv)
    week = load_week(args.data_dir, args.week)["week"]
    stages = list(STAGES)[:-1] if args.stage == "all" else [args.stage]
    if args.skip_data_mining and "data" in stages:
        stages.remove("data")
    outcomes = {}
    failed = False
    for stage in stages:
        module, function = STAGES[stage]
        try:
            result = getattr(importlib.import_module("analysis." + module), function)(args.data_dir, week)
            statuses = [result.get("status")] if stage != "data" else [v.get("status") for v in result.values()]
            status = "error" if any(s in ("error", "unavailable") for s in statuses) else "partial" if "partial" in statuses else "ok"
            outcomes[stage] = {"status": status}
        except Exception as error:
            logging.exception("Stage %s failed", stage)
            outcomes[stage] = {"status": "error", "message": type(error).__name__}
            status = "error"
        print(json.dumps({"week": week, "stage": stage, **outcomes[stage]}, ensure_ascii=False))
        if status == "error":
            failed = True
            if stage in ("summary", "text"):
                break
    run_path = args.data_dir / "analysis" / week / "run.json"
    previous = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {"stages": {}}
    atomic_json(run_path, {"week": week, "stages": {**previous["stages"], **outcomes}})
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
