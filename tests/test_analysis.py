import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from domain import RANK_LABELS, atomic_json, comparable, load_week, normalize_snapshot
from analysis import agent
from analysis.data_mining import cluster_books, detect_anomalies, forecast_categories, forecast_series, mine_association_rules
from analysis.llm_analyzer import _parse_llm_response, batch_analyze_books, run_llm_analysis, run_report, select_sample
from analysis.metrics import build_summary, opportunity_metrics, rank_quality
from analysis.pipeline import parse_args
from analysis.results import read_result, record_failure, write_result


def snapshot(week="2026-W26", depth=3, missing=()):
    books = [{"title": f"Book {i}", "author": "Author", "category": "Fantasy", "rank": i,
              "rank_type": rt, "intro": "Magic world", "url": f"https://www.qidian.com/book/{i}/"}
             for rt in RANK_LABELS if rt not in missing for i in range(1, depth + 1)]
    quality = {rt: {"status": "complete", "requested": depth, "reason": "requested_limit"} for rt in RANK_LABELS if rt not in missing}
    return {"week": week, "source": "qidian", "books": books, "total": len(books), "quality": {"rankings": quality}}


def store(tmp_path, raw):
    atomic_json(tmp_path / (raw["week"] + ".json"), raw)
    return normalize_snapshot(raw)


def insight(book):
    return {"title": book["title"], "author": book["author"], "genre_tags": ["Magic"],
            "world_keywords": ["World"], "protagonist_archetype": "其他", "golden_finger": "其他"}


def test_comparisons_exclude_missing_rankings_and_share_depth():
    a = normalize_snapshot(snapshot(depth=3))
    b = normalize_snapshot(snapshot("2026-W27", depth=5, missing=("signnewbook",)))
    old, new, depths = comparable(a, b)
    assert "signnewbook" not in depths
    assert set(depths.values()) == {3}
    assert len(old) == len(new) == 21


def test_rank_scores_and_density_are_bounded():
    current = normalize_snapshot(snapshot(depth=180))
    entries, _ = opportunity_metrics(current, [])
    assert entries[0]["signnewDensity"] == 100
    assert all(0 <= rank_quality(i, 180) <= 1 for i in range(1, 201))
    assert 0 <= entries[0]["entryScore"] <= 100


def test_missing_newbook_rank_is_not_zero_density():
    current = normalize_snapshot(snapshot(missing=("signnewbook",)))
    assert opportunity_metrics(current, []) == ([], [])


def test_summary_historical_run_cannot_include_future(tmp_path):
    for week in ("2026-W25", "2026-W26", "2026-W27"):
        store(tmp_path, snapshot(week))
    summary = build_summary(tmp_path, "2026-W26")
    assert summary["source_weeks"] == ["2026-W25", "2026-W26"]
    assert summary["appearances"][0]["weeks"] == 2
    assert summary["comparison"]["previous_week"] == "2026-W25"


def test_failure_retains_success_and_old_run_cannot_move_pointer_back(tmp_path):
    write_result(tmp_path, "2026-W27", "keywords.json", {"top": ["new"]})
    record_failure(tmp_path, "2026-W27", "keywords.json", "timeout")
    write_result(tmp_path, "2026-W26", "keywords.json", {"top": ["old"]})
    manifest = json.loads((tmp_path / "analysis/index.json").read_text())
    assert manifest["artifacts"]["keywords.json"]["week"] == "2026-W27"
    assert manifest["artifacts"]["keywords.json"]["attempt_status"] == "error"
    assert read_result(tmp_path, "2026-W27", "keywords.json")["top"] == ["new"]


def test_forecast_requires_backtests_and_beats_naive():
    assert forecast_series([1, 2, 3, 4])["forecast"] is None
    predictor = lambda values: [values[-1] + 1, values[-1] + 2]
    result = forecast_series(list(range(1, 10)), predictor)
    assert result["backtest_origins"] == 4
    assert result["forecast"] == 10
    assert result["model_mae"] < result["baseline_mae"]
    assert forecast_series([1] * 10, lambda values: [1, 1])["forecast"] is None


def test_late_category_alignment_and_partial_week_gap(tmp_path):
    for i, week in enumerate(("2026-W24", "2026-W25", "2026-W26", "2026-W27")):
        raw = snapshot(week, missing=("signnewbook",) if i == 3 else ())
        for b in raw["books"]:
            b["category"] = "New" if i > 0 else "Old"
        store(tmp_path, raw)
    result = forecast_categories(tmp_path)
    history = result["categories"]["New"]["history"]
    assert history[0]["heat"] == 0
    assert history[1]["heat"] > 0
    assert history[-1]["heat"] is None
    assert result["categories"]["New"]["forecast"] is None


