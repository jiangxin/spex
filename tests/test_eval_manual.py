"""Fast checks for manual batch dispatch and batch grade import."""

import argparse
import json
import re
import sys
from pathlib import Path

import collect_handoff
import host_turn_timer
import manual
import manual_batch
import pytest
import run

from tests.conftest import manual_action

SOP_SKILL = (
    Path(__file__).resolve().parent.parent
    / ".agents" / "skills" / "spex-eval" / "SKILL.md"
)
EVAL_README = (
    Path(__file__).resolve().parent.parent / "eval" / "spex" / "README.md"
)
ADAPTERS_README = (
    Path(__file__).resolve().parent.parent
    / "eval" / "spex" / "adapters" / "README.md"
)
# Fenced eval docs and the minimum number of runner invocations each must
# keep, so trimming examples cannot silently empty the assertions.
DOC_FENCES = [
    pytest.param(SOP_SKILL, 6, id="skill"),
    pytest.param(EVAL_README, 8, id="eval-readme"),
    pytest.param(ADAPTERS_README, 1, id="adapters-readme"),
]
SOP_FENCE_RE = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)
SOP_ALTERNATION_RE = re.compile(r"\[[^\]\n]*\|[^\]\n]*\]")

GRADE_ROW = {
    "criterion_id": "coverage", "score": 2, "verdict": "pass",
    "reason": "The saved state shows the expected specification.",
    "evidence_refs": ["turn-1:state"],
}


def build_sandbox(
    root: Path, keys: list[str], jobs: int, monkeypatch, turns: int = 1,
) -> Path:
    """Publish the minimal queue, trial metadata, and env script that dispatch reads."""
    sandbox = (root / "runs" / "2026-11-18-09-21-00").resolve()
    entries = {}
    queue = {}
    for key in keys:
        suite, case = key.split("/")
        trial = sandbox / suite / case
        (trial / "workspace" / "repo").mkdir(parents=True, exist_ok=True)
        (trial / "trial.json").write_text(json.dumps({
            "suite": suite, "case_id": case, "sandbox": str(sandbox),
            "collection": "manual", "trial_directory": str(trial / "workspace"),
            "spex_ref": "0" * 40, "session": "", "turn_results": [],
            "verdict": "pending", "execution": {"jobs": jobs},
            "host": "qoder", "host_version": "1", "model": "unknown",
            "invocation": "native",
            "case": {"turns": [{"input": f"turn {n}"} for n in range(1, turns + 1)]},
        }), encoding="utf-8")
        run.write_env_script(sandbox, suite, case, {})
        entries[key] = {"trial": key, "environment": {}}
        queue[key] = {"status": "pending"}
    manual_batch.write(sandbox / "batch-index.json", entries)
    manual_batch.write(sandbox / "queue.json", queue)
    monkeypatch.setattr(run, "RUNS", root / "runs")
    return sandbox


def build_prepare_sandbox(
    root: Path, keys: list[str], monkeypatch,
) -> tuple[Path, list]:
    """Publish only the batch index and fake prepare_case with a minimal handoff."""
    sandbox = (root / "runs" / "2026-11-18-09-21-00").resolve()
    sandbox.mkdir(parents=True)
    manual_batch.write(sandbox / "batch-index.json", {
        key: {"trial": key, "environment": {}} for key in keys
    })

    def fake_prepare(case, _sandbox, _args, *, allocated):
        assert not allocated
        return {"next_input": f"turn 1 of {case.id}", "environment": {}}

    monkeypatch.setattr(run, "resolve_sandbox", lambda path=None: sandbox)
    monkeypatch.setattr(run, "resolve_spex_ref", lambda source, ref: "0" * 40)
    monkeypatch.setattr(run, "prepare_case", fake_prepare)
    cases = [run.Case("example", {"id": key.split("/")[1]}, Path(".")) for key in keys]
    return sandbox, cases


def prepare_args(sandbox: Path, *extra: str):
    """Parse one full-batch prepare command against an explicit sandbox."""
    return run.parser().parse_args([
        "prepare", "--all", "--host", "qoder", "--sandbox", str(sandbox), *extra,
    ])


def finish_turn(sandbox: Path, key: str, turn: int) -> None:
    """Record one collected turn so the next input becomes the pending turn."""
    suite, case = key.split("/")
    trial = sandbox / suite / case / "trial.json"
    metadata = run.read_json(trial)
    metadata["turn_results"] = [{"turn": number} for number in range(1, turn + 1)]
    run.write_json(trial, metadata)
    collect_handoff.handoff_reply(sandbox, suite, case, turn).write_text("done", encoding="utf-8")


def set_verdict(sandbox: Path, key: str, verdict: str, *, hard: bool = False) -> None:
    """Store the verdict an imported grade or a host failure would leave behind."""
    suite, case = key.split("/")
    path = sandbox / suite / case / "trial.json"
    metadata = run.read_json(path)
    metadata["verdict"] = verdict
    if hard:
        metadata["hard_verdict"] = verdict
    run.write_json(path, metadata)


