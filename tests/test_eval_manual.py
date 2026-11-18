"""Fast checks for manual batch dispatch slot accounting and one-call dispatch."""

import json
import sys
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
