"""Fast checks for manual batch dispatch slot accounting and one-call dispatch."""

import json
from pathlib import Path

import collect_handoff
import host_turn_timer
import manual
import manual_batch
import pytest
import run

from tests.conftest import manual_action


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


def finish_turn(sandbox: Path, key: str, turn: int) -> None:
    """Record one collected turn so the next input becomes the pending turn."""
    suite, case = key.split("/")
    trial = sandbox / suite / case / "trial.json"
    metadata = run.read_json(trial)
    metadata["turn_results"] = [{"turn": number} for number in range(1, turn + 1)]
    run.write_json(trial, metadata)
    collect_handoff.handoff_reply(sandbox, suite, case, turn).write_text("done", encoding="utf-8")


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
        "next_input": "turn 1",
    }
    assert manual_batch.read(sandbox / "queue.json")["example/alpha"] == {
        "status": "running", "dispatch": {"turn": 1, "session": "sess-1"},
    }
    assert host_turn_timer.pending_path(Path(bundle["reply"])).is_file()


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
