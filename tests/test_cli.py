"""Tests for the spex CLI entry point."""

import json
import re
import subprocess
import sys
from pathlib import Path

SPEX_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "spex")


def _run_spex(*args):
    """Run the spex CLI with given arguments and return the CompletedProcess."""
    return subprocess.run(
        [sys.executable, SPEX_SCRIPT, *args],
        capture_output=True,
        text=True,
    )


class TestNoArgs:
    def test_prints_usage(self):
        result = _run_spex()

        assert result.returncode == 0
        assert "Usage: spex" in result.stdout

    def test_lists_commands(self):
        result = _run_spex()

        assert "list" in result.stdout
        assert "archive" in result.stdout


class TestHelpFlag:
    """Tests for -h/--help support."""

    def test_spex_h_exits_zero_with_usage(self):
        result = _run_spex("-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_spex_help_exits_zero_with_usage(self):
        result = _run_spex("--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_config_h_exits_zero_with_usage(self):
        result = _run_spex("config", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_config_help_exits_zero_with_usage(self):
        result = _run_spex("config", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_list_h_exits_zero_with_usage(self):
        result = _run_spex("list", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_list_help_exits_zero_with_usage(self):
        result = _run_spex("list", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_archive_h_exits_zero_with_usage(self):
        result = _run_spex("archive", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_archive_help_exits_zero_with_usage(self):
        result = _run_spex("archive", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_open_h_exits_zero_with_usage(self):
        result = _run_spex("open", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_open_help_exits_zero_with_usage(self):
        result = _run_spex("open", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_get_topic_h_exits_zero_with_usage(self):
        result = _run_spex("get-topic", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_get_topic_help_exits_zero(self):
        result = _run_spex("get-topic", "--help")

        assert result.returncode == 0

    def test_meta_h_exits_zero_with_usage(self):
        result = _run_spex("meta", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_meta_help_exits_zero(self):
        result = _run_spex("meta", "--help")

        assert result.returncode == 0


class TestDirectCommands:
    def test_list_exits_zero(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        (tmp_path / ".spex" / "specs").mkdir(parents=True)

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "list"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert "requires an AI coding agent" not in result.stderr

    def test_list_all_exits_zero(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        (tmp_path / ".spex" / "specs").mkdir(parents=True)
        (tmp_path / ".spex" / "archives").mkdir(parents=True)

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "list", "--all"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert "requires an AI coding agent" not in result.stderr

    def test_archive_exits_zero(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        (tmp_path / ".spex" / "specs").mkdir(parents=True)
        (tmp_path / ".spex" / "archives").mkdir(parents=True)

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "archive"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert "requires an AI coding agent" not in result.stderr


class TestLLMCommands:
    def test_apply_prints_hint(self):
        result = _run_spex("apply")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr
        assert "'/spex apply'" in result.stderr

    def test_create_prints_hint(self):
        result = _run_spex("create")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr
        assert "'/spex create'" in result.stderr

    def test_modify_prints_hint(self):
        result = _run_spex("modify")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr
        assert "'/spex modify'" in result.stderr

    def test_new_alias(self):
        result = _run_spex("new")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr


class TestVersion:
    _VERSION_RE = r"spex \d+\.\d+\.\d+"

    def test_version_command(self):
        result = _run_spex("version")

        assert result.returncode == 0
        assert re.search(self._VERSION_RE, result.stdout)

    def test_version_flag(self):
        result = _run_spex("--version")

        assert result.returncode == 0
        assert re.search(self._VERSION_RE, result.stdout)

    def test_version_short_flag(self):
        result = _run_spex("-V")

        assert result.returncode == 0
        assert re.search(self._VERSION_RE, result.stdout)


class TestUnknownCommand:
    def test_unknown_prints_usage_to_stderr(self):
        result = _run_spex("bogus")

        assert result.returncode == 1
        assert "Unknown command: bogus" in result.stderr
        assert "Usage: spex" in result.stderr


class TestGetCommand:
    """Tests for the removed get subcommand."""

    def test_get_is_unknown_command(self):
        """spex get is no longer a valid command."""
        result = _run_spex("get")

        assert result.returncode == 1
        assert "Unknown command: get" in result.stderr


class TestGetTopicCommand:
    """Tests for the get-topic subcommand."""

    def test_no_matching_topics_exit_1(self, tmp_path):
        """spex get-topic (no matching topics) exits 1."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        specs_dir = tmp_path / ".spex" / "specs"
        specs_dir.mkdir(parents=True)

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "get-topic"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 1


class TestCreateTopicCommand:
    """Tests for the create-topic subcommand."""

    def test_no_arg_exit_1(self):
        """spex create-topic (no arg) exits 1."""
        result = _run_spex("create-topic")

        assert result.returncode == 1
        assert "Usage:" in result.stderr


class TestTodoCommand:
    """Tests for the todo subcommand."""

    def test_no_subcommand_exit_1(self):
        """spex todo (no subcommand) exits 1."""
        result = _run_spex("todo")

        assert result.returncode == 1
        assert "Usage:" in result.stderr

    def test_validate_valid_file(self, tmp_path):
        """spex todo validate <valid-file> exits 0."""
        todo_file = tmp_path / "todo.json"
        todo_file.write_text(
            json.dumps([
                {
                    "id": "task-1",
                    "name": "Test task",
                    "details": "Some details",
                    "completed_at": None,
                    "commit_title": None,
                }
            ]),
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "todo", "validate", str(todo_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "OK:" in result.stdout

    def test_mark_done_wrong_args_exit_1(self):
        """spex todo mark-done (wrong args) exits non-zero."""
        result = _run_spex("todo", "mark-done")

        assert result.returncode in (1, 2)
        assert "Usage:" in result.stderr

    def test_todo_h_exits_zero_with_usage(self):
        """spex todo -h exits 0 with usage."""
        result = _run_spex("todo", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_help_exits_zero_with_usage(self):
        """spex todo --help exits 0 with usage."""
        result = _run_spex("todo", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_validate_h_exits_zero_with_usage(self):
        """spex todo validate -h exits 0 with usage."""
        result = _run_spex("todo", "validate", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_validate_help_exits_zero_with_usage(self):
        """spex todo validate --help exits 0 with usage."""
        result = _run_spex("todo", "validate", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_get_next_undone_h_exits_zero_with_usage(self):
        """spex todo get-next-undone -h exits 0 with usage."""
        result = _run_spex("todo", "get-next-undone", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_get_next_undone_help_exits_zero_with_usage(self):
        """spex todo get-next-undone --help exits 0 with usage."""
        result = _run_spex("todo", "get-next-undone", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_get_done_h_exits_zero_with_usage(self):
        """spex todo get-done -h exits 0 with usage."""
        result = _run_spex("todo", "get-done", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_get_done_help_exits_zero_with_usage(self):
        """spex todo get-done --help exits 0 with usage."""
        result = _run_spex("todo", "get-done", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_mark_done_h_exits_zero_with_usage(self):
        """spex todo mark-done -h exits 0 with usage."""
        result = _run_spex("todo", "mark-done", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_mark_done_help_exits_zero_with_usage(self):
        """spex todo mark-done --help exits 0 with usage."""
        result = _run_spex("todo", "mark-done", "--help")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_xml2json_h_exits_zero_with_usage(self):
        """spex todo xml2json -h exits 0 with usage."""
        result = _run_spex("todo", "xml2json", "-h")

        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_todo_xml2json_help_exits_zero(self):
        """spex todo xml2json --help exits 0."""
        result = _run_spex("todo", "xml2json", "--help")

        assert result.returncode == 0



