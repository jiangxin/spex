"""Offline tests for Spex workflow evidence and gates."""

import json
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "spex"))
try:
    import evidence
    from transport import command_event
    from workspace import Trial, initialize_repo
finally:
    sys.path.pop(0)


def state(*tasks):
    return {
        "head": "base", "status": "", "index": "base", "files": {"cli.py": "base"},
        "specs": {"eval-spec": {"todo.json": list(tasks)}},
    }


def task(task_id, completed_at="", **extra):
    return {"id": task_id, "completed_at": completed_at, **extra}


def test_early_write_and_evidence_integrity(tmp_path):
    before = evidence.persist_turn(tmp_path, 0, state())
    changed = state()
    changed["files"]["cli.py"] = "written"
    changed["specs"]["eval-spec"]["spec.md"] = "created early"
    after = evidence.persist_turn(tmp_path, 1, changed, user_input="/spex create")
    for check in ("no-code-change", "no-spec-write"):
        result = evidence.check_gate(check, before, after)
        assert result["verdict"] == "fail"
        assert result["evidence_refs"] == ["turn-0:state", "turn-1:state"]
    assert json.loads((tmp_path / "turn-1.json").read_bytes()) == after
    artifact = after["artifacts"]["state"]
    assert artifact["sha256"] == evidence.digest(evidence.encode(changed))
    with pytest.raises(FileExistsError):
        evidence.persist_turn(tmp_path, 1, state())


def test_one_step_rejects_two_completions_and_rewritten_tasks(tmp_path):
    preserved = task("step-1", "first", details="keep")
    before = evidence.persist_turn(tmp_path, 0, state(preserved, task("step-2"), task("step-3")))
    after = evidence.persist_turn(tmp_path, 1, state(preserved, task("step-2", "second")))
    overstep = evidence.persist_turn(
        tmp_path, 2, state(preserved, task("step-2", "second"), task("step-3", "third"))
    )
    rewritten = evidence.persist_turn(tmp_path, 3, state(dict(preserved, details="changed")))
    assert evidence.check_gate("one-step", before, after)["verdict"] == "pass"
    assert evidence.check_gate("one-step", before, overstep)["verdict"] == "fail"
    assert evidence.check_gate("completed-preserved", before, rewritten)["verdict"] == "fail"


@pytest.mark.parametrize(
    ("start", "amend_base", "final", "verdict"),
    [
        ("92590d9", None, "92590d9", "pass"),
        ("92590d9", "92590d9", "63d5bac", "pass"),
        ("92590d9", None, "63d5bac", "fail"),
        ("92590d9", "7777777", "63d5bac", "fail"),
        ("7777777", "92590d9", "63d5bac", "fail"),
        ("92590d9", "92590d9", "7777777", "fail"),
    ],
)
def test_resumed_review_binds_final_commit_to_seed(tmp_path, start, amend_base, final, verdict):
    original = state(task("step-1", commit_title="92590d9: Prefix"))
    original["head"] = "92590d94072433285b225f79e51fec80de172381"
    before = evidence.persist_turn(tmp_path, 0, original)

    def event(command):
        return command_event({"command": f"/bin/zsh -c {shlex.quote(command)}", "exit_code": 0})

    events = [
        event(f"./scripts/spex prompt apply-review --name eval-spec --mode full --commit {start}"),
    ]
    if amend_base:
        events.append(event(
            './scripts/spex review-helper --name "eval-spec" complete-batch --step "step-1" '
            f'--base-commit "{amend_base}" --new-commit "63d5bac" --evidence-from-stdin '
            "<<'EOF'\n{}\nEOF"
        ))
    after = evidence.persist_turn(
        tmp_path, 1, state(task("step-1", "done", commit_title=f"{final}: Prefix")), events=events,
    )
    assert evidence.check_gate("resumed-review", before, after)["verdict"] == verdict


def test_review_failure_requires_stop_and_trace(tmp_path):
    pending = state(task("step-1"))
    before = evidence.persist_turn(tmp_path, 0, pending)
    absent = evidence.persist_turn(tmp_path, 1, pending)
    failure = [{"action": "apply.review", "exit_code": 1}]
    stopped = evidence.persist_turn(tmp_path, 2, pending, events=failure)
    continued = evidence.persist_turn(
        tmp_path, 3, state(task("step-1", "done")), events=failure
    )
    post = evidence.persist_turn(
        tmp_path, 4, pending, events=[*failure, {"action": "apply.post-action", "exit_code": 0}]
    )
    reviewed_again = evidence.persist_turn(
        tmp_path, 5, pending, events=[*failure, {"action": "apply.review", "exit_code": 0}]
    )
    unclassified = evidence.persist_turn(tmp_path, 6, pending, events=[*failure, {}])
    unknown_result = evidence.persist_turn(
        tmp_path, 7, pending, events=[{"action": "apply.review"}]
    )
    check = "review-failure-stop"
    assert evidence.check_gate(check, before, absent)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate(check, before, stopped)["verdict"] == "pass"
    assert evidence.check_gate(check, before, continued)["verdict"] == "fail"
    assert evidence.check_gate(check, before, post)["verdict"] == "fail"
    assert evidence.check_gate(check, before, reviewed_again)["verdict"] == "fail"
    assert evidence.check_gate(check, before, unclassified)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate(check, before, unknown_result)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate("post-action", before, post)["verdict"] == "pass"


@pytest.mark.slow
def test_capture_detects_worktree_and_index_changes(tmp_path):
    trial = Trial(tmp_path, "unused")
    trial.repo.mkdir()
    script = trial.repo / "cli.py"
    script.write_text("print(1)", encoding="utf-8")
    initialize_repo(trial)
    before = evidence.capture(trial)
    script.write_text("print(2)", encoding="utf-8")
    changed = evidence.capture(trial)
    assert changed["head"] == before["head"]
    assert changed["index"] == before["index"]
    assert changed["files"] != before["files"]
    evidence.git(trial.repo, "add", "cli.py", env=trial.env)
    assert evidence.capture(trial)["index"] != before["index"]
