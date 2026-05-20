import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from parse_todo import (
    MAX_OUTPUT_BYTES,
    _format_done_output,
    cmd_get_done,
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


class TestGetDoneLargeOutputTruncated:
    """Test truncation when output exceeds 10KB without --details."""

    def _make_large_tasks(self, count=20):
        """Create tasks with long names to exceed 10KB total."""
        # Each task summary: "{id}: {name}\n" ~ 600 bytes with padding
        padding = "x" * 550
        return [
            _make_task(str(i), name=f"Task {i} {padding}")
            for i in range(1, count + 1)
        ]

    def test_only_last_10_shown(self, tmp_path, capsys):
        tasks = self._make_large_tasks()
        path = _write_todo(tmp_path, tasks)

        # Verify precondition: full output exceeds limit
        full = _format_done_output(tasks, details_mode=False)
        assert len(full.encode("utf-8")) > MAX_OUTPUT_BYTES

        cmd_get_done([path])

        output = capsys.readouterr().out
        # Last 10 tasks (ids 11-20) should appear
        for i in range(11, 21):
            assert f"{i}: Task {i}" in output
        # Earlier tasks should not appear as standalone entries
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

        # Verify precondition
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
        # Earlier items in the last-10 should NOT have their details expanded
        for i in range(11, 20):
            assert f"Detail for {i}" not in output


class TestGetDoneBoundary:
    """Test that output at or just below 10KB is not truncated."""

    def test_no_truncation_at_boundary(self, tmp_path, capsys):
        # Build tasks incrementally until just under the limit
        tasks = []
        task_id = 0
        while True:
            task_id += 1
            tasks.append(_make_task(str(task_id), name=f"Task {task_id}"))
            full = _format_done_output(tasks, details_mode=False)
            if len(full.encode("utf-8")) > MAX_OUTPUT_BYTES:
                # Remove last task to stay at or below limit
                tasks.pop()
                break

        assert len(tasks) > 10, "Need more than 10 tasks for meaningful test"
        path = _write_todo(tmp_path, tasks)

        cmd_get_done([path])

        output = capsys.readouterr().out
        assert "showing last" not in output
        # All tasks should be present
        for i in range(1, len(tasks) + 1):
            assert f"{i}: Task {i}" in output


class TestGetDoneFewerThan10Completed:
    """Test that fewer than 10 completed tasks are all shown even if > 10KB."""

    def test_all_5_shown_when_exceeding_limit(self, tmp_path, capsys):
        # 5 tasks with very large details to exceed 10KB
        big_detail = "y" * 3000
        tasks = [
            _make_task(str(i), name=f"Task {i}", details=big_detail)
            for i in range(1, 6)
        ]
        path = _write_todo(tmp_path, tasks)

        # Verify precondition: full output with details exceeds limit
        full = _format_done_output(tasks, details_mode=True)
        assert len(full.encode("utf-8")) > MAX_OUTPUT_BYTES

        cmd_get_done(["--details", path])

        output = capsys.readouterr().out
        # All 5 tasks should appear since 5 < 10
        for i in range(1, 6):
            assert f"Task {i}" in output
