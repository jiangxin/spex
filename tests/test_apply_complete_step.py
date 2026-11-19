"""Coverage for transactional apply completion."""

import io
import json

import apply_helper
import pytest
import todo_helper


@pytest.fixture
def complete(tmp_path, monkeypatch):
    spec = tmp_path / "example"
    spec.mkdir()
    todo = spec / "todo.json"
    data = [
        {"id": step, "name": f"Step {step}", "details": "Work", "completed_at": "",
         "commit_title": ""}
        for step in (1, 2)
    ]
    todo.write_text(json.dumps(data))
    monkeypatch.setattr("common.resolve_spec_dir", lambda _name: spec)

    def run(step, *args):
        apply_helper.main(["complete-step", "--name", spec.name, "--id", str(step), *args])

    return todo, run


def test_complete_reports_own_snapshot_after_next_commit(complete, monkeypatch, capsys):
    todo, run = complete
    transaction = todo_helper.cmd_transaction

    def interleave(path, action):
        transaction(path, action)
        if action == "commit":
            monkeypatch.setattr(todo_helper, "cmd_transaction", transaction)
            run(2)

    monkeypatch.setattr(todo_helper, "cmd_transaction", interleave)
    run(1, "--commit-title", "0123456: Recorded")
    final, first = map(json.loads, capsys.readouterr().out.splitlines())
    assert final == {"completion": "completed", "remaining": 0, "finalization": "pending"}
    assert first == {"completion": "completed", "remaining": 1, "finalization": "not_needed"}
    assert json.loads(todo.read_text())[0]["commit_title"] == "0123456: Recorded"
    before = todo.read_bytes()
    run(2, "--commit-title", "0000000: Replacement")
    assert json.loads(capsys.readouterr().out) == {
        "completion": "already_completed", "remaining": 0, "finalization": "unknown",
    }
    assert todo.read_bytes() == before


def test_complete_persists_general_evidence(complete, monkeypatch):
    todo, run = complete
    (todo.parent / "meta.json").write_text('{"task_mode": "general"}')
    evidence = [{"kind": "command", "criterion": "Check", "command": "true", "exit_code": 0}]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(evidence)))
    run(1, "--acceptance-evidence-stdin")
    before = todo.read_bytes()
    assert json.loads(before)[0]["acceptance_evidence"] == evidence
    run(1)
    assert todo.read_bytes() == before


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_complete_rejects_snapshot_made_before_concurrent_commit(
    complete, monkeypatch, caplog, cleanup_fails,
):
    todo, run = complete
    backup = todo.with_suffix(".json.lock")
    original_unlink = type(backup).unlink
    original_link = todo_helper.os.link
    updated = json.loads(todo.read_text())
    updated[0]["completed_at"] = "2026-11-19T14:00:00+08:00"

    def interleave(source, destination):
        todo.write_text(json.dumps(updated))
        original_link(source, destination)

    def unlink(path, *args, **kwargs):
        if path == backup:
            raise PermissionError("cannot remove stale backup")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(todo_helper.os, "link", interleave)
    if cleanup_fails:
        monkeypatch.setattr(type(backup), "unlink", unlink)
    with pytest.raises(SystemExit) as failure:
        run(2)
    assert failure.value.code == 1
    assert json.loads(todo.read_text()) == updated
    assert backup.exists() == cleanup_fails
    if cleanup_fails:
        assert json.loads(backup.read_text())[0]["completed_at"] == ""
        assert "potentially stale todo backup" in caplog.text
        assert "transaction commit example" in caplog.text
        assert "transaction rollback example" not in caplog.text


@pytest.mark.parametrize(("stage", "code"), [("start", 1), ("update", 1), ("commit", 3),
                                             ("rollback", 4)])
def test_complete_preserves_recovery_on_failure(complete, monkeypatch, caplog, stage, code):
    todo, run = complete
    backup = todo.with_suffix(".json.lock")
    before = todo.read_bytes()
    transaction = todo_helper.cmd_transaction

    def fail_transaction(path, action):
        if action == stage:
            if action == "start":
                backup.write_bytes(before)
            raise SystemExit(1)
        transaction(path, action)

    monkeypatch.setattr(todo_helper, "cmd_transaction", fail_transaction)
    if stage in {"update", "rollback"}:
        def fail_update(*_args):
            raise OSError("Cannot update todo")

        monkeypatch.setattr(todo_helper, "atomic_write_json", fail_update)

    with pytest.raises(SystemExit) as failure:
        run(1)
    assert failure.value.code == code
    assert backup.exists() == (stage != "update")
    if backup.exists():
        assert backup.read_bytes() == before
        assert str(backup) in caplog.text
        recovery = "rollback" if stage == "rollback" else "commit"
        assert f"transaction {recovery} example" in caplog.text
    assert bool(json.loads(todo.read_text())[0]["completed_at"]) == (stage == "commit")
