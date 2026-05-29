import json

import pytest
import remove_undone_todo


@pytest.fixture()
def todo_file(tmp_path):
    path = tmp_path / "todo.json"
    return path


def _write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class TestRemoveUndone:
    def test_removes_undone_items(self, todo_file, capsys):
        data = [
            {"id": "step-1", "name": "Done",
             "completed_at": "2026-01-01", "commit_title": "abc"},
            {"id": "step-2", "name": "Undone",
             "completed_at": "", "commit_title": ""},
            {"id": "step-3", "name": "Also done",
             "completed_at": "2026-01-02", "commit_title": "def"},
        ]
        _write(todo_file, data)

        remove_undone_todo.main([str(todo_file)])

        result = json.loads(todo_file.read_text())
        assert len(result) == 2
        assert result[0]["id"] == "step-1"
        assert result[1]["id"] == "step-3"

    def test_all_completed_no_change(self, todo_file, capsys):
        data = [
            {"id": "step-1", "name": "Done", "completed_at": "2026-01-01", "commit_title": "x"},
        ]
        _write(todo_file, data)

        remove_undone_todo.main([str(todo_file)])

        result = json.loads(todo_file.read_text())
        assert len(result) == 1
        out = capsys.readouterr().out
        assert "0 undone" in out

    def test_none_completed_empty_result(self, todo_file):
        data = [
            {"id": "step-1", "name": "Undone", "completed_at": "", "commit_title": ""},
        ]
        _write(todo_file, data)

        remove_undone_todo.main([str(todo_file)])

        result = json.loads(todo_file.read_text())
        assert result == []

    def test_file_not_found_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            remove_undone_todo.main([str(tmp_path / "nope.json")])
        assert exc_info.value.code == 1

    def test_invalid_json_exits(self, todo_file):
        todo_file.write_text("{bad json", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            remove_undone_todo.main([str(todo_file)])
        assert exc_info.value.code == 1

    def test_non_list_json_exits(self, todo_file):
        todo_file.write_text('{"key": "value"}', encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            remove_undone_todo.main([str(todo_file)])
        assert exc_info.value.code == 1

    def test_no_tmp_files_after_success(self, todo_file):
        data = [{"id": "s1", "name": "X", "completed_at": "2026-01-01", "commit_title": ""}]
        _write(todo_file, data)

        remove_undone_todo.main([str(todo_file)])

        tmp_files = list(todo_file.parent.glob("*.tmp"))
        assert tmp_files == []

    def test_help_flag(self):
        with pytest.raises(SystemExit) as exc_info:
            remove_undone_todo.main(["-h"])
        assert exc_info.value.code == 0
