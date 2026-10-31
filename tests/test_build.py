import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("build_site", Path(__file__).resolve().parents[1] / "scripts/build_site.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_build_uses_allowlist_and_preserves_raw_history(tmp_path):
    root = Path(__file__).resolve().parents[1]
    raw = {p.name: p.read_bytes() for p in (root / "data").glob("????-W??.json")}
    output = builder.build_site(root, tmp_path / "site", optional=False)
    assert builder.verify_site(output) == max(w["week"] for w in builder.load_weeks(root / "data"))
    assert not (output / "scripts").exists()
    assert not (output / "data/cache").exists()
    week = builder.verify_site(output)
    latest = json.loads((output / f"data/{week}.json").read_text(encoding="utf-8"))
    assert all(b["url"] is None or b["url"].startswith("https://www.qidian.com/book/") for b in latest["books"])
    assert not (output / "data/2026-W20.json").exists()
    assert raw == {p.name: p.read_bytes() for p in (root / "data").glob("????-W??.json")}
    manifest = json.loads((output / "deployment-manifest.json").read_text(encoding="utf-8"))
    assert "vendor/echarts.min.js" in manifest["files"]
    # Rebuilding the same output remains valid and does not duplicate stale artifacts.
    builder.build_site(root, output, optional=False)
    builder.verify_site(output, check_hashes=True)
    (output / "app.js").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        builder.verify_site(output, check_hashes=True)


def test_builder_cannot_overwrite_sources():
    root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError):
        builder.build_site(root, root / "docs", optional=False)
