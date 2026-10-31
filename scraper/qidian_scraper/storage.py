"""Validated, atomic storage of weekly snapshots."""
from datetime import date
from pathlib import Path
from domain import DATA_DIR, atomic_json, build_index, normalize_snapshot, now, validate_week


def get_week_label(dt=None):
    iso = (dt or date.today()).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def save_weekly_snapshot(books, week_label=None, rankings=None, data_dir=DATA_DIR):
    week_label = validate_week(week_label or get_week_label())
    snapshot = {"schema_version": 2, "source": "qidian", "week": week_label,
                "scraped_at": now(), "total": len(books), "books": books,
                "quality": {"rankings": rankings or {}}}
    checked = normalize_snapshot(snapshot)
    snapshot["quality"] = checked["quality"]
    if checked["total"] != len(books):
        snapshot["quality"]["status"] = "partial"
    data_dir = Path(data_dir)
    if snapshot["quality"]["status"] == "complete":
        path = data_dir / f"{week_label}.json"
    else:
        path = data_dir / "partial" / f"{week_label}-{now().replace(':', '-')}.json"
    atomic_json(path, snapshot)
    return path


def update_index(data_dir=DATA_DIR):
    path = Path(data_dir) / "index.json"
    atomic_json(path, build_index(data_dir))
    return path
