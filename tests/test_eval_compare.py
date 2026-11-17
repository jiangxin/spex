"""Exercise controlled comparison and diagnostic fallback offline."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "spex"))

import run  # noqa: E402
from compare import compare, diagnosis, markdown  # noqa: E402
from evidence import persist_turn  # noqa: E402


def trial(**changes):
    row = {
        "suite": "docs", "case_id": "edit-guide", "repeat": 1, "path": "example",
        "model": "old", "spex_ref": "commit", "host": "codex", "host_version": "1",
        "invocation": "explicit", "case_hash": "case", "fixture_hash": "fixture",
        "case": {"turns": [{"input": "/spex apply guide"}]},
        "verdict": "pass", "judgment": {"model": "judge", "prompt_hash": "prompt",
                                       "rubric_hash": "rubric", "suite_rubric_hash": "suite"},
        "turn_results": [{"turn": 1, "checks": [
            {"phase": "workflow", "check_id": "example", "verdict": "pass",
             "evidence_refs": ["turn-1:state"]},
        ]}],
    }
    return {**row, **changes}


KEY = ("docs", "edit-guide", 1)
CALIBRATIONS = {("judge", "prompt", "suite", "docs")}


def test_aligns_trials_and_flags_confounds():
    baseline = {KEY: trial(), ("docs", "edit-guide", 2): trial(repeat=2)}
    candidate = {KEY: trial(model="new", spex_ref="different", fixture_hash="other",
                            judgment={"model": "different"})}
    report = compare(baseline, candidate, CALIBRATIONS)
    item = report["pairs"][0]
    assert item["changes"] == ["model", "spex_ref"]
    assert item["incomparable"] == ["fixture_hash", "judge_configuration"]
    assert not item["calibrated"]
    assert report["paired_decided"] == 0
    assert report["baseline"]["decided"] == 2
    assert report["baseline_only"] == [("docs", "edit-guide", 2)]


def test_collection_mode_is_a_comparison_axis_with_legacy_defaults():
    baseline = {KEY: trial()}
    candidate = {KEY: trial(model="new", collection="manual")}
    report = compare(baseline, candidate, CALIBRATIONS)
    assert report["pairs"][0]["changes"] == ["collection", "model"]

    candidate = {KEY: trial(model="new", collection="automatic")}
    report = compare(baseline, candidate, CALIBRATIONS)
    assert report["pairs"][0]["changes"] == ["model"]

    baseline = {KEY: trial(host="cursor")}
    candidate = {KEY: trial(host="cursor", model="new", collection="manual")}
    report = compare(baseline, candidate, CALIBRATIONS)
    assert report["pairs"][0]["changes"] == ["model"]


def test_comparison_reports_execution_changes():
    report = compare(
        {KEY: trial(execution=run.execution(1))},
        {KEY: trial(execution=run.execution(2), rejudge_execution=run.execution(3))},
    )
    assert report["pairs"][0]["changes"] == ["execution", "rejudge_execution"]
    text = markdown(report)
    assert "serial (max workers: 1) → parallel (max workers: 2)" in text
    assert "unknown → parallel (max workers: 3)" in text


def test_cli_compares_timestamp_sandboxes(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path)
    baseline, candidate = "2026-11-11-10-00-00", "2026-11-11-10-01-00"
    for name, jobs, relative in (
        (baseline, 1, "docs/edit-guide"),
        (candidate, 2, "docs/edit-guide/1"),
    ):
        directory = tmp_path / name / relative
        directory.mkdir(parents=True)
        run.write_json(directory / "trial.json", trial(execution=run.execution(jobs)))
    report = run.execute(run.parser().parse_args(["compare", baseline, candidate]))
    assert report["pairs"][0]["changes"] == ["execution"]
    assert report["pairs"][0]["execution"] == [run.execution(1), run.execution(2)]


def test_missing_trace_is_excluded_and_ai_hypothesis_is_grounded(tmp_path):
    persist_turn(tmp_path, 1, {"specs": {"guide": {
        "spec.md": "Document export behavior. token=synthetic-secret",
    }}})
    candidate = trial(model="new", verdict="insufficient_evidence", turn_results=[])
    report = compare({KEY: trial(path=str(tmp_path))}, {KEY: candidate}, CALIBRATIONS)
    assert report["pairs"][0]["calibrated"]
    assert report["paired_decided"] == 0
    assert report["pairs"][0]["deltas"][0]["candidate"] == "missing"
    answer = [{"category": "model_adaptation", "evidence_refs": ["pair-1:delta-1"],
               "reason": "The trace is missing.", "recheck": "Capture the first turn."}]
    def adapter(prompt, *_):
        assert "Document export behavior" in prompt
        assert "synthetic-secret" not in prompt
        return json.dumps(answer)

    result = diagnosis(report, adapter, "judge", 1)
    assert result[0]["confidence"] == "hypothesis"
    assert result[0]["first_phase"] == "workflow"


def test_cli_persists_basic_report_when_diagnosis_fabricates_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path)
    baseline, candidate = "a" * 32, "b" * 32
    for run_id, row in ((baseline, trial()), (candidate, trial(verdict="fail", turn_results=[]))):
        directory = tmp_path / run_id
        directory.mkdir()
        run.write_json(directory / "trial.json", row)
        run.write_json(directory / "judge.json", row["judgment"])
        persist_turn(directory, 1, {"specs": {}})
    answer = [{"category": "helper", "evidence_refs": ["fabricated"],
               "reason": "Claim", "recheck": "Reproduce"}]
    monkeypatch.setattr(run, "codex_judge", lambda *_: json.dumps(answer))
    args = run.parser().parse_args(["compare", baseline, candidate, "--judge-model", "judge"])
    report = run.execute(args)
    assert report["diagnostic_error"] == "diagnostic_judge_error"
    assert report["diagnosis"] == []
    assert report["paired_decided"] == 1
    assert "Structured comparison is retained" in Path(report["markdown"]).read_text()


def test_cli_falls_back_without_valid_saved_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path)
    baseline, candidate = "a" * 32, "b" * 32
    for run_id, row in ((baseline, trial()), (candidate, trial(verdict="fail", turn_results=[]))):
        directory = tmp_path / run_id
        directory.mkdir()
        run.write_json(directory / "trial.json", row)
    artifact = persist_turn(tmp_path / baseline, 1, {"specs": {}})
    artifact["artifacts"]["state"]["value"]["specs"]["tampered"] = {}
    run.write_json(tmp_path / baseline / "turn-1.json", artifact)

    def unexpected(*_):
        raise AssertionError("Judge must not receive a dangling or invalid reference")

    monkeypatch.setattr(run, "codex_judge", unexpected)
    args = run.parser().parse_args(["compare", baseline, candidate, "--judge-model", "judge"])
    report = run.execute(args)
    assert report["diagnostic_error"] == "diagnostic_judge_error"
    assert report["diagnosis"] == []
