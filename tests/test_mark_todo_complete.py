import json
import os
import subprocess
import sys
from pathlib import Path

import mark_todo_complete
import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "mark_todo_complete.py")


def _make_todo(tmp_path, tasks):
    """Write tasks list to todo.json and return the path."""
    path = tmp_path / "todo.json"
    path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    return path


def _run_script(task_id, commit_title, todo_path):
    """Run mark_todo_complete.py as a subprocess."""
    return subprocess.run(
        [sys.executable, SCRIPT, task_id, commit_title, str(todo_path)],
        capture_output=True,
        text=True,
    )


class TestNormalCompletion:
    """Verify a task is correctly marked as complete."""

    def test_task_marked_complete(self, tmp_path):
        tasks = [{"id": "1", "name": "Implement feature"}]
        todo_path = _make_todo(tmp_path, tasks)

        result = _run_script("1", "feat: add feature", todo_path)

        assert result.returncode == 0
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert data[0]["completed_at"] != ""
        assert data[0]["commit_title"] == "feat: add feature"

    def test_output_is_valid_json(self, tmp_path):
        tasks = [{"id": "2", "name": "Fix bug"}]
        todo_path = _make_todo(tmp_path, tasks)

        _run_script("2", "fix: resolve bug", todo_path)

        # Must not raise
        json.loads(todo_path.read_text(encoding="utf-8"))


class TestNoLeftoverTempFiles:
    """After successful write, no .tmp files should remain."""

    def test_no_tmp_files_after_success(self, tmp_path):
        tasks = [{"id": "1", "name": "Task A"}]
        todo_path = _make_todo(tmp_path, tasks)

        result = _run_script("1", "chore: done", todo_path)

        assert result.returncode == 0
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


class TestOriginalFileIntactOnError:
    """When os.replace fails, original file must be unchanged and temp cleaned."""

    def test_original_unchanged_on_replace_failure(self, tmp_path, monkeypatch):
        tasks = [{"id": "1", "name": "Task A"}]
        todo_path = _make_todo(tmp_path, tasks)
        original_content = todo_path.read_text(encoding="utf-8")

        monkeypatch.setattr(os, "replace", _raise_os_error)

        with pytest.raises(OSError, match="simulated"):
            mark_todo_complete.main(["1", "msg", str(todo_path)])

        assert todo_path.read_text(encoding="utf-8") == original_content

    def test_temp_file_cleaned_on_replace_failure(self, tmp_path, monkeypatch):
        tasks = [{"id": "1", "name": "Task A"}]
        todo_path = _make_todo(tmp_path, tasks)

        monkeypatch.setattr(os, "replace", _raise_os_error)

        with pytest.raises(OSError, match="simulated"):
            mark_todo_complete.main(["1", "msg", str(todo_path)])

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


def _raise_os_error(*_args, **_kwargs):
    raise OSError("simulated replace failure")


class TestMainErrors:
    """Tests for main() error handling paths."""

    def test_wrong_arg_count_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            mark_todo_complete.main(["only-one"])
        assert exc_info.value.code in (1, 2)

    def test_file_not_found_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            mark_todo_complete.main(["1", "msg", str(tmp_path / "missing.json")])
        assert exc_info.value.code == 1

    def test_invalid_json_exits(self, tmp_path):
        bad_file = tmp_path / "todo.json"
        bad_file.write_text("not valid json", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            mark_todo_complete.main(["1", "msg", str(bad_file)])
        assert exc_info.value.code == 1

    def test_non_list_json_exits(self, tmp_path):
        bad_file = tmp_path / "todo.json"
        bad_file.write_text('{"not": "a list"}', encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            mark_todo_complete.main(["1", "msg", str(bad_file)])
        assert exc_info.value.code == 1

    def test_task_not_found_exits(self, tmp_path):
        todo_file = tmp_path / "todo.json"
        todo_file.write_text(
            json.dumps([{"id": "other", "name": "Other task"}]),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc_info:
            mark_todo_complete.main(["missing-id", "msg", str(todo_file)])
        assert exc_info.value.code == 1

    def test_success_prints_message(self, tmp_path, capsys):
        todo_file = tmp_path / "todo.json"
        todo_file.write_text(
            json.dumps([{"id": "1", "name": "Task"}]),
            encoding="utf-8",
        )
        mark_todo_complete.main(["1", "feat: done", str(todo_file)])
        output = capsys.readouterr().out
        assert "Marked '1' as completed" in output
        data = json.loads(todo_file.read_text(encoding="utf-8"))
        assert data[0]["completed_at"] != ""
        assert data[0]["commit_title"] == "feat: done"