def test_exact_associations(tmp_path):
    store(tmp_path, snapshot())
    result = mine_association_rules(tmp_path)
    assert len(result["rules"]) == 56
    assert all(r["confidence"] == r["support"] == r["lift"] == 1 for r in result["rules"])


def test_sampling_is_deterministic_and_spans_rankings():
    books = snapshot(depth=180)["books"]
    for b in books:
        b["title"] += b["rank_type"]
    sample = select_sample(books)
    assert len(sample) == 120
    assert len({b["rank_type"] for b in sample}) == 8
    assert sample == select_sample(books)


@pytest.mark.parametrize("value", ['[{"wrong":"shape"}]', '[]', '{"title":"Book 1"}', 'not json'])
def test_invalid_llm_response_rejected(value):
    assert _parse_llm_response(value, snapshot()["books"][:1]) == []


def test_wrong_book_and_duplicate_model_output_rejected():
    books = snapshot(depth=3)["books"][:2]
    assert not _parse_llm_response(json.dumps([insight(books[0])] * 2), books)
    wrong = insight(books[0]); wrong["author"] = "Wrong"
    assert not _parse_llm_response(json.dumps([wrong]), books[:1])


def test_extraction_cache_avoids_model_calls(tmp_path):
    books = snapshot(depth=2)["books"]
    sample = select_sample(books)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps([insight(b) for b in sample])))])
    client = SimpleNamespace(complete=lambda **kwargs: response)
    path = tmp_path / "cache.json"
    first = batch_analyze_books(books, path, client)
    with patch("analysis.llm_analyzer._get_client", side_effect=AssertionError("Must use cache")):
        assert batch_analyze_books(books, path) == first


def test_no_api_key_preserves_valid_extraction(tmp_path, monkeypatch):
    store(tmp_path, snapshot())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_result(tmp_path, "2026-W26", "llm_insights.json", {"n_books": 1})
    assert run_llm_analysis(tmp_path)["status"] == "unavailable"
    assert read_result(tmp_path, "2026-W26", "llm_insights.json")["n_books"] == 1


def test_deterministic_report_without_api(tmp_path, monkeypatch):
    store(tmp_path, snapshot())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = run_report(tmp_path)
    assert report["week"] == "2026-W26"
    assert report["status"] == "partial"
    assert report["faq"][0]["source"] == "summary.json"
    assert any("通用建议" in item["a"] for item in report["faq"])


def test_report_timeout_preserves_success(tmp_path, monkeypatch):
    store(tmp_path, snapshot())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    write_result(tmp_path, "2026-W26", "llm_insights.json", {"sample": {}, "aggregations": {}})
    write_result(tmp_path, "2026-W26", "weekly_report.json", {"markdown": "Previous success", "model_status": "ok"})
    with patch("analysis.llm_analyzer._get_client", side_effect=TimeoutError()):
        assert run_report(tmp_path)["status"] == "error"
    assert read_result(tmp_path, "2026-W26", "weekly_report.json")["markdown"] == "Previous success"


def test_agent_context_blocks_future_and_uses_requested_week(tmp_path):
    store(tmp_path, snapshot("2026-W26"))
    store(tmp_path, snapshot("2026-W27"))
    write_result(tmp_path, "2026-W26", "keywords.json", {"top": ["older"]})
    write_result(tmp_path, "2026-W27", "keywords.json", {"top": ["newer"]})
    token = agent._CONTEXT.set((tmp_path, "2026-W26"))
    try:
        assert json.loads(agent._tool_get_keywords())["top"] == ["older"]
        with pytest.raises(ValueError):
            agent._tool_get_keywords("2026-W27")
        assert agent._load_all_weeks(tmp_path)[-1]["week"] == "2026-W26"
    finally:
        agent._CONTEXT.reset(token)


def test_cli_defaults_and_conflicts():
    assert parse_args([]).stage == "all"
    assert parse_args(["--agent-only"]).stage == "agent"
    with pytest.raises(SystemExit):
        parse_args(["text", "--agent-only"])
    with pytest.raises(SystemExit):
        parse_args(["--text-only", "--agent-only"])


