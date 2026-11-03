#!/usr/bin/env python3
"""Build and verify one self-contained static artifact; never call paid APIs."""
import argparse
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))
from domain import atomic_json, build_index, load_weeks, validate_week
from analysis.metrics import build_summary
from analysis.results import read_result, write_result

PAGES = ("index", "analysis", "trends", "ai-report")
ASSETS = [*(page + ".html" for page in PAGES), "app.js", "style.css", "js/shared.js", "js/research.js",
          "vendor/echarts.min.js", "vendor/ECHARTS-LICENSE.txt", "vendor/ECHARTS-NOTICE.txt"]
ARTIFACTS = {"summary.json", "keywords.json", "category_keywords.json", "genre_tags.json", "forecast.json",
             "association_rules.json", "clusters.json", "anomalies.json", "llm_insights.json", "weekly_report.json", "agent_insights.json"}


def verify_site(output, check_hashes=False):
    output = Path(output)
    index = json.loads((output / "data/index.json").read_text(encoding="utf-8"))
    latest = index["weeks"][-1]["week"]
    manifest = json.loads((output / "data/analysis/index.json").read_text(encoding="utf-8"))
    for filename, entry in manifest["artifacts"].items():
        if filename not in ARTIFACTS or not entry.get("path"):
            continue
        relative = Path(entry["path"])
        if relative.parts != (entry["week"], filename) or entry["week"] > latest:
            raise ValueError("Invalid analysis pointer")
        result = json.loads((output / "data/analysis" / relative).read_text(encoding="utf-8"))
        if result["week"] != entry["week"] or any(w > result["week"] for w in result["source_weeks"]):
            raise ValueError("Analysis source weeks do not match its target")
    if manifest["artifacts"].get("summary.json", {}).get("week") != latest:
        raise ValueError("Missing latest-week summary")
    for file in ASSETS:
        if not (output / file).is_file():
            raise ValueError(f"Missing static asset: {file}")
    if check_hashes:
        hashes = json.loads((output / "deployment-manifest.json").read_text(encoding="utf-8"))["files"]
        actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
        if actual != set(hashes) | {"deployment-manifest.json"}:
            raise ValueError("Unexpected or missing publication file")
        for filename, expected in hashes.items():
            path = (output / filename).resolve()
            if not path.is_relative_to(output.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Artifact hash mismatch: {filename}")
    return latest


def build_site(source=ROOT, output=None, optional=True):
    source = Path(source).resolve()
    output = Path(output or source / "dist/site").resolve()
    if output == source or output.is_relative_to(source / "docs") or output.is_relative_to(source / "data"):
        raise ValueError("Build output must be separate from source assets and raw data")
    weeks = load_weeks(source / "data")
    if not weeks:
        raise ValueError("No valid real snapshots to publish")
    expected = set(ASSETS) | {"data/index.json", "deployment-manifest.json"}
    expected.update(f"data/{w['week']}.json" for w in weeks)
    output.mkdir(parents=True, exist_ok=True)
    # Only remove files previously produced by this builder, inside its output root.
    previous = output / "deployment-manifest.json"
    if previous.exists():
        for file in json.loads(previous.read_text(encoding="utf-8"))["files"]:
            path = (output / file).resolve()
            if not path.is_relative_to(output):
                raise ValueError("Build manifest escapes output directory")
            if file not in expected and path.is_file():
                path.unlink()
    for file in ASSETS:
        target = output / file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "docs" / file, target)
    # New HTML must not reuse an older deployment's cached styles or scripts.
    for module, dependencies in (("js/research.js", ("js/shared.js",)),
                                 ("app.js", ("js/shared.js", "js/research.js"))):
        path = output / module
        script = path.read_text(encoding="utf-8")
        for dependency in dependencies:
            relative = './' + (Path(dependency).name if module.startswith("js/") else dependency)
            version = hashlib.sha256((output / dependency).read_bytes()).hexdigest()[:12]
            script = script.replace("'" + relative + "'", "'" + relative + '?v=' + version + "'")
        path.write_text(script, encoding="utf-8")
    for page in PAGES:
        path = output / (page + ".html")
        html = path.read_text(encoding="utf-8")
        for asset in ASSETS:
            if asset.endswith((".css", ".js")):
                version = hashlib.sha256((output / asset).read_bytes()).hexdigest()[:12]
                html = html.replace('="' + asset + '"', '="' + asset + '?v=' + version + '"')
        path.write_text(html, encoding="utf-8")
    data_dir = output / "data"
    for snapshot in weeks:
        atomic_json(data_dir / (snapshot["week"] + ".json"), snapshot)
    atomic_json(data_dir / "index.json", build_index(data_dir))
    week = weeks[-1]["week"]
    original_manifest = source / "data/analysis/index.json"
    if original_manifest.exists():
        entries = json.loads(original_manifest.read_text(encoding="utf-8"))["artifacts"]
        for filename, entry in entries.items():
            result_week = entry.get("week")
            if filename not in ARTIFACTS:
                continue
            result = read_result(source / "data", result_week, filename) if result_week and result_week <= week else {}
            if result:
                write_result(data_dir, result_week, filename, result, result["source_weeks"])
            if entry.get("attempt_status") in ("error", "unavailable") and entry.get("attempt_week", "") <= week:
                from analysis.results import record_failure
                record_failure(data_dir, entry["attempt_week"], filename, entry.get("message"), entry["attempt_status"])
    build_summary(data_dir, week)
    if optional:
        from analysis.text_mining import run_text_mining
        from analysis.data_mining import run_data_mining
        run_text_mining(data_dir, week)
        outcomes = run_data_mining(data_dir, week)
        for name, result in outcomes.items():
            logging.info("%s: %s", name, result["status"])
    if not read_result(data_dir, week, "weekly_report.json"):
        from analysis.llm_analyzer import run_report
        run_report(data_dir, week, allow_ai=False)
    # The dashboard only looks up appearances for current books and needs no
    # duplicated book descriptions in rank changes. Keep full analysis at source.
    summary = read_result(data_dir, week, "summary.json")
    current_books = {(b["title"], b["author"]) for b in summary["heatScores"]}
    summary["appearances"] = [b for b in summary["appearances"] if (b["title"], b["author"]) in current_books]
    summary["rankChanges"] = [{key: b[key] for key in ("title", "author", "rank_type", "delta")}
                              for b in summary["rankChanges"]]
    (data_dir / "analysis" / week / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    verify_site(output)
    files = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(output.rglob("*")) if p.is_file() and p.name != "deployment-manifest.json"}
    # A cache must never enter the public artifact, including a reused output directory.
    if any("cache" in Path(file).parts or file.endswith(".env") for file in files):
        raise ValueError("Private cache/configuration in public artifact")
    for file in files:
        if file in expected:
            continue
        parts = Path(file).parts
        if parts == ("data", "analysis", "index.json"):
            continue
        if len(parts) in (4, 5) and parts[:2] == ("data", "analysis") and parts[-1] in ARTIFACTS:
            validate_week(parts[2])
            if len(parts) == 4 or parts[3] == "attempts":
                continue
        raise ValueError(f"File outside publication allowlist: {file}")
    atomic_json(output / "deployment-manifest.json", {"week": week, "files": files})
    verify_site(output, check_hashes=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-optional", action="store_true", help="Build summary/report without statistical dependencies")
    parser.add_argument("--verify-only", action="store_true", help="Verify an existing artifact including its file hashes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(verify_site(args.output or ROOT / "dist/site", check_hashes=True) if args.verify_only else build_site(output=args.output, optional=not args.skip_optional))
