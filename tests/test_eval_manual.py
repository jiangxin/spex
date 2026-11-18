"""Fast checks for manual batch dispatch slot accounting."""

import json
from pathlib import Path

import manual
import manual_batch
import pytest
import run

from tests.conftest import manual_action


def build_sandbox(root: Path, keys: list[str], jobs: int, monkeypatch) -> Path:
    """Publish the minimal queue and trial metadata that claim accounting reads."""
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
        }), encoding="utf-8")
        entries[key] = {"trial": key, "environment": {}}
        queue[key] = {"status": "pending"}
    manual_batch.write(sandbox / "batch-index.json", entries)
    manual_batch.write(sandbox / "queue.json", queue)
    monkeypatch.setattr(run, "RUNS", root / "runs")
    return sandbox


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