def test_missing_calendar_week_does_not_create_weekly_momentum(tmp_path):
    store(tmp_path, snapshot("2026-W25"))
    store(tmp_path, snapshot("2026-W27"))
    result = build_summary(tmp_path)
    assert result["catMomentum"] == []
    assert result["comparison"]["previous_week"] is None
    assert detect_anomalies(tmp_path)["anomalies"] == []


def test_anomalies_do_not_pool_different_rankings(tmp_path):
    store(tmp_path, snapshot("2026-W25", depth=4))
    raw = snapshot("2026-W26", depth=4)
    for b in raw["books"]:
        if b["rank_type"] == "yuepiao" and b["rank"] in (1, 4):
            b["rank"] = 5 - b["rank"]
    store(tmp_path, raw)
    assert detect_anomalies(tmp_path)["anomalies"] == []


def test_text_analysis_uses_one_target_week_and_fits_once(tmp_path, monkeypatch):
    from analysis.text_mining import TfidfVectorizer, run_text_mining
    store(tmp_path, snapshot("2026-W26", depth=12))
    future = snapshot("2026-W27", depth=12)
    for b in future["books"]:
        b["intro"] = "futureuniquetoken"
    store(tmp_path, future)
    fitted = []
    original = TfidfVectorizer.fit
    def track(self, *args, **kwargs):
        fitted.append(True)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(TfidfVectorizer, "fit", track)
    assert run_text_mining(tmp_path, "2026-W26")["n_books"] == 12
    assert len(fitted) == 1
    assert "futureuniquetoken" not in read_result(tmp_path, "2026-W26", "keywords.json")["tokens"]


def test_timeout_preserves_successful_model_result(tmp_path, monkeypatch):
    store(tmp_path, snapshot())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    write_result(tmp_path, "2026-W26", "llm_insights.json", {"n_books": 10})
    with patch("analysis.llm_analyzer._get_client", side_effect=TimeoutError()):
        assert run_llm_analysis(tmp_path)["status"] == "error"
    assert read_result(tmp_path, "2026-W26", "llm_insights.json")["n_books"] == 10


def test_client_call_budget_is_enforced_without_network():
    from analysis.ai_client import AIClient
    client = AIClient.__new__(AIClient)
    client.calls, client.max_calls, client.remaining = 0, 1, 10000
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: "ok")))
    assert client.complete(messages=[{"role": "user", "content": "test"}], max_tokens=10) == "ok"
    with pytest.raises(RuntimeError):
        client.complete(messages=[], max_tokens=10)


def test_default_pipeline_excludes_agent_and_merges_stage_summary(tmp_path):
    from analysis.pipeline import main
    store(tmp_path, snapshot())
    called = []
    def stage(name):
        def call(*args):
            called.append(name)
            return {"forecast": {"status": "ok"}} if name == "data" else {"status": "ok"}
        return call
    fake = SimpleNamespace(build_summary=stage("summary"), run_text_mining=stage("text"),
                           run_data_mining=stage("data"), run_llm_analysis=stage("llm"), run_report=stage("report"))
    with patch("analysis.pipeline.importlib.import_module", return_value=fake):
        assert main(["--data-dir", str(tmp_path)]) == 0
    assert called == ["summary", "text", "data", "llm", "report"]
    assert len(json.loads((tmp_path / "analysis/2026-W26/run.json").read_text())["stages"]) == 5


def test_artifact_rejects_future_sources_and_preserves_generation_date(tmp_path):
    with pytest.raises(ValueError):
        write_result(tmp_path, "2026-W26", "keywords.json", {}, ["2026-W27"])
    output = write_result(tmp_path, "2026-W26", "keywords.json", {"generated_at": "2026-06-22T00:00:00+00:00"})
    assert output["generated_at"] == "2026-06-22T00:00:00+00:00"


def test_real_holt_beats_constant_baseline_on_linear_series():
    output = forecast_series([10 + 2 * i for i in range(12)])
    assert output["reason"] == "validated"
    assert output["model_mae"] < output["baseline_mae"]
    assert output["forecast_w2"] > output["forecast"] > 32


def test_clustering_keeps_all_books_and_handles_sparse_data(tmp_path):
    raw = snapshot(depth=20)
    for b in raw["books"]:
        b["title"] += b["rank_type"]
    store(tmp_path, raw)
    result = cluster_books(tmp_path)
    assert sum(len(c["books"]) for c in result["clusters"]) == 160
    store(tmp_path, snapshot("2026-W27", depth=3))
    assert cluster_books(tmp_path)["clusters"] == []
