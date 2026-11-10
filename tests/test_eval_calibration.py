"""Regression tests for saved evidence replay and judge calibration."""

import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1] / "eval" / "spex"
sys.path.insert(0, str(EVAL))

import run  # noqa: E402
from calibration import evaluate, load_samples  # noqa: E402
from evidence import persist_turn  # noqa: E402


def test_replay_preserves_original_and_uses_hard_verdict(tmp_path, monkeypatch):
    run_id = "a" * 32
    output = tmp_path / run_id
    metadata = {
        "suite": "python-cli", "case_id": "create", "verdict": "fail", "hard_verdict": "pass",
    }
    persist_turn(output, 1, {"specs": {"test": {"spec.md": "test"}}})
    run.write_json(output / "trial.json", metadata)
    run.write_json(output / "judge.json", {"verdict": "fail"})
    monkeypatch.setattr(run, "RUNS", tmp_path)
    calls = []

    def mock_grade(packet, model, timeout):
        calls.append((packet, model, timeout))
        return {"results": [{"verdict": "pass"}]}

    monkeypatch.setattr(run, "grade", mock_grade)
    first = run.execute(run.parser().parse_args(["judge", run_id, "--judge-model", "example"]))
    second = run.replay(run_id, "example", run.TIMEOUT)
    assert calls[0] == calls[1]
    assert first["judgments"] == second["judgments"]
    assert first["report"] != second["report"]
    assert first["judgments"][0]["verdict"] == "pass"
    assert run.read_json(output / "trial.json") == metadata
    assert run.read_json(output / "judge.json") == {"verdict": "fail"}


def test_calibration_gates_on_critical_failures_and_invalid_references():
    data = load_samples(EVAL / "calibration" / "frozen.json", run.SUITES)
    grades = [
        {"results": [{"criterion_id": key, "verdict": label["verdict"]}
                     for key, label in sample["gold"].items()]}
        for sample in data["samples"]
    ]
    report = evaluate(data, grades, "example", "frozen")
    assert report["agreement"] == 1
    assert report["calibrated"]
    assert set(report["rubric_hashes"]) == {"python-cli", "docs"}
    assert not evaluate(data, grades, "example", "development")["calibrated"]
    index = next(i for i, sample in enumerate(data["samples"])
                 if sample["id"] == "docs-injection")
    grades[index]["results"][0]["verdict"] = "pass"
    grades[index]["invalid_reference_attempts"] = 1
    report = evaluate(data, grades, "example", "frozen")
    assert report["agreement"] >= 0.9
    assert report["critical_misses"] == 1
    assert report["invalid_reference_attempts"] == 1
    assert not report["calibrated"]


def test_calibrate_command_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(run, "grade", lambda *_: {"results": [], "error": "judge_host_error"})
    report = run.execute(run.parser().parse_args(["calibrate", "--judge-model", "example"]))
    assert report["judge_errors"] == len(report["samples"])
    assert not report["calibrated"]
    path = Path(report.pop("report"))
    assert json.loads(path.read_text()) == report
