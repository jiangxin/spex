"""Output destination regressions without Git or template side effects."""

import io
import json
from types import SimpleNamespace

import prompt
import pytest


@pytest.mark.parametrize("command", [
    "apply-one-task", "apply-commit", "apply-review", "apply-fix", "modify-spec", "modify-todo",
])
@pytest.mark.parametrize("to_file", [False, True])
def test_json_destination(command, to_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    (tmp_path / "todo.json").write_text(json.dumps([{
        "id": "step-1", "name": "Task", "details": "Details",
        "completed_at": "", "commit_title": "",
    }]))
    metadata = {
        "current_task_id": "step-1", "current_task_description": "Task",
        "step_id": "step-1", "commit_sha": "abcdef", "finding_id_list": ["f1"],
    }
    monkeypatch.setattr(prompt, "_build_metadata", lambda *a: dict(metadata))
    monkeypatch.setattr(prompt, "render_prompt", lambda *a, **kw: "Rendered")
    monkeypatch.setattr(prompt, "_enrich_review_metadata", lambda *a, **kw: None)
    monkeypatch.setattr(prompt, "resolve_spec_dir", lambda *a: tmp_path)
    monkeypatch.setattr(prompt, "get_project_context", lambda: SimpleNamespace(config={}))
    import debug_log
    monkeypatch.setattr(debug_log, "emit_apply_anchor", lambda *a, **kw: None)
    output = tmp_path / "nested" / "result.json"
    argv = [command, "--name", "example", "--json"]
    if to_file:
        argv += ["--output", str(output)]
    prompt.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(output.read_text() if to_file else captured.out)
    assert payload["prompt"] == "Rendered"
    if to_file:
        assert captured.out == ""


@pytest.mark.parametrize("command", ["apply-one-task", "apply-review", "apply-fix"])
def test_all_done_output(command, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(prompt, "_build_metadata", lambda *a: {})
    monkeypatch.setattr(prompt, "get_project_context", lambda: SimpleNamespace(config={}))
    output = tmp_path / "result.json"
    with pytest.raises(SystemExit) as exc:
        prompt.main([command, "--name", "example", "--json", "-o", str(output)])
    assert exc.value.code == 0
    assert json.loads(output.read_text())["all_done"] is True
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("disabled", [False, True])
def test_skipped_review_output(disabled, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(prompt, "get_project_context", lambda: SimpleNamespace(
        config={"step_review": not disabled},
    ))
    monkeypatch.setattr(prompt, "_build_metadata", lambda *a: {"current_task_id": "s1"})
    monkeypatch.setattr(prompt, "_enrich_review_metadata", lambda data, *a, **kw:
                        data.update(skip_delta=True))
    output = tmp_path / "result.json"
    with pytest.raises(SystemExit) as exc:
        prompt.main(["apply-review", "--name", "example", "--json", "-o", str(output)])
    assert exc.value.code == 0
    assert json.loads(output.read_text())["skipped"] is True
    assert capsys.readouterr().out == ""


def test_output_error(tmp_path, capsys, caplog):
    with pytest.raises(SystemExit) as exc:
        prompt._output_rendered('{"prompt": "test"}', tmp_path)
    assert exc.value.code == 1
    assert "Error writing output" in caplog.text
    assert capsys.readouterr().out == ""


def test_text_output(tmp_path, capsys):
    output = tmp_path / "prompt.md"
    prompt._output_rendered("Rendered", output)
    assert output.read_text() == "Rendered"
    assert capsys.readouterr().out == ""
    prompt._output_rendered("Rendered", None)
    assert capsys.readouterr().out == "Rendered\n"
