"""Offline tests for Spex workflow evidence and gates."""

import json
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "spex"))
try:
    import evidence
    import native_trace
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


def cli_log(argv, code=0):
    return (
        "===== BEGIN 2026-11-11T10:00:00+08:00 =====\n"
        f"argv: spex {argv}\n"
        f"===== END exit={code} duration_ms=10 =====\n"
    )


def test_integer_task_ids_count_toward_progress(tmp_path):
    before = evidence.persist_turn(tmp_path, 0, state(task(1, "done"), task(2)))
    after = evidence.persist_turn(tmp_path, 1, state(task(1, "done"), task(2, "later")))
    changed = evidence.persist_turn(tmp_path, 2, state(task(1, "changed"), task(2)))
    assert evidence.check_gate("one-step", before, after)["verdict"] == "pass"
    assert evidence.check_gate("no-progress", before, after)["verdict"] == "fail"
    assert evidence.check_gate("completed-preserved", before, changed)["verdict"] == "fail"
    assert evidence.completed(state(task(True, "done"))) == {}


def test_native_trace_excludes_setup_and_acceptance_between_turns(tmp_path):
    repo = tmp_path / "repo"
    log = repo / ".spex/specs/eval-spec/debug.log"
    log.parent.mkdir(parents=True)
    post = cli_log("apply-helper post-action eval-spec")
    log.write_text(post)
    checkpoint = native_trace.snapshot(repo)
    out = tmp_path / "evidence"
    before = evidence.persist_turn(out, 0, state(task("step-1")))
    with log.open("a") as stream:
        stream.write(cli_log("todo-helper edit eval-spec"))
    _, first = native_trace.window(repo, checkpoint)
    turn1 = evidence.persist_turn(out, 1, state(task("step-1", "done")), native=first)
    assert evidence.check_gate("no-post-action", before, turn1)["verdict"] == "pass"
    assert evidence.check_gate("post-action", before, turn1)["verdict"] == "fail"
    with log.open("a") as stream:
        stream.write(post)  # Acceptance output belongs to neither trial turn.
    checkpoint = native_trace.snapshot(repo)
    with log.open("a") as stream:
        stream.write(post)
    _, second = native_trace.window(repo, checkpoint)
    turn2 = evidence.persist_turn(out, 2, state(task("step-1", "done")), native=second)
    check = evidence.check_gate("post-action", turn1, turn2)
    assert check["verdict"] == "pass"
    assert "turn-2:spex-trace" in check["evidence_refs"]
    log.write_text(post)
    _, replaced = native_trace.window(repo, checkpoint)
    turn3 = evidence.persist_turn(out, 3, state(task("step-1", "done")), native=replaced)
    assert evidence.check_gate("post-action", turn2, turn3)["verdict"] == "insufficient_evidence"


@pytest.mark.parametrize("step", ["step-1", 1])
def test_native_review_failure_stop_requires_no_later_workflow(tmp_path, step):
    pending = state(task(step))
    before = evidence.persist_turn(tmp_path, 0, pending)
    log = "specs/eval-spec/debug.log"
    failure = cli_log(f"review-helper --name eval-spec status --step {step} --json", 1)
    later = cli_log("prompt apply-one-task eval-spec")
    for turn, contents, verdict in ((1, failure, "pass"), (2, failure + later, "fail")):
        gaps = set()
        events = native_trace.parse(contents.splitlines(), log, gaps)
        after = evidence.persist_turn(
            tmp_path, turn, pending, native={"events": events, "gaps": sorted(gaps)},
        )
        assert evidence.check_gate("review-failure-stop", before, after)["verdict"] == verdict


@pytest.mark.parametrize("wrong_spec", [False, True])
def test_review_failure_stop_checks_spec_identity_and_pending_order(tmp_path, wrong_spec):
    pending = state(task("step-1"), task("step-2"))
    pending["specs"]["other-spec"] = {"todo.json": [task("step-1", "done")]}
    before = evidence.persist_turn(tmp_path, 0, pending)
    changed = json.loads(json.dumps(pending))
    changed["specs"]["eval-spec"]["todo.json"].reverse()
    selector = "other-spec" if wrong_spec else "eval-spec"
    log = cli_log(f"review-helper --name {selector} status --step step-1", 1)
    gaps = set()
    events = native_trace.parse(log.splitlines(), "debug.log", gaps)
    for turn, snapshot, expected in [
        (1, pending, "fail" if wrong_spec else "pass"), (2, changed, "fail"),
    ]:
        after = evidence.persist_turn(
            tmp_path, turn, snapshot, native={"events": events, "gaps": sorted(gaps)},
        )
        assert evidence.check_gate("review-failure-stop", before, after)["verdict"] == expected


def test_native_prompt_skip_requires_logged_output_and_success():
    log = cli_log("prompt apply-review --name eval-spec --commit abc1234")
    log = log.replace(
        "===== END", "----- stdout -----\n"
        "[truncated prompt stdout, total=120B; task_id=step-1; skipped=True]\n===== END",
    )
    events = native_trace.parse(log.splitlines(), "specs/eval-spec/debug.log", set())
    assert events[0]["action"] == "apply.review-command"
    assert events[0]["skipped"] is True
    assert events[0]["step"] == "step-1"
    assert events[0]["commit"] == "abc1234"


