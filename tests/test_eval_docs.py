"""Offline checks for the non-coding Spex eval suite."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "eval" / "spex"
SUITE = EVAL / "suites" / "docs"
sys.path.insert(0, str(EVAL))
try:
    from evidence import EXPECTATIONS
    from workspace import git, prepare_trial, select_cases
finally:
    sys.path.pop(0)


def test_docs_smoke_has_evidence_rubrics():
    cases = select_cases(EVAL / "suites", suite="docs", tag="smoke")
    rubrics = json.loads((SUITE / "rubrics.json").read_text(encoding="utf-8"))
    assert [case.id for case in cases] == ["edit-guide", "analyze-incident"]
    for case in cases:
        turn, = case.definition["turns"]
        assert set(turn["checks"]) <= EXPECTATIONS.keys()
        assert turn["acceptance"] == case.id
        criterion, = rubrics["cases"][case.id]
        assert criterion["turn"] == 1
        assert "acceptance" in criterion["requires"]
        assert len(criterion["anchors"]) == 3


@pytest.mark.slow
@pytest.mark.parametrize("case_id,skip_commit", [("edit-guide", False), ("analyze-incident", True)])
def test_docs_acceptance_rejects_unrelated_changes(tmp_path, case_id, skip_commit):
    case = select_cases(EVAL / "suites", suite="docs", case_id=case_id)[0]
    trial = prepare_trial(REPO, case, parent=tmp_path / "case")
    target = case.definition["turns"][0]["input"].split()[-1]
    prompt = subprocess.check_output(
        [sys.executable, str(trial.skill / "scripts" / "spex"),
         "prompt", "apply-one-task", "--json", target],
        cwd=trial.repo, env=trial.env, text=True,
    )
    assert json.loads(prompt)["skip_commit"] == str(skip_commit).lower()
    todo = trial.repo / ".spex" / "specs" / target / "todo.json"
    tasks = json.loads(todo.read_text(encoding="utf-8"))
    tasks[0]["completed_at"] = "2000-01-02T00:00:00+00:00"
    if not skip_commit:
        guide = trial.repo / "GUIDE.md"
        with guide.open("a", encoding="utf-8") as stream:
            stream.write("\nRun python3 export.py and check report.csv.\n")
        git(trial.repo, "commit", "-am", "Document export", env=trial.env)
        short = git(trial.repo, "rev-parse", "--short", "HEAD", env=trial.env).decode().strip()
        tasks[0]["commit_title"] = f"{short}: Document export"
    todo.write_text(json.dumps(tasks), encoding="utf-8")

    def evaluate():
        result = subprocess.run(
            [sys.executable, str(SUITE / "acceptance.py"), str(trial.repo), case_id],
            env=trial.env, capture_output=True, text=True, timeout=20, check=False,
        )
        payload = json.loads(result.stdout)
        assert result.returncode == (0 if payload["passed"] else 1)
        return payload

    report = evaluate()
    assert report["passed"], report
    assert ("incident_log" if skip_commit else "guide") in report["evidence"]
    if not skip_commit:
        tasks[0]["commit_title"] = None
        todo.write_text(json.dumps(tasks), encoding="utf-8")
        assert not evaluate()["checks"]["guide-committed"]
        tasks[0]["commit_title"] = f"{short}: Document export"
        todo.write_text(json.dumps(tasks), encoding="utf-8")
    (trial.repo / "export.py").write_text("# unrelated edit\n", encoding="utf-8")
    assert not evaluate()["checks"]["clean-worktree"]
    git(trial.repo, "commit", "-am", "Change unrelated source", env=trial.env)
    assert not evaluate()["checks"]["skip-commit" if skip_commit else "guide-only"]
