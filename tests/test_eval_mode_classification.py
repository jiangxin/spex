"""Offline checks for persisted task-mode classification."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SUITE = Path(__file__).resolve().parents[1] / "eval/spex/suites/mode-classification"


def test_mode_cases_are_blind_and_have_matching_rubrics():
    cases = json.loads((SUITE / "cases.json").read_text(encoding="utf-8"))
    rubrics = json.loads((SUITE / "rubrics.json").read_text(encoding="utf-8"))
    assert set(rubrics["cases"]) == {case["id"] for case in cases}
    turns = {case["id"]: case["turns"][0] for case in cases}
    assert {name: turn["acceptance"] for name, turn in turns.items()} == {
        "negative-amounts": "software", "event-analysis": "general", "operator-guide": "general",
    }
    assert all("--mode" not in turn["input"] and "task_mode" not in turn["input"]
               and "no-code-change" in turn["checks"] for turn in turns.values())


@pytest.mark.parametrize(("actual", "expected", "passed"), [
    ("software", "software", True),
    ("general", "general", True),
    ("software", "general", False),
    (None, "software", False),
])
def test_classification_acceptance(tmp_path, actual, expected, passed):
    spec = tmp_path / ".spex/specs/event-plan"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("# Plan\n", encoding="utf-8")
    (spec / "meta.json").write_text(json.dumps({"task_mode": actual}), encoding="utf-8")
    (spec / "todo.json").write_text(json.dumps([
        {"completed_at": "", "commit_title": "", "details": "Verify the output"},
    ]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SUITE / "acceptance.py"), str(tmp_path), expected],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode == (0 if passed else 1)
    data = json.loads(result.stdout)
    assert data["checks"]["task-mode"] is passed
    assert data["evidence"]["actual_mode"] == actual