@pytest.mark.parametrize(("fix", "expected"), [(False, "92590d9"), (True, "63d5bac")])
@pytest.mark.parametrize("step", ["step-1", 1])
def test_native_resume_follows_the_reviewed_commit(tmp_path, fix, expected, step):
    old = state(task(step, commit_title="92590d9: Prefix"))
    old["head"] = "92590d94072433285b225f79e51fec80de172381"
    before = evidence.persist_turn(tmp_path, 0, old)
    lines = [
        f"===== APPLY review {edge} step={step} round=1 mode=full commit=92590d9 ====="
        for edge in ("begin", "end")
    ]
    if fix:
        lines.append(f"===== APPLY fix end step={step} base=92590d9 new=63d5bac =====")
    gaps = set()
    events = native_trace.parse(lines, "specs/eval-spec/debug.log", gaps)
    after = evidence.persist_turn(
        tmp_path, 1, state(task(step, "done", commit_title=f"{expected}: Prefix")),
        native={"events": events, "gaps": sorted(gaps)},
    )
    assert evidence.check_gate("resumed-review", before, after)["verdict"] == "pass"


def test_optional_observations_fill_gaps_without_proving_absence(tmp_path):
    before = evidence.persist_turn(tmp_path, 0, state(task("step-1")))
    after = evidence.persist_turn(
        tmp_path, 1, state(task("step-1", "done")),
        native={"events": [], "gaps": ["missing_spex_commands"]},
        supplemental=[{"action": "apply.post-action", "spec": "eval-spec",
                       "exit_code": 0, "source": "observed"}],
    )
    assert evidence.check_gate("post-action", before, after)["verdict"] == "pass"
    assert evidence.check_gate("no-post-action", before, after)["verdict"] == "fail"
    unsupported = evidence.persist_turn(
        tmp_path, 2, state(task("step-1", "done")),
        native={"events": [], "gaps": ["missing_spex_commands"]}, supplemental=[],
    )
    assert evidence.check_gate("no-post-action", before, unsupported)["verdict"] == (
        "insufficient_evidence"
    )


@pytest.mark.parametrize(("command", "gaps", "required", "forbidden"), [
    ("/fixture/scripts/spex apply-helper post-action --name eval-spec",
     ["missing_spex_commands"], "pass", "fail"),
    ("/fixture/scripts/spex apply-helper post-action eval-spec",
     [], "insufficient_evidence", "fail"),
    ("/fixture/scripts/spex apply-helper post-action --name other-spec",
     ["missing_spex_commands"], "insufficient_evidence", "insufficient_evidence"),
    ("/fixture/scripts/spex apply-helper post-action --name eval-spec || true",
     ["missing_spex_commands"], "insufficient_evidence", "insufficient_evidence"),
])
def test_host_transcript_supplements_native_post_action(
    tmp_path, command, gaps, required, forbidden,
):
    before = evidence.persist_turn(tmp_path, 0, state(task("step-1")))
    after = evidence.persist_turn(
        tmp_path, 1, state(task("step-1", "done")),
        native={"events": [], "gaps": gaps},
        events=[command_event({"command": command, "exit_code": 0})],
    )
    required_check = evidence.check_gate("post-action", before, after)
    assert required_check["verdict"] == required
    if forbidden == "fail":
        assert "turn-1:events" in required_check["evidence_refs"]
    assert evidence.check_gate("no-post-action", before, after)["verdict"] == forbidden


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
        normalized = command_event({
            "command": f"/bin/zsh -c {shlex.quote(command)}", "exit_code": 0,
        })
        assert normalized["action"] == "apply.review-command"
        return {**normalized, "action": "apply.review"}  # Legacy saved events.

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
    head_probe = command_event({
        "command": "/bin/zsh -c 'git rev-parse --short HEAD'", "exit_code": 0,
    })
    after_probe = evidence.persist_turn(tmp_path, 8, pending, events=[*failure, head_probe])
    compound = command_event({
        "command": "/bin/zsh -c 'git rev-parse --short HEAD && echo unknown'", "exit_code": 0,
    })
    after_compound = evidence.persist_turn(tmp_path, 9, pending, events=[*failure, compound])
    check = "review-failure-stop"
    assert evidence.check_gate(check, before, absent)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate(check, before, stopped)["verdict"] == "pass"
    assert evidence.check_gate(check, before, continued)["verdict"] == "fail"
    assert evidence.check_gate(check, before, post)["verdict"] == "fail"
    assert evidence.check_gate(check, before, reviewed_again)["verdict"] == "fail"
    assert evidence.check_gate(check, before, unclassified)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate(check, before, unknown_result)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate(check, before, after_probe)["verdict"] == "pass"
    assert evidence.check_gate(check, before, after_compound)["verdict"] == "insufficient_evidence"
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


def test_native_timing_prefers_precise_spans_and_keeps_legacy_only_folders(tmp_path):
    baseline = native_trace.snapshot(tmp_path)
    root = tmp_path / ".spex"
    spec = root / "specs" / "eval-spec"
    spec.mkdir(parents=True)
    shared = root / "eval-logs"
    shared.mkdir()
    (root / "debug.log").write_text(cli_log("list"))
    (shared / "debug.log").write_text(cli_log("list"))
    (spec / "debug.log").write_text(cli_log("list"))
    (shared / "trace.jsonl").write_text(json.dumps({
        "schema_version": 1, "start_time_unix_nano": 1, "end_time_unix_nano": 9,
    }) + "\n")
    checkpoint, evidence = native_trace.window(tmp_path, baseline)
    assert len(evidence["events"]) == 3
    assert [event["log"] for event in evidence["timing_events"]] == [
        "eval-logs/trace.jsonl", "debug.log", "specs/eval-spec/debug.log",
    ]
    assert evidence["timing_events"][0]["end_ns"] == 9
    _, after = native_trace.window(tmp_path, checkpoint)
    assert "timing_events" not in after and after["events"] == []
