"""Coverage for transactional apply completion."""

import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

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
    finalized = []

    def interleave(path, action):
        transaction(path, action)
        if action == "commit":
            monkeypatch.setattr(todo_helper, "cmd_transaction", transaction)
            run(2)

    monkeypatch.setattr(todo_helper, "cmd_transaction", interleave)
    monkeypatch.setattr(apply_helper, "_run_post_action", finalized.append)
    run(1, "--commit-title", "0123456: Recorded")
    final, first = map(json.loads, capsys.readouterr().out.splitlines())
    assert final == {"completion": "completed", "remaining": 0, "finalization": "succeeded"}
    assert first == {"completion": "completed", "remaining": 1, "finalization": "not_needed"}
    assert json.loads(todo.read_text())[0]["commit_title"] == "0123456: Recorded"
    before = todo.read_bytes()
    run(2, "--commit-title", "0000000: Replacement")
    assert json.loads(capsys.readouterr().out) == {
        "completion": "already_completed", "remaining": 0, "finalization": "unknown",
    }
    assert todo.read_bytes() == before
    assert finalized == [todo.parent]


@pytest.mark.parametrize("error", [OSError("hook launch failed"), KeyboardInterrupt()])
def test_finalization_error_preserves_completion(complete, monkeypatch, caplog, capsys, error):
    todo, run = complete
    run(1)
    capsys.readouterr()

    def interrupt(spec_dir):
        assert spec_dir == todo.parent
        assert not todo.with_suffix(".json.lock").exists()
        assert all(task["completed_at"] for task in json.loads(todo.read_text()))
        raise error

    monkeypatch.setattr(apply_helper, "_run_post_action", interrupt)
    with pytest.raises(SystemExit) as failure:
        run(2)
    assert failure.value.code == 5
    assert capsys.readouterr().out == ""
    assert "Todo completion for example is saved" in caplog.text
    assert "spex apply-helper post-action --name example" in caplog.text
    before = todo.read_bytes()
    run(2)
    assert json.loads(capsys.readouterr().out)["finalization"] == "unknown"
    assert todo.read_bytes() == before


def test_final_done_anchor_interrupt_reports_recovery(complete, monkeypatch, caplog, capsys):
    todo, run = complete
    run(1)
    capsys.readouterr()

    def interrupt(spec_dir, event, *, id):
        assert (spec_dir, event, id) == (todo.parent, "done", 2)
        assert not todo.with_suffix(".json.lock").exists()
        assert all(task["completed_at"] for task in json.loads(todo.read_text()))
        raise KeyboardInterrupt

    post_action = Mock()
    monkeypatch.setattr("debug_log.emit_apply_task", interrupt)
    monkeypatch.setattr(apply_helper, "_run_post_action", post_action)
    with pytest.raises(SystemExit) as failure:
        run(2)

    assert failure.value.code == 5
    assert not capsys.readouterr().out
    assert "Todo completion for example is saved" in caplog.text
    assert "spex apply-helper post-action --name example" in caplog.text
    post_action.assert_not_called()


@pytest.mark.parametrize("hook_mode", [None, 0o777, 0o755])
def test_finalization_preserves_hook_and_hint_behavior(
    complete, tmp_path, monkeypatch, caplog, capsys, hook_mode,
):
    import hooks

    todo, run = complete
    cwd = str(tmp_path / "coding")
    (todo.parent / "meta.json").write_text(json.dumps({
        "spex_branch": "spex/example", "branch": "main", "spex_worktree": cwd,
    }))
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    hook_path = hook_dir / "post-action"
    if hook_mode is not None:
        hook_path.touch()
        hook_path.chmod(hook_mode)
    context = SimpleNamespace(
        top_workdir=tmp_path, user_name="Tester", user_email="test@example.com",
    )
    monkeypatch.setattr("config.get_project_context", lambda: context)
    monkeypatch.setattr(hooks, "get_project_context", lambda _cwd: context)
    monkeypatch.setattr(hooks, "_resolve_hook_roots", lambda _cwd: [hook_dir])
    original_find = hooks.find_hook
    lookups = []
    invocations = []
    anchors = []

    def find(name, workdir):
        lookups.append((name, workdir))
        return original_find(name, workdir)

    def execute(argv, *, input, cwd, **_kwargs):
        event = json.loads(input)
        assert event["event_type"] == "apply"
        assert event["workdir"] == cwd
        assert event["payload"] == {
            "source_branch": "spex/example", "target_branch": "main", "spec_name": "example",
        }
        invocations.append((argv, cwd))
        return hooks.subprocess.CompletedProcess(argv, 7, stderr="hook rejected")

    monkeypatch.setattr(hooks, "find_hook", find)
    monkeypatch.setattr(hooks.subprocess, "run", execute)
    monkeypatch.setattr("debug_log.emit_apply_anchor", lambda _path, line: anchors.append(line))
    run(1)
    assert not lookups
    run(2)
    assert lookups == [("post-action", cwd)]
    assert invocations == ([([str(hook_path)], cwd)] if hook_mode == 0o755 else [])
    assert ("Development completed on spec branch" in caplog.text) == (hook_mode is None)
    assert ("hook rejected" in caplog.text) == (hook_mode == 0o755)
    assert anchors[-1] == "===== APPLY post-action ok ====="
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["finalization"] == "succeeded"


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
