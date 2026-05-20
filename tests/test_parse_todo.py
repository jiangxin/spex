"""Tests for parse_todo.py (direct import)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from parse_todo import (
    MAX_OUTPUT_BYTES,
    _format_done_output,
    cmd_get_done,
    cmd_get_next_undone,
    cmd_validate,
)


def _make_task(task_id, name="Task", details="Details here", completed=True):
    """Create a single todo item dict."""
    return {
        "id": task_id,
        "name": name,
        "details": details,
        "completed_at": "2026-01-01T00:00:00Z" if completed else "",
        "commit_title": f"commit for {task_id}" if completed else "",
    }


def _write_todo(tmp_path, tasks):
    """Write tasks to a todo.json file and return the path."""
    path = tmp_path / "todo.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return str(path)


# ===================== cmd_validate =====================


class TestCmdValidate:
    def test_valid_file(self, tmp_path, capsys):
        tasks = [_make_task("1")]
        path = _write_todo(tmp_path, tasks)

        cmd_validate([path])

        output = capsys.readouterr().out
        assert "OK: 1 step(s) validated" in output

    def test_multiple_items_valid(self, tmp_path, capsys):
        tasks = [_make_task("1"), _make_task("2", completed=False)]
        path = _write_todo(tmp_path, tasks)

        cmd_validate([path])

        output = capsys.readouterr().out
        assert "OK: 2 step(s) validated" in output

    def test_not_array(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text('{"not": "array"}', encoding="utf-8")

        with pytest.raises(SystemExit):
            cmd_validate([str(path)])

    def test_empty_array(self, tmp_path):
        path = _write_todo(tmp_path, [])

        with pytest.raises(SystemExit):
            cmd_validate([path])

    def test_missing_fields(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text('[{"id": "1"}]', encoding="utf-8")

        with pytest.raises(SystemExit):
            cmd_validate([str(path)])

    def test_item_not_object(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text('["string_item"]', encoding="utf-8")

        with pytest.raises(SystemExit):
            cmd_validate([str(path)])

    def test_no_args(self):
        with pytest.raises(SystemExit):
            cmd_validate([])

    def test_file_not_found(self):
        with pytest.raises(SystemExit):
            cmd_validate(["/nonexistent/todo.json"])

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text("{invalid json", encoding="utf-8")

        with pytest.raises(SystemExit):
            cmd_validate([str(path)])


# ===================== cmd_get_next_undone =====================


class TestCmdGetNextUndone:
    def test_only_id_mode(self, tmp_path, capsys):
        tasks = [_make_task("1"), _make_task("2", completed=False)]
        path = _write_todo(tmp_path, tasks)

        cmd_get_next_undone(["--only-id", path])

        output = capsys.readouterr().out.strip()
        assert output == "2"

    def test_details_mode(self, tmp_path, capsys):
        tasks = [_make_task("1"), _make_task("2", name="Do thing", completed=False)]
        path = _write_todo(tmp_path, tasks)

        cmd_get_next_undone(["--details", path])

        output = capsys.readouterr().out
        assert "**Task**: 2 - Do thing" in output
        assert "<details>" in output

    def test_all_done_outputs_nothing(self, tmp_path, capsys):
        tasks = [_make_task("1"), _make_task("2")]
        path = _write_todo(tmp_path, tasks)

        cmd_get_next_undone(["--only-id", path])

        output = capsys.readouterr().out
        assert output == ""

    def test_first_undone_returned(self, tmp_path, capsys):
        tasks = [
            _make_task("1"),
            _make_task("2", completed=False),
            _make_task("3", completed=False),
        ]
        path = _write_todo(tmp_path, tasks)

        cmd_get_next_undone(["--only-id", path])

        output = capsys.readouterr().out.strip()
        assert output == "2"

    def test_no_args(self):
        with pytest.raises(SystemExit):
            cmd_get_next_undone([])

    def test_wrong_flag(self, tmp_path):
        tasks = [_make_task("1", completed=False)]
        path = _write_todo(tmp_path, tasks)

        with pytest.raises(SystemExit):
            cmd_get_next_undone(["--bad-flag", path])

    def test_not_array(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text('{}', encoding="utf-8")

        with pytest.raises(SystemExit):
            cmd_get_next_undone(["--only-id", str(path)])


# ===================== cmd_get_done =====================


class TestGetDoneSmallOutput:
    """Test that small output (< 10KB) shows all completed tasks."""

    def test_all_tasks_shown(self, tmp_path, capsys):
        tasks = [_make_task(str(i), name=f"Task {i}") for i in range(1, 4)]
        path = _write_todo(tmp_path, tasks)

        cmd_get_done([path])

        output = capsys.readouterr().out
        for i in range(1, 4):
            assert f"{i}: Task {i}" in output

    def test_no_truncation_notice(self, tmp_path, capsys):
        tasks = [_make_task(str(i), name=f"Task {i}") for i in range(1, 4)]
        path = _write_todo(tmp_path, tasks)

        cmd_get_done([path])

        output = capsys.readouterr().out
        assert "showing last" not in output

    def test_no_done_outputs_nothing(self, tmp_path, capsys):
        tasks = [_make_task("1", completed=False)]
        path = _write_todo(tmp_path, tasks)

        cmd_get_done([path])

        output = capsys.readouterr().out
        assert output == ""

    def test_no_args(self):
        with pytest.raises(SystemExit):
            cmd_get_done([])


class TestGetDoneLargeOutputTruncated:
    """Test truncation when output exceeds 10KB without --details."""

    def _make_large_tasks(self, count=20):
        padding = "x" * 550
        return [
            _make_task(str(i), name=f"Task {i} {padding}")
            for i in range(1, count + 1)
        ]

    def test_only_last_10_shown(self, tmp_path, capsys):
        tasks = self._make_large_tasks()
        path = _write_todo(tmp_path, tasks)

        full = _format_done_output(tasks, details_mode=False)
        assert len(full.encode("utf-8")) > MAX_OUTPUT_BYTES

        cmd_get_done([path])

        output = capsys.readouterr().out
        for i in range(11, 21):
            assert f"{i}: Task {i}" in output
        for i in range(1, 11):
            assert f"\n{i}: Task {i}" not in output

    def test_truncation_notice_present(self, tmp_path, capsys):
        tasks = self._make_large_tasks()
        path = _write_todo(tmp_path, tasks)

        cmd_get_done([path])

        output = capsys.readouterr().out
        assert "20 completed, showing last 10" in output


class TestGetDoneLargeOutputDetailsLastOnly:
    """Test --details mode: only the last record shows details."""

    def _make_large_tasks(self, count=20):
        padding = "x" * 550
        return [
            _make_task(str(i), name=f"Task {i} {padding}", details=f"Detail for {i}")
            for i in range(1, count + 1)
        ]

    def test_last_item_has_details(self, tmp_path, capsys):
        tasks = self._make_large_tasks()
        path = _write_todo(tmp_path, tasks)

        full = _format_done_output(tasks, details_mode=True)
        assert len(full.encode("utf-8")) > MAX_OUTPUT_BYTES

        cmd_get_done(["--details", path])

        output = capsys.readouterr().out
        assert "Detail for 20" in output
        assert "<details>" in output

    def test_non_last_items_summary_only(self, tmp_path, capsys):
        tasks = self._make_large_tasks()
        path = _write_todo(tmp_path, tasks)

        cmd_get_done(["--details", path])

        output = capsys.readouterr().out
        for i in range(11, 20):
            assert f"Detail for {i}" not in output


class TestGetDoneBoundary:
    """Test that output at or just below 10KB is not truncated."""

    def test_no_truncation_at_boundary(self, tmp_path, capsys):
        tasks = []
        task_id = 0
        while True:
            task_id += 1
            tasks.append(_make_task(str(task_id), name=f"Task {task_id}"))
            full = _format_done_output(tasks, details_mode=False)
            if len(full.encode("utf-8")) > MAX_OUTPUT_BYTES:
                tasks.pop()
                break

        assert len(tasks) > 10
        path = _write_todo(tmp_path, tasks)

        cmd_get_done([path])

        output = capsys.readouterr().out
        assert "showing last" not in output
        for i in range(1, len(tasks) + 1):
            assert f"{i}: Task {i}" in output


class TestGetDoneFewerThan10Completed:
    """Test that fewer than 10 completed tasks are all shown even if > 10KB."""

    def test_all_5_shown_when_exceeding_limit(self, tmp_path, capsys):
        big_detail = "y" * 3000
        tasks = [
            _make_task(str(i), name=f"Task {i}", details=big_detail)
            for i in range(1, 6)
        ]
        path = _write_todo(tmp_path, tasks)

        full = _format_done_output(tasks, details_mode=True)
        assert len(full.encode("utf-8")) > MAX_OUTPUT_BYTES

        cmd_get_done(["--details", path])

        output = capsys.readouterr().out
        for i in range(1, 6):
            assert f"Task {i}" in output
