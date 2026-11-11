"""Check that the extended suite catches broken import and workflow behavior."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "eval" / "spex"
SUITE = EVAL / "suites" / "batch-import"
sys.path.insert(0, str(EVAL))
try:
    from evidence import EXPECTATIONS
    from workspace import git, prepare_trial, select_cases
finally:
    sys.path.pop(0)

spec = importlib.util.spec_from_file_location("batch_import_acceptance", SUITE / "acceptance.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def test_extended_cases_have_rubrics_and_stay_out_of_smoke():
    cases = select_cases(EVAL / "suites", suite="batch-import", tag="extended")
    assert [case.id for case in cases] == ["apply-all", "apply-resume"]
    assert not select_cases(EVAL / "suites", suite="batch-import", tag="smoke")
    rubrics = json.loads((SUITE / "rubrics.json").read_text(encoding="utf-8"))
    for case in cases:
        turn, = case.definition["turns"]
        criterion, = rubrics["cases"][case.id]
        assert set(turn["checks"]) <= EXPECTATIONS.keys()
        assert turn["acceptance"] == case.id
        assert criterion["turn"] == 1
        assert set(criterion["requires"]) == {"reply", "acceptance"}
        assert len(criterion["anchors"]) == 3


@pytest.mark.parametrize("fault", [None, "advance-early", "count-inserts-only"])
def test_batch_acceptance_detects_incorrect_progress(monkeypatch, fault):
    def import_batch(conn, batch, *, committed_rows, sha256, complete):
        rows = list(batch)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS import_checkpoint "
            "(id INTEGER PRIMARY KEY, data TEXT)"
        )

        def save_progress(count):
            conn.execute(
                "INSERT OR REPLACE INTO import_checkpoint VALUES (1, ?)",
                (json.dumps(dict(version=2, committed_rows=count, sha256=sha256,
                                 complete=complete)),),
            )

        if fault == "advance-early":
            with conn:
                save_progress(committed_rows + len(rows))
        with conn:
            inserted = 0
            for key, value in rows:
                if not key:
                    raise ValueError("invalid row")
                inserted += conn.execute(
                    "INSERT OR IGNORE INTO records VALUES (?, ?)", (key, value)
                ).rowcount
            count = inserted if fault == "count-inserts-only" else len(rows)
            save_progress(committed_rows + count)

    monkeypatch.setitem(sys.modules, "importer", SimpleNamespace(import_batch=import_batch))
    if fault is None:
        acceptance.batch_atomicity()
    else:
        with pytest.raises(AssertionError):
            acceptance.batch_atomicity()


def test_input_identity_acceptance_rejects_success_for_changed_input(monkeypatch):
    def ignores_fingerprint(connection, data, *options, **kwargs):
        connection.execute("INSERT INTO records VALUES ('e', 'echo')")
        return 0, "Resumed\n", ""

    monkeypatch.setattr(acceptance, "cli", ignores_fingerprint)
    with pytest.raises(AssertionError):
        acceptance.input_identity()


@pytest.mark.slow
def test_resume_seed_is_preserved_and_commit_order_is_checked(tmp_path):
    case, = select_cases(EVAL / "suites", suite="batch-import", case_id="apply-resume")
    trial = prepare_trial(REPO, case, parent=tmp_path / "resume")
    repo = trial.repo
    todo = repo / acceptance.SPEC / "todo.json"
    tasks = json.loads(todo.read_text(encoding="utf-8"))
    assert [bool(task["completed_at"]) for task in tasks] == [True, False, False, False]
    assert git(repo, "status", "--porcelain", env=trial.env) == b""
    seed = git(repo, "rev-parse", "HEAD", env=trial.env).decode().strip()
    with acceptance.snapshot(repo, seed):
        acceptance.checkpoint_compatibility()
        acceptance.legacy_cli()

    for index, task in enumerate(tasks[1:], 2):
        file = f"test_step_{index}.py"
        (repo / file).write_text("# Test change for the history checker.\n", encoding="utf-8")
        git(repo, "add", "--", file, env=trial.env)
        git(repo, "commit", "-m", f"Implement step {index}", env=trial.env)
        title = git(repo, "log", "-1", "--format=%h: %s", env=trial.env).decode().strip()
        task.update(completed_at="2000-01-03T00:00:00+00:00", commit_title=title)
    todo.write_text(json.dumps(tasks), encoding="utf-8")
    assert acceptance.ordered_steps(repo, "apply-resume")[0] == seed

    tasks[1]["commit_title"], tasks[2]["commit_title"] = (
        tasks[2]["commit_title"], tasks[1]["commit_title"],
    )
    todo.write_text(json.dumps(tasks), encoding="utf-8")
    with pytest.raises(AssertionError, match="step-2 does not identify its ordered commit"):
        acceptance.ordered_steps(repo, "apply-resume")
