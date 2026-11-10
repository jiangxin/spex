"""Offline checks for the Python CLI eval suite."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "eval" / "spex"
SUITE = EVAL / "suites" / "python-cli"
sys.path.insert(0, str(EVAL))
try:
    from evidence import EXPECTATIONS, check_gate, persist_turn
    from workspace import git, prepare_trial, select_cases
finally:
    sys.path.pop(0)


def test_python_cli_smoke_covers_each_command_and_has_anchored_rubrics():
    cases = select_cases(EVAL / "suites", suite="python-cli", tag="smoke")
    rubrics = json.loads((SUITE / "rubrics.json").read_text(encoding="utf-8"))
    assert [case.id for case in cases] == ["create", "modify", "apply", "apply-one-step"]
    assert rubrics["version"] == 1
    assert set(rubrics["cases"]) == {
        case.id for case in select_cases(EVAL / "suites", suite="python-cli")
    }
    inputs = []
    for case in cases:
        turns = case.definition["turns"]
        for turn in turns:
            inputs.append(turn["input"])
            assert set(turn["checks"]) <= EXPECTATIONS.keys()
            assert turn["acceptance"]
        for criterion in rubrics["cases"][case.id]:
            assert 1 <= criterion["turn"] <= len(turns)
            assert criterion["requires"]
            assert len(criterion["anchors"]) == 3
            assert 0 <= criterion["threshold"] <= 2
    assert any(value.isascii() for value in inputs)
    assert any(not value.isascii() for value in inputs)


def acceptance(trial, scenario):
    run = subprocess.run(
        [sys.executable, str(SUITE / "acceptance.py"), str(trial.repo), scenario],
        env=trial.env, capture_output=True, text=True, timeout=30, check=False,
    )
    report = json.loads(run.stdout)
    assert run.returncode == (0 if report["passed"] else 1)
    return report


@pytest.mark.slow
def test_python_cli_seeded_fixture_and_acceptance(tmp_path):
    case = select_cases(EVAL / "suites", suite="python-cli", case_id="apply-one-step")[0]
    trial = prepare_trial(REPO, case, parent=tmp_path)
    listing = subprocess.run(
        [sys.executable, str(trial.skill / "scripts" / "spex"), "list", "--json", "--must-undone"],
        cwd=trial.repo, env=trial.env, capture_output=True, text=True, check=True,
    )
    assert {item["spec_name"] for item in json.loads(listing.stdout)} == {
        "2000-01-01-00-00-greeting-format", "2000-01-01-00-01-greeting-decoration",
    }
    report = acceptance(trial, "prefix-only")
    assert not report["passed"]
    assert report["checks"]["default-compatible"]
    assert report["checks"]["suffix-not-implemented"]
    assert not report["checks"]["prefix-verbatim"]
    cli = trial.repo / "greet.py"
    updated = cli.read_text(encoding="utf-8").replace(
        '    args = parser.parse_args()', '    parser.add_argument("--prefix", default="")\n'
        '    args = parser.parse_args()'
    ).replace(
        "print(greeting.upper() if args.upper else greeting)",
        "print(args.prefix + (greeting.upper() if args.upper else greeting))",
    )
    cli.write_text(updated, encoding="utf-8")
    sha = git(trial.repo, "rev-parse", "--short", "HEAD", env=trial.env).decode().strip()
    todo = trial.repo / ".spex/specs/2000-01-01-00-01-greeting-decoration/todo.json"
    tasks = json.loads(todo.read_text(encoding="utf-8"))
    tasks[0].update(completed_at="2000-01-02T00:00:00+00:00", commit_title=f"{sha}: prefix")
    todo.write_text(json.dumps(tasks), encoding="utf-8")
    report = acceptance(trial, "prefix-only")
    assert not report["passed"]
    assert report["checks"]["prefix-verbatim"]
    assert not report["checks"]["commits-in-step-order"]
    assert not report["checks"]["clean-worktree"]

    git(trial.repo, "commit", "-am", "Implement prefix", env=trial.env)
    sha = git(trial.repo, "rev-parse", "--short", "HEAD", env=trial.env).decode().strip()
    tasks[0]["commit_title"] = f"{sha}: prefix"
    todo.write_text(json.dumps(tasks), encoding="utf-8")
    assert acceptance(trial, "prefix-only")["passed"]
    assert not acceptance(trial, "all-decoration")["passed"]


def test_python_cli_recovery_cases_have_checkpoints_and_rubrics():
    cases = select_cases(EVAL / "suites", suite="python-cli", tag="recovery")
    rubrics = json.loads((SUITE / "rubrics.json").read_text(encoding="utf-8"))["cases"]
    assert [case.id for case in cases] == [
        "create-clarification", "apply-ambiguous", "apply-review-resume",
        "apply-review-failure", "workflow-lifecycle",
    ]
    assert "no-spec-write" in cases[0].definition["turns"][0]["checks"]
    assert "no-progress" in cases[1].definition["turns"][0]["checks"]
    assert "review-failure-stop" in cases[3].definition["turns"][0]["checks"]
    for case in cases:
        turns = case.definition["turns"]
        assert all(set(turn["checks"]) <= EXPECTATIONS.keys() for turn in turns)
        assert all(1 <= rubric["turn"] <= len(turns) for rubric in rubrics[case.id])


def test_ambiguous_apply_rejects_completing_an_unselected_spec(tmp_path):
    case = select_cases(EVAL / "suites", suite="python-cli", case_id="apply-ambiguous")[0]
    checks = case.definition["turns"][1]["checks"]
    assert "one-spec-changed" in checks

    def snapshot(turn, selected_done="", unselected_done=""):
        specs = {
            name: {"todo.json": [{"id": "step-1", "completed_at": completed_at}]}
            for name, completed_at in (
                ("greeting-decoration", selected_done),
                ("greeting-format", unselected_done),
            )
        }
        return persist_turn(
            tmp_path, turn, {"head": "", "index": "", "status": "", "files": {}, "specs": specs}
        )

    before = snapshot(1)
    selected = snapshot(2, selected_done="now")
    both = snapshot(3, selected_done="now", unselected_done="now")
    assert check_gate("one-spec-changed", before, selected)["verdict"] == "pass"
    assert check_gate("one-spec-changed", before, both)["verdict"] == "fail"


@pytest.mark.slow
@pytest.mark.parametrize("case_id, review_exit", [
    ("apply-review-resume", 0), ("apply-review-failure", 1),
])
def test_seeded_review_reaches_review_status(tmp_path, case_id, review_exit):
    case = select_cases(EVAL / "suites", suite="python-cli", case_id=case_id)[0]
    trial = prepare_trial(REPO, case, parent=tmp_path)
    name = "2000-01-01-00-01-greeting-decoration"

    def spex(*args):
        return subprocess.run(
            [sys.executable, str(trial.skill / "scripts" / "spex"), *args],
            cwd=trial.repo, env=trial.env, capture_output=True, text=True, check=False,
        )

    precheck = spex("apply-helper", "precheck", "--name", name)
    assert precheck.returncode == 0, precheck.stderr
    prompt = spex("prompt", "apply-one-task", "--name", name, "--json")
    assert prompt.returncode == 0, prompt.stderr
    assert json.loads(prompt.stdout)["resume_phase"] == "review"
    status = spex("review-helper", "--name", name, "status", "--step", "step-1", "--json")
    assert status.returncode == review_exit, status.stderr
    if review_exit:
        assert "invalid JSON" in status.stderr
    seeded = subprocess.run(
        [sys.executable, "-B", str(trial.repo / "test_greet.py")],
        cwd=trial.repo, env=trial.env, capture_output=True, text=True, check=False,
    )
    assert seeded.returncode == 0, seeded.stderr
    assert "Ran 2 tests" in seeded.stderr