def test_full_queue_names_occupants_and_keeps_the_refused_case_pending(
    tmp_path, monkeypatch,
):
    keys = ["example/alpha", "example/bravo", "example/charlie"]
    sandbox = build_sandbox(tmp_path, keys, 2, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    manual_action(sandbox, "claim", "example/bravo")

    with pytest.raises(ValueError) as error:
        manual_action(sandbox, "claim", "example/charlie")

    message = str(error.value)
    assert message.startswith("All configured trial slots are occupied")
    assert "jobs=2" in message
    assert "example/alpha, example/bravo" in message
    queue = manual_batch.read(sandbox / "queue.json")
    assert queue["example/charlie"]["status"] == "pending"
    assert queue["example/alpha"]["status"] == "running"
    assert queue["example/bravo"]["status"] == "running"


def test_claim_rejects_a_case_that_is_not_pending(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")

    with pytest.raises(ValueError, match="Case is already running: example/alpha"):
        manual_action(sandbox, "claim", "example/alpha")


def test_running_keys_preserves_queue_insertion_order():
    queue = {
        "docs/beta": {"status": "running"},
        "docs/alpha": {"status": "completed"},
        "docs/gamma": {"status": "running"},
        "docs/delta": {"status": "pending"},
    }
    assert manual.running_keys(queue) == ["docs/beta", "docs/gamma"]


def test_active_keys_skips_rows_with_a_released_slot_in_queue_order():
    queue = {
        "docs/beta": {"status": "running"},
        "docs/alpha": {"status": "running", "slot_released": True},
        "docs/gamma": {"status": "running", "slot_released": False},
        "docs/delta": {"status": "completed"},
    }
    assert manual.active_keys(queue) == ["docs/beta", "docs/gamma"]


def test_claim_row_counts_only_trials_that_are_still_executing():
    queue = {
        "docs/a": {"status": "running"},
        "docs/b": {"status": "running", "slot_released": True},
        "docs/c": {"status": "running"},
        "docs/d": {"status": "running"},
        "docs/e": {"status": "pending"},
    }
    manual.claim_row(queue, "docs/e", 4)  # The graded trial no longer holds a slot.

    with pytest.raises(ValueError) as error:
        manual.claim_row(queue, "docs/e", 3)
    assert str(error.value) == (
        "All configured trial slots are occupied (jobs=3): docs/a, docs/c, docs/d"
    )
    assert queue["docs/e"]["status"] == "pending"


def test_legacy_queue_rows_without_the_key_still_occupy_a_slot():
    queue = {
        "docs/a": {"status": "running"},
        "docs/b": {"status": "running"},
        "docs/c": {"status": "pending"},
    }
    assert not any("slot_released" in row for row in queue.values())

    with pytest.raises(ValueError, match=r"occupied \(jobs=2\): docs/a, docs/b"):
        manual.claim_row(queue, "docs/c", 2)


def test_status_stays_non_terminal_while_a_released_slot_awaits_grades(
    tmp_path, monkeypatch,
):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    set_verdict(sandbox, "example/alpha", "pass")  # Collected and exported, not graded.
    queue = manual_batch.read(sandbox / "queue.json")
    queue["example/alpha"]["slot_released"] = True
    manual_batch.write(sandbox / "queue.json", queue)

    payload, code = manual_action(sandbox, "status", "--require-terminal")
    assert code == 1
    assert payload["terminal"] is False
    assert payload["cases"]["example/alpha"]["slot_released"] is True

    set_verdict(sandbox, "example/alpha", "pass", hard=True)
    _, code = manual_action(sandbox, "complete", "example/alpha")
    assert code == 0

    payload, code = manual_action(sandbox, "status", "--require-terminal")
    assert code == 0
    assert payload["terminal"] is True


def test_claim_row_reports_completed_status_and_full_queue():
    with pytest.raises(ValueError, match="Case is already completed: docs/alpha"):
        manual.claim_row({"docs/alpha": {"status": "completed"}}, "docs/alpha", 4)

    queue = {
        "docs/a": {"status": "running"},
        "docs/b": {"status": "running"},
        "docs/c": {"status": "pending"},
    }
    with pytest.raises(ValueError) as error:
        manual.claim_row(queue, "docs/c", 2)
    assert str(error.value) == (
        "All configured trial slots are occupied (jobs=2): docs/a, docs/b"
    )
    assert queue["docs/c"]["status"] == "pending"


def test_parser_lists_the_dispatch_command(capsys):
    with pytest.raises(SystemExit) as exit_info:
        manual.parser().parse_args(["--help"])
    assert exit_info.value.code == 0
    assert "dispatch" in capsys.readouterr().out


def test_dispatch_claims_and_starts_a_pending_turn(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 2, monkeypatch)
    bundle, code = manual_action(
        sandbox, "dispatch", "example/alpha", "--session", "sess-1", "--turn", "1",
    )
    assert code == 0
    trial = sandbox / "example" / "alpha"
    assert bundle == {
        "case": "example/alpha",
        "turn": 1,
        "session": "sess-1",
        "trial": str(trial),
        "workspace": str(trial / "workspace" / "repo"),
        "skill": str(trial / "workspace" / "repo" / ".agents" / "skills" / "spex"),
        "env_script": str(sandbox / "_handoff" / "env-example-alpha.sh"),
        "reply": str(sandbox / "_handoff" / "example-alpha-turn1.txt"),
        "staging_reply": str(sandbox / "_handoff" / "example-alpha-turn1.txt.staging"),
        "next_input": "turn 1",
    }
    assert manual_batch.read(sandbox / "queue.json")["example/alpha"] == {
        "status": "running", "dispatch": {"turn": 1, "session": "sess-1"},
    }
    assert host_turn_timer.pending_path(Path(bundle["reply"])).is_file()


def test_dispatch_warns_when_a_staging_reply_predates_the_timer(
    tmp_path, monkeypatch, capsys,
):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    staging = sandbox / "_handoff" / "example-alpha-turn1.txt.staging"
    staging.write_text("already answered", encoding="utf-8")

    _, code = manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")

    assert code == 0
    assert "under-measure" in capsys.readouterr().err


def test_dispatch_reuses_a_running_slot_for_the_next_turn(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch, turns=2)
    manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")
    finish_turn(sandbox, "example/alpha", 1)

    bundle, code = manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")

    assert code == 0
    assert bundle["turn"] == 2
    assert bundle["next_input"] == "turn 2"
    assert bundle["reply"] == str(sandbox / "_handoff" / "example-alpha-turn2.txt")
    assert manual_batch.read(sandbox / "queue.json")["example/alpha"] == {
        "status": "running", "dispatch": {"turn": 2, "session": "sess-1"},
    }


def test_dispatch_rejects_a_turn_mismatch_without_touching_the_queue(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch, turns=2)
    before = (sandbox / "queue.json").read_bytes()

    with pytest.raises(ValueError, match="No next input for turn 2; pending turn is 1"):
        manual_action(
            sandbox, "dispatch", "example/alpha", "--session", "sess-1", "--turn", "2",
        )

    assert (sandbox / "queue.json").read_bytes() == before


def test_dispatch_rejects_a_conflicting_or_invalid_session(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")
    before = (sandbox / "queue.json").read_bytes()

    for session in ("sess-2", "not a session"):
        with pytest.raises(ValueError, match="same valid session ID"):
            manual_action(sandbox, "dispatch", "example/alpha", "--session", session)
        assert (sandbox / "queue.json").read_bytes() == before


def test_dispatch_restores_the_row_when_the_timer_fails(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    before = (sandbox / "queue.json").read_bytes()

    def fail(*_arguments):
        raise RuntimeError("timer unavailable")

    monkeypatch.setattr(host_turn_timer, "start_timer", fail)
    with pytest.raises(RuntimeError, match="timer unavailable"):
        manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")

    assert (sandbox / "queue.json").read_bytes() == before
    assert manual_batch.read(sandbox / "queue.json")["example/alpha"] == {"status": "pending"}


def test_dispatch_removes_the_timer_when_the_queue_write_fails(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    before = (sandbox / "queue.json").read_bytes()
    timer = host_turn_timer.pending_path(sandbox / "_handoff" / "example-alpha-turn1.txt")

    def fail(*_arguments):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(manual_batch, "write", fail)
        with pytest.raises(OSError, match="disk full"):
            manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")

    assert not timer.exists()
    assert (sandbox / "queue.json").read_bytes() == before
    bundle, code = manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")
    assert code == 0
    assert bundle["turn"] == 1
    assert timer.is_file()


def test_dispatch_rejects_a_turn_whose_reply_already_exists(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    bundle, _ = manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")
    Path(bundle["reply"]).write_text("done", encoding="utf-8")
    before = (sandbox / "queue.json").read_bytes()

    with pytest.raises(ValueError, match="Turn already started"):
        manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")

    assert (sandbox / "queue.json").read_bytes() == before


def test_dispatch_requires_the_prepared_env_script(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    (sandbox / "_handoff" / "env-example-alpha.sh").unlink()
    before = (sandbox / "queue.json").read_bytes()

    with pytest.raises(ValueError, match="re-run prepare"):
        manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")

    assert (sandbox / "queue.json").read_bytes() == before


@pytest.mark.parametrize("defect", ["other-case", "other-dir", "symlink", "blank", "utf-8"])
def test_stop_rejects_invalid_staging_without_changing_the_turn(
    tmp_path, monkeypatch, defect,
):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    bundle, code = manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")
    assert code == 0
    reply = Path(bundle["reply"])
    staged = Path(bundle["staging_reply"])
    timer = host_turn_timer.pending_path(reply)
    queue = sandbox / "queue.json"
    queue_before, timer_before = queue.read_bytes(), timer.read_bytes()
    source = staged
    if defect == "other-case":
        source = reply.with_name("example-bravo-turn1.txt.staging")
    elif defect == "other-dir":
        source = tmp_path / staged.name

    if defect == "symlink":
        target = staged.with_suffix(".original")
        target.write_text("wrong reply", encoding="utf-8")
        source.symlink_to(target)
    else:
        source.write_bytes({"blank": b" \n", "utf-8": b"\xff"}.get(defect, b"wrong reply"))

    monkeypatch.setattr(run, "resolve_sandbox", lambda path=None: sandbox)
    monkeypatch.setattr(sys, "argv", [
        "manual.py", "--sandbox", str(sandbox), "stop", "example/alpha", "1",
        "--reply-file", str(source),
    ])
    assert manual.main() == 2
    assert not reply.exists()
    assert queue.read_bytes() == queue_before
    assert timer.read_bytes() == timer_before

    staged.unlink(missing_ok=True)
    staged.write_text("done", encoding="utf-8")
    result, code = manual_action(
        sandbox, "stop", "example/alpha", "1", "--reply-file", str(staged),
    )
    assert code == 0
    assert result["action"] == "stop"
    assert reply.read_text(encoding="utf-8") == "done"
    assert not timer.exists()


def test_dispatch_reuses_slots_released_by_trials_awaiting_grades(tmp_path, monkeypatch):
    keys = [
        "example/alpha", "example/bravo", "example/charlie",
        "example/delta", "example/echo", "example/foxtrot",
    ]
    sandbox = build_sandbox(tmp_path, keys, 4, monkeypatch)
    for key in keys[:4]:
        manual_action(sandbox, "claim", key)
    queue = manual_batch.read(sandbox / "queue.json")
    queue["example/alpha"]["slot_released"] = True  # Collected and exported.
    manual_batch.write(sandbox / "queue.json", queue)

    bundle, code = manual_action(sandbox, "dispatch", "example/echo", "--session", "sess-1")
    assert code == 0
    assert bundle["turn"] == 1
    assert manual_batch.read(sandbox / "queue.json")["example/echo"]["status"] == "running"

    with pytest.raises(ValueError) as error:
        manual_action(sandbox, "dispatch", "example/foxtrot", "--session", "sess-1")
    message = str(error.value)
    assert message == (
        "All configured trial slots are occupied (jobs=4): "
        "example/bravo, example/charlie, example/delta, example/echo"
    )
    assert "example/alpha" not in message


def test_advance_marks_a_collected_final_turn_as_slot_released(
    tmp_path, monkeypatch,
):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    bundle, _ = manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")
    Path(bundle["reply"]).write_text("done", encoding="utf-8")
    monkeypatch.setattr(run, "manual_result", lambda *_arguments: {"next_input": None})
    monkeypatch.setattr(run, "export_judge", lambda _output: {
        "hard_verdict": "pass", "prompt": "judge-prompt", "trial": "trial",
    })

    payload, code = manual.advance_action(sandbox)

    assert code == 0
    assert [item["case"] for item in payload["exported"]] == ["example/alpha"]
    row = manual_batch.read(sandbox / "queue.json")["example/alpha"]
    assert row == {"status": "running", "slot_released": True}

    set_verdict(sandbox, "example/alpha", "pass", hard=True)
    result, code = manual_action(sandbox, "complete", "example/alpha")

    assert code == 0
    assert result == {"case": "example/alpha", "status": "completed", "verdict": "pass"}
    assert manual_batch.read(sandbox / "queue.json")["example/alpha"] == {
        "status": "completed", "verdict": "pass",
    }


def test_collect_retry_still_marks_the_collected_final_turn(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    manual_action(sandbox, "dispatch", "example/alpha", "--session", "sess-1")
    finish_turn(sandbox, "example/alpha", 1)
    set_verdict(sandbox, "example/alpha", "pass")  # Collection committed; retry is safe.
    entries = manual_batch.read(sandbox / "batch-index.json")
    output, trial, metadata = manual.load_trial(sandbox, "example/alpha", entries)
    queue = manual_batch.read(sandbox / "queue.json")

    with manual_batch.locked(sandbox):
        manual.turn_action(
            manual.parse_arguments([
                "--sandbox", str(sandbox), "collect", "example/alpha", "1",
            ]), sandbox, output, trial, metadata, queue["example/alpha"], {},
            lambda: None,
        )

    assert queue["example/alpha"]["slot_released"] is True


def test_complete_all_releases_graded_slots_and_keeps_the_rest(tmp_path, monkeypatch):
    """Complete graded running rows only and free their slots for new claims."""
    keys = ["example/alpha", "example/bravo", "example/charlie"]
    sandbox = build_sandbox(tmp_path, keys, 2, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    set_verdict(sandbox, "example/alpha", "pass", hard=True)
    manual_action(sandbox, "claim", "example/bravo")  # Graded later, still occupies a slot.
    with pytest.raises(ValueError, match="All configured trial slots are occupied"):
        manual_action(sandbox, "claim", "example/charlie")

    payload, code = manual_action(sandbox, "complete", "--all")

    assert code == 0
    assert payload == {
        "completed": [{"case": "example/alpha", "verdict": "pass"}],
        "skipped": [
            {"case": "example/bravo", "reason": "not_graded"},
            {"case": "example/charlie", "reason": "not_running"},
        ],
        "errors": [],
    }
    queue = manual_batch.read(sandbox / "queue.json")
    assert queue["example/alpha"] == {"status": "completed", "verdict": "pass"}
    assert queue["example/bravo"] == {"status": "running"}
    assert queue["example/charlie"] == {"status": "pending"}
    # The released slot is claimable again without another complete round.
    assert manual_action(sandbox, "claim", "example/charlie")[1] == 0
    assert manual_batch.read(sandbox / "queue.json")["example/charlie"]["status"] == "running"


def test_complete_all_completes_a_host_failure_without_grades(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    set_verdict(sandbox, "example/alpha", "run_error")

    payload, code = manual_action(sandbox, "complete", "--all")

    assert code == 0
    assert payload["completed"] == [{"case": "example/alpha", "verdict": "run_error"}]
    assert payload["skipped"] == []
    assert payload["errors"] == []
    assert manual_batch.read(sandbox / "queue.json")["example/alpha"] == {
        "status": "completed", "verdict": "run_error",
    }


def test_complete_all_reports_a_corrupt_trial_and_continues(tmp_path, monkeypatch):
    keys = ["example/alpha", "example/bravo"]
    sandbox = build_sandbox(tmp_path, keys, 2, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    manual_action(sandbox, "claim", "example/bravo")
    set_verdict(sandbox, "example/bravo", "pass", hard=True)
    (sandbox / "example" / "alpha" / "trial.json").write_text("{not json", encoding="utf-8")

    payload, code = manual_action(sandbox, "complete", "--all")

    assert code == 1
    assert payload["completed"] == [{"case": "example/bravo", "verdict": "pass"}]
    assert [item["case"] for item in payload["errors"]] == ["example/alpha"]
    assert payload["errors"][0]["error"]
    queue = manual_batch.read(sandbox / "queue.json")
    assert queue["example/bravo"] == {"status": "completed", "verdict": "pass"}
    assert queue["example/alpha"]["status"] == "running"


def test_complete_all_skips_a_collected_trial_awaiting_grades(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    finish_turn(sandbox, "example/alpha", 1)
    set_verdict(sandbox, "example/alpha", "pass")  # Final turn collected, not graded.
    before = manual_batch.read(sandbox / "queue.json")

    payload, code = manual_action(sandbox, "complete", "--all")

    assert code == 0
    assert payload == {
        "completed": [],
        "skipped": [{"case": "example/alpha", "reason": "not_graded"}],
        "errors": [],
    }
    assert manual_batch.read(sandbox / "queue.json") == before


def test_complete_all_reports_a_corrupt_queue_row_and_continues(tmp_path, monkeypatch):
    keys = ["example/alpha", "example/bravo"]
    sandbox = build_sandbox(tmp_path, keys, 2, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    set_verdict(sandbox, "example/alpha", "pass", hard=True)
    queue = manual_batch.read(sandbox / "queue.json")
    queue["example/bravo"] = {}  # A damaged row must not abort the sweep.
    manual_batch.write(sandbox / "queue.json", queue)

    payload, code = manual_action(sandbox, "complete", "--all")

    assert code == 1
    assert payload["completed"] == [{"case": "example/alpha", "verdict": "pass"}]
    assert [item["case"] for item in payload["errors"]] == ["example/bravo"]


def test_single_case_complete_keeps_the_graded_release(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    set_verdict(sandbox, "example/alpha", "pass", hard=True)

    result, code = manual_action(sandbox, "complete", "example/alpha")

    assert code == 0
    assert result == {"case": "example/alpha", "status": "completed", "verdict": "pass"}
    assert manual_action(sandbox, "status", "--require-terminal") == (
        {"terminal": True, "cases": {"example/alpha": {
            "status": "completed", "verdict": "pass",
        }}},
        0,
    )


def test_single_case_complete_keeps_the_grade_gate(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    manual_action(sandbox, "claim", "example/alpha")
    set_verdict(sandbox, "example/alpha", "pass")

    with pytest.raises(ValueError, match="^Import semantic grades before completing"):
        manual_action(sandbox, "complete", "example/alpha")

    assert manual_batch.read(sandbox / "queue.json")["example/alpha"]["status"] == "running"


@pytest.mark.parametrize(("argv", "message"), [
    ([], "Pass one suite/case ID or --all"),
    (["example/alpha", "--all"], "--all cannot be combined with a single case"),
])
def test_complete_requires_exactly_one_target(capsys, argv, message):
    with pytest.raises(SystemExit) as exit_info:
        manual.parse_arguments(["--sandbox", "runs/s", "complete", *argv])

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(("argv", "attributes"), [
    (["advance"], {}),
    (["status", "--require-terminal"], {"require_terminal": True}),
    (["init", "example/alpha"], {"cases": ["example/alpha"]}),
    (["claim", "example/alpha"], {"case": "example/alpha"}),
    (["start", "example/alpha", "2", "--session", "sess-1"],
     {"turn": 2, "session": "sess-1"}),
    (["dispatch", "example/alpha", "--session", "sess-1", "--turn", "2"],
     {"turn": 2, "session": "sess-1"}),
    (["stop", "example/alpha", "1"], {"turn": 1, "reply_file": None}),
    (["collect", "example/alpha", "1"], {"turn": 1}),
    (["fail", "example/alpha", "--reason", "exited"], {"reason": "exited"}),
    (["exec", "--", "spex", "status"], {"case": "spex", "argv": ["status"]}),
    (["wait", "--any"], {"any": True, "timeout": 900}),
    (["complete", "example/alpha"], {"case": "example/alpha", "all_cases": False}),
])
def test_parse_arguments_survives_every_subcommand(argv, attributes):
    """Only complete's target rule may inspect the parsed namespace."""
    args = manual.parse_arguments(["--sandbox", "runs/s", *argv])

    assert args.command == argv[0]
    assert str(args.sandbox) == "runs/s"
    for name, value in attributes.items():
        assert getattr(args, name) == value


def test_manual_initialize_shares_the_batch_bootstrap(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    (sandbox / "queue.json").unlink()

    result, code = manual_action(sandbox, "init", "example/alpha")

    assert code == 0
    assert result == {"terminal": False, "cases": {"example/alpha": {"status": "pending"}}}
    assert manual_batch.read(sandbox / "queue.json") == {"example/alpha": {"status": "pending"}}
    # An existing queue is reported as-is instead of reloading every trial.
    (sandbox / "example" / "alpha" / "trial.json").unlink()
    assert manual_action(sandbox, "init", "example/alpha")[0] == result


def test_manual_initialize_validates_trials_before_writing_the_queue(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha"], 1, monkeypatch)
    (sandbox / "queue.json").unlink()
    run.write_json(
        sandbox / "example" / "alpha" / "trial.json", {"suite": "other", "case_id": "alpha"},
    )

    with pytest.raises(ValueError, match="identity does not match"):
        manual_action(sandbox, "init", "example/alpha")

    assert not (sandbox / "queue.json").exists()


def test_manual_batch_initialize_rejects_duplicate_and_unselected_keys(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/alpha", "example/bravo"], 1, monkeypatch)
    (sandbox / "queue.json").unlink()

    with manual_batch.locked(sandbox):
        for keys in (
            ["example/alpha", "example/bravo", "example/alpha"],
            ["example/alpha"],
            ["example/alpha", "example/bravo", "example/charlie"],
        ):
            with pytest.raises(ValueError, match="exact selected"):
                manual_batch.initialize(sandbox, keys)

    assert not (sandbox / "queue.json").exists()


def test_manual_batch_initialize_writes_pending_rows_in_key_order(tmp_path, monkeypatch):
    sandbox = build_sandbox(tmp_path, ["example/bravo", "example/alpha"], 1, monkeypatch)
    (sandbox / "queue.json").unlink()

    with manual_batch.locked(sandbox):
        result = manual_batch.initialize(sandbox, ["example/alpha", "example/bravo"])

    assert result == {"status": "initialized", "cases": 2}
    assert manual_batch.read(sandbox / "queue.json") == {
        "example/alpha": {"status": "pending"},
        "example/bravo": {"status": "pending"},
    }


def test_prepare_all_init_writes_the_queue_and_aliases_case_ids(tmp_path, monkeypatch):
    sandbox, cases = build_prepare_sandbox(
        tmp_path, ["example/alpha", "example/bravo"], monkeypatch,
    )

    payload = run.prepare_all(cases, prepare_args(sandbox, "--init"))

    assert payload["queue_init"] == {"status": "initialized", "cases": 2}
    queue = manual_batch.read(sandbox / "queue.json")
    assert list(queue) == ["example/alpha", "example/bravo"]
    assert all(row == {"status": "pending"} for row in queue.values())
    assert [item["id"] for item in payload["prepared"]] == ["alpha", "bravo"]
    assert all(item["id"] == item["case"] for item in payload["prepared"])


def test_prepare_all_init_keeps_an_existing_queue(tmp_path, monkeypatch):
    sandbox, cases = build_prepare_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    manual_batch.write(sandbox / "queue.json", {"example/alpha": {"status": "running"}})
    before = (sandbox / "queue.json").read_bytes()

    payload = run.prepare_all(cases, prepare_args(sandbox, "--init"))

    assert payload["queue_init"] == {"status": "existing", "cases": 1}
    assert (sandbox / "queue.json").read_bytes() == before


def test_prepare_all_init_skips_when_a_case_fails(tmp_path, monkeypatch):
    sandbox, cases = build_prepare_sandbox(
        tmp_path, ["example/alpha", "example/bravo"], monkeypatch,
    )

    def flaky(case, _sandbox, _args, *, allocated):
        if case.id == "bravo":
            raise ValueError("fixture is missing")
        return {"next_input": "turn 1", "environment": {}}

    monkeypatch.setattr(run, "prepare_case", flaky)
    payload = run.prepare_all(cases, prepare_args(sandbox, "--init"))

    assert payload["queue_init"] == {"status": "skipped", "reason": "prepare_errors"}
    assert [item["id"] for item in payload["prepared"]] == ["alpha"]
    assert payload["errors"] == [
        {"suite": "example", "id": "bravo", "case": "bravo", "error": "fixture is missing"},
    ]
    assert not (sandbox / "queue.json").exists()


def test_prepare_all_init_reports_a_batch_index_mismatch_as_skipped(tmp_path, monkeypatch):
    sandbox, cases = build_prepare_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    # A seeded or resumed sandbox legitimately keeps keys from earlier prepares.
    manual_batch.write(sandbox / "batch-index.json", {
        "example/alpha": {"trial": "example/alpha", "environment": {}},
        "example/bravo": {"trial": "example/bravo", "environment": {}},
    })

    payload = run.prepare_all(cases, prepare_args(sandbox, "--init"))

    assert payload["queue_init"]["status"] == "skipped"
    assert payload["queue_init"]["reason"] == "batch_mismatch"
    assert "example/bravo" in payload["queue_init"]["detail"]
    assert [item["id"] for item in payload["prepared"]] == ["alpha"]
    assert payload["sandbox"] == str(sandbox)
    assert not (sandbox / "queue.json").exists()


def test_prepare_all_without_init_leaves_the_queue_untouched(tmp_path, monkeypatch):
    sandbox, cases = build_prepare_sandbox(tmp_path, ["example/alpha"], monkeypatch)

    payload = run.prepare_all(cases, prepare_args(sandbox))

    assert "queue_init" not in payload
    assert not (sandbox / "queue.json").exists()


def test_single_case_prepare_rejects_init(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "run.py", "prepare", "--host", "qoder", "--init", "--suite", "example",
    ])

    with pytest.raises(SystemExit):
        run.main()

    assert "--init requires --all" in capsys.readouterr().err


def build_import_sandbox(
    root: Path, keys: list[str], monkeypatch, *, stub_sandbox: bool = True,
) -> Path:
    """Publish minimal gradable trials, the matching rubric, and a batch index."""
    sandbox = (root / "runs" / "2026-11-18-09-21-00").resolve()
    suite = root / "suites" / "example"
    suite.mkdir(parents=True)
    rubrics = {"version": 1, "cases": {}}
    entries = {}
    for key in keys:
        _, case = key.split("/")
        trial = sandbox / "example" / case
        trial.mkdir(parents=True)
        state = {"specs": {"demo": {"spec.md": "# Demo", "todo.json": "[]"}}}
        run.write_json(trial / "turn-1.json", {
            "turn": 1,
            "artifacts": {"state": {
                "id": "turn-1:state", "sha256": run.digest(run.encode(state)),
                "value": state,
            }},
        })
        run.write_json(trial / "trial.json", {
            "suite": "example", "case_id": case, "verdict": "pass", "turn_results": [],
        })
        (trial / "judge-prompt.txt").write_text("prompt", encoding="utf-8")
        rubrics["cases"][case] = [{
            "id": "coverage", "turn": 1, "requires": ["state"], "threshold": 2,
            "anchors": ["Missing", "Partial", "Complete"],
        }]
        entries[key] = {"trial": key, "environment": {}}
    (suite / "rubrics.json").write_text(json.dumps(rubrics), encoding="utf-8")
    manual_batch.write(sandbox / "batch-index.json", entries)
    monkeypatch.setattr(run, "RUNS", root / "runs")
    monkeypatch.setattr(run, "SUITES", root / "suites")
    if stub_sandbox:
        def check_sandbox_path(path=None):
            # The CLI path must reach batch import, not be dropped on the way.
            assert path is None or Path(path) == sandbox, f"unexpected sandbox: {path}"
            return sandbox

        monkeypatch.setattr(run, "resolve_sandbox", check_sandbox_path)
    return sandbox


def write_grades(sandbox: Path, key: str, raw: str | None = None) -> Path:
    """Save one case's grades under the default batch handoff directory."""
    suite, case = key.split("/")
    path = run.grades_path(sandbox / "_handoff", suite, case)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw if raw is not None else json.dumps([GRADE_ROW]), encoding="utf-8")
    return path


def import_all(sandbox: Path, *extra: str) -> dict:
    """Run one batch grade import without going through the process wrapper."""
    return run.execute(run.parser().parse_args([
        "import-grades", "--all", "--sandbox", str(sandbox), *extra,
    ]))


def run_cli(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["run.py", *argv])
    return run.main()


def test_import_grades_all_imports_saved_grades_and_skips_the_rest(
    tmp_path, monkeypatch, capsys,
):
    # Deliberately unsorted so a sorted() walk would reorder the payload.
    keys = ["example/charlie", "example/alpha", "example/bravo"]
    sandbox = build_import_sandbox(tmp_path, keys, monkeypatch)
    # charlie is already graded, and its packet is gone: the graded check wins.
    run.write_json(sandbox / "example" / "charlie" / "judge.json", {"verdict": "pass"})
    (sandbox / "example" / "charlie" / "judge-prompt.txt").unlink()
    write_grades(sandbox, "example/charlie")
    before = (sandbox / "example" / "charlie" / "judge.json").read_bytes()
    write_grades(sandbox, "example/bravo")
    # alpha stays without grades.

    code = run_cli(monkeypatch, "import-grades", "--all", "--sandbox", str(sandbox))

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "imported": [{"case": "example/bravo", "verdict": "pass", "results": 1}],
        "skipped": [
            {"case": "example/charlie", "reason": "already_graded"},
            {"case": "example/alpha", "reason": "no_grades"},
        ],
        "errors": [],
    }
    assert (sandbox / "example" / "charlie" / "judge.json").read_bytes() == before
    judge = run.read_json(sandbox / "example" / "bravo" / "judge.json")
    assert (judge["source"], judge["host"], judge["model"]) == ("external", "unknown", "unknown")
    assert judge["verdict"] == "pass"
    assert run.read_json(sandbox / "example" / "bravo" / "trial.json")["verdict"] == "pass"


def test_import_grades_all_keeps_batch_index_insertion_order(tmp_path, monkeypatch):
    keys = ["example/charlie", "example/alpha", "example/bravo"]
    sandbox = build_import_sandbox(tmp_path, keys, monkeypatch)
    for key in keys:
        write_grades(sandbox, key)

    payload = import_all(sandbox)

    assert [item["case"] for item in payload["imported"]] == keys
    assert payload["skipped"] == []
    assert payload["errors"] == []


def test_import_grades_all_continues_after_a_corrupt_grade_file(
    tmp_path, monkeypatch, capsys,
):
    keys = ["example/alpha", "example/bravo"]
    sandbox = build_import_sandbox(tmp_path, keys, monkeypatch)
    write_grades(sandbox, "example/alpha", "{not json")
    write_grades(sandbox, "example/bravo")

    code = run_cli(
        monkeypatch, "import-grades", "--all", "--sandbox", str(sandbox),
        "--host", "qoder", "--judge-duration-ms", "2500",
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == [{"case": "example/bravo", "verdict": "pass", "results": 1}]
    assert [item["case"] for item in payload["errors"]] == ["example/alpha"]
    assert payload["errors"][0]["error"]
    assert not (sandbox / "example" / "alpha" / "judge.json").exists()
    judge = run.read_json(sandbox / "example" / "bravo" / "judge.json")
    assert (judge["host"], judge["model"]) == ("qoder", "unknown")
    performance = run.read_json(sandbox / "example" / "bravo" / "performance.json")
    assert performance["judge"]["duration_ms"] == 2500


@pytest.mark.parametrize("raw", [
    "{}",
    '{"results": []}',
    json.dumps([{**GRADE_ROW, "criterion_id": "unknown"}]),
])
def test_import_grades_all_rejects_a_grade_contract_violation(
    tmp_path, monkeypatch, capsys, raw,
):
    """A parseable payload that breaks the grades contract stays retryable."""
    keys = ["example/alpha", "example/bravo"]
    sandbox = build_import_sandbox(tmp_path, keys, monkeypatch)
    write_grades(sandbox, "example/alpha", raw)
    write_grades(sandbox, "example/bravo")

    code = run_cli(monkeypatch, "import-grades", "--all", "--sandbox", str(sandbox))

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == [{"case": "example/bravo", "verdict": "pass", "results": 1}]
    assert [item["case"] for item in payload["errors"]] == ["example/alpha"]
    assert not (sandbox / "example" / "alpha" / "judge.json").exists()


def test_import_grades_all_skips_a_case_without_a_judge_packet(
    tmp_path, monkeypatch, capsys,
):
    sandbox = build_import_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    write_grades(sandbox, "example/alpha")
    (sandbox / "example" / "alpha" / "judge-prompt.txt").unlink()

    code = run_cli(monkeypatch, "import-grades", "--all", "--sandbox", str(sandbox))

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "imported": [],
        "skipped": [{"case": "example/alpha", "reason": "no_packet"}],
        "errors": [],
    }
    assert not (sandbox / "example" / "alpha" / "judge.json").exists()


def test_import_grades_all_ignores_grades_for_unselected_keys(tmp_path, monkeypatch):
    sandbox = build_import_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    write_grades(sandbox, "example/zulu")

    payload = import_all(sandbox)

    assert payload == {
        "imported": [],
        "skipped": [{"case": "example/alpha", "reason": "no_grades"}],
        "errors": [],
    }
    assert not (sandbox / "example" / "zulu").exists()


def test_import_grades_all_uses_an_explicit_grades_directory(tmp_path, monkeypatch):
    sandbox = build_import_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    elsewhere = tmp_path / "grades"
    elsewhere.mkdir()
    suite, case = "example", "alpha"
    (elsewhere / f"grades-{suite}-{case}.json").write_text(
        json.dumps([GRADE_ROW]), encoding="utf-8",
    )

    payload = import_all(sandbox, "--grades-dir", str(elsewhere))

    assert payload["imported"] == [{"case": "example/alpha", "verdict": "pass", "results": 1}]
    assert (sandbox / "example" / "alpha" / "judge.json").is_file()


def test_import_grades_all_resolves_a_relative_grades_directory_under_the_sandbox(
    tmp_path, monkeypatch,
):
    sandbox = build_import_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    write_grades(sandbox, "example/alpha")
    monkeypatch.chdir(tmp_path)

    payload = import_all(sandbox, "--grades-dir", "_handoff")

    assert payload["imported"] == [{"case": "example/alpha", "verdict": "pass", "results": 1}]


def test_import_grades_all_rejects_a_missing_grades_directory(tmp_path, monkeypatch):
    sandbox = build_import_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    missing = tmp_path / "nowhere"

    with pytest.raises(ValueError, match="Grades directory does not exist"):
        import_all(sandbox, "--grades-dir", str(missing))

    assert not (sandbox / "example" / "alpha" / "judge.json").exists()


def test_import_grades_all_rejects_a_missing_batch_index(tmp_path, monkeypatch):
    sandbox = build_import_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    (sandbox / "batch-index.json").unlink()

    with pytest.raises(ValueError, match="Batch index is missing"):
        import_all(sandbox)


def test_import_grades_all_rejects_a_non_object_batch_index(tmp_path, monkeypatch):
    sandbox = build_import_sandbox(tmp_path, ["example/alpha"], monkeypatch)
    manual_batch.write(sandbox / "batch-index.json", [{"trial": "example/alpha"}])

    with pytest.raises(ValueError, match="Batch index must be a JSON object"):
        import_all(sandbox)


def test_import_grades_all_resolves_the_cli_sandbox_without_a_stub(tmp_path, monkeypatch):
    sandbox = build_import_sandbox(
        tmp_path, ["example/alpha"], monkeypatch, stub_sandbox=False,
    )
    write_grades(sandbox, "example/alpha")
    verified = []
    monkeypatch.setattr(run, "verify_sandbox", lambda path, source: verified.append(path))

    payload = import_all(sandbox)

    assert payload["imported"] == [{"case": "example/alpha", "verdict": "pass", "results": 1}]
    assert verified == [sandbox]

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(ValueError, match="Expected a sandbox path under eval/spex/runs"):
        run.execute(run.parser().parse_args([
            "import-grades", "--all", "--sandbox", str(outside),
        ]))


@pytest.mark.parametrize(("argv", "message"), [
    (["import-grades", "--all"], "--all requires --sandbox"),
    (["import-grades", "--all", "--sandbox", "runs/s", "runs/s/trial"],
     "--all cannot be combined with a trial path"),
    (["import-grades", "--all", "--sandbox", "runs/s", "--grades", "g.json"],
     "--all cannot be combined with --grades"),
    (["import-grades"], "Pass a trial path or --all with --sandbox"),
    (["import-grades", "runs/s/trial"], "--grades is required unless --all is used"),
    (["import-grades", "runs/s/trial", "--grades", "g.json", "--sandbox", "runs/s"],
     "--sandbox requires --all"),
    (["import-grades", "runs/s/trial", "--grades", "g.json", "--grades-dir", "d"],
     "--grades-dir requires --all"),
])
def test_import_grades_rejects_incomplete_arguments(monkeypatch, capsys, argv, message):
    with pytest.raises(SystemExit) as exit_info:
        run_cli(monkeypatch, *argv)

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


def _parser_option_strings(parser: argparse.ArgumentParser) -> set[str]:
    """Collect option strings from a parser and all of its subparsers."""
    options: set[str] = set()
    for action in parser._actions:
        options.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                options |= _parser_option_strings(child)
    return options


def _sop_fences(doc: Path) -> list[str]:
    return SOP_FENCE_RE.findall(doc.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("doc", "min_invocations"), DOC_FENCES)
def test_sop_fences_have_no_alternation_pseudo_syntax(doc, min_invocations):
    """Fenced eval commands must stay runnable: no ``[a|b]`` placeholders."""
    blocks = _sop_fences(doc)
    assert blocks, f"expected fenced blocks in {doc.name}"
    offenders = SOP_ALTERNATION_RE.findall("\n".join(blocks))
    assert not offenders, (
        f"{doc.name}: replace [a|b] pseudo-syntax with one real form: "
        + ", ".join(sorted(set(offenders)))
    )


@pytest.mark.parametrize(("doc", "min_invocations"), DOC_FENCES)
def test_sop_fences_use_only_real_runner_and_manual_flags(doc, min_invocations):
    """Every ``--flag`` in a fenced run.py/manual.py call exists on its parser."""
    scripts = {"run.py": run.parser(), "manual.py": manual.parser()}
    known = {
        name: _parser_option_strings(parser) for name, parser in scripts.items()
    }
    invocations = 0
    for block in _sop_fences(doc):
        collapsed = re.sub(r"\\\n\s*", " ", block)
        for line in collapsed.splitlines():
            line = line.split("#", 1)[0]
            tokens = line.split()
            script = next(
                (name for name in scripts if any(name in t for t in tokens)),
                None,
            )
            if script is None:
                continue
            invocations += 1
            for token in tokens:
                if token.startswith("--"):
                    assert token in known[script], (
                        f"{doc.name}: {script} has no option {token!r} "
                        f"in: {line.strip()!r}"
                    )
    assert invocations >= min_invocations, (
        f"{doc.name}: expected ≥{min_invocations} fenced eval calls, "
        f"got {invocations}"
    )
