"""Week-scoped results and monotonic pointers to last successful artifacts."""
import json
from pathlib import Path

from domain import atomic_json, now, validate_week

METHOD_VERSION = "2.0"


def read_result(data_dir, week, filename):
    validate_week(week)
    path = Path(data_dir) / "analysis" / week / filename
    if not path.exists():
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    return result if result.get("week") == week else {}


def _manifest(data_dir, week, filename, attempt):
    root = Path(data_dir) / "analysis"
    path = root / "index.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 2, "artifacts": {}}
    previous = manifest["artifacts"].get(filename, {})
    if week >= previous.get("attempt_week", ""):
        entry = {**previous, "attempt_week": week, "attempt_status": attempt["status"],
                 "attempted_at": attempt["generated_at"], "message": attempt.get("message")}
        if attempt["status"] in ("ok", "partial"):
            entry.update(week=week, path=f"{week}/{filename}", status=attempt["status"])
        manifest["artifacts"][filename] = entry
        manifest["updated_at"] = now()
        atomic_json(path, manifest)


def write_result(data_dir, week, filename, payload, source_weeks=None):
    validate_week(week)
    sources = source_weeks or [week]
    if any(validate_week(source) > week for source in sources):
        raise ValueError("Analysis cannot include future source weeks")
    generated = payload.get("generated_at") or now()
    result = {**payload, "schema_version": 2, "week": week,
              "source_weeks": sources, "method_version": payload.get("method_version", METHOD_VERSION),
              "generated_at": generated, "updated_at": generated, "status": payload.get("status", "ok")}
    atomic_json(Path(data_dir) / "analysis" / week / filename, result)
    _manifest(data_dir, week, filename, result)
    return result


def record_failure(data_dir, week, filename, message, status="error"):
    result = {"week": validate_week(week), "status": status, "message": message, "generated_at": now()}
    atomic_json(Path(data_dir) / "analysis" / week / "attempts" / filename, result)
    _manifest(data_dir, week, filename, result)
    return result
