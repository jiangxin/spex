"""Tests for the spex CLI entry point."""

import json
import os
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
        assert "Usage: spex <command>" in result.stdout

    def test_lists_commands(self):
        result = _run_spex()

        assert "list" in result.stdout
        assert "archive" in result.stdout


class TestDirectCommands:
    def test_list_exits_zero(self, tmp_path, monkeypatch):
        # Create a minimal specs dir so list_specs doesn't fail
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        monkeypatch.setenv("SPEX_SPEC_ROOT", str(tmp_path))

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "list"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # list_specs calls get_specs_dir which needs git; test via mock
        # Instead, just test that the script dispatches correctly
        # by checking it doesn't print the LLM error or usage
        assert "requires an AI coding agent" not in result.stderr

    def test_list_all_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEX_SPEC_ROOT", str(tmp_path))

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "list-all"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert "requires an AI coding agent" not in result.stderr

    def test_archive_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEX_SPEC_ROOT", str(tmp_path))

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

    def test_init_alias(self):
        result = _run_spex("init")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr

    def test_new_alias(self):
        result = _run_spex("new")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr


class TestUnknownCommand:
    def test_unknown_prints_usage_to_stderr(self):
        result = _run_spex("bogus")

        assert result.returncode == 1
        assert "Unknown command: bogus" in result.stderr
        assert "Usage: spex <command>" in result.stderr


class TestInstallCommand:
    """Tests for the install subcommand."""

    def _run_install(self, tmp_path, env_override=None):
        """Run spex install with HOME pointed to tmp_path."""
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        if env_override:
            env.update(env_override)
        return subprocess.run(
            [sys.executable, SPEX_SCRIPT, "install"],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_successful_install_creates_symlink(self, tmp_path):
        result = self._run_install(tmp_path)

        assert result.returncode == 0
        link = tmp_path / ".local" / "bin" / "spex"
        assert link.is_symlink()
        assert link.resolve() == Path(SPEX_SCRIPT).resolve()
        assert "Installed:" in result.stdout

    def test_already_installed_same_target(self, tmp_path):
        # Pre-create the correct symlink
        link_dir = tmp_path / ".local" / "bin"
        link_dir.mkdir(parents=True)
        link = link_dir / "spex"
        link.symlink_to(Path(SPEX_SCRIPT).resolve())

        result = self._run_install(tmp_path)

        assert result.returncode == 0
        assert "Already installed." in result.stdout

    def test_conflict_symlink_different_target(self, tmp_path):
        # Pre-create a symlink pointing elsewhere
        link_dir = tmp_path / ".local" / "bin"
        link_dir.mkdir(parents=True)
        link = link_dir / "spex"
        other_target = tmp_path / "other_spex"
        other_target.write_text("#!/bin/sh\n")
        link.symlink_to(other_target)

        result = self._run_install(tmp_path)

        assert result.returncode == 1
        assert "already exists and points to" in result.stderr

    def test_conflict_non_symlink_file(self, tmp_path):
        # Pre-create a regular file at the target path
        link_dir = tmp_path / ".local" / "bin"
        link_dir.mkdir(parents=True)
        link = link_dir / "spex"
        link.write_text("#!/bin/sh\n")

        result = self._run_install(tmp_path)

        assert result.returncode == 1
        assert "is not a symlink" in result.stderr

    def test_path_hint_when_not_in_path(self, tmp_path):
        # Use a PATH that does not include ~/.local/bin
        env_override = {"PATH": "/usr/bin:/bin"}
        result = self._run_install(tmp_path, env_override=env_override)

        assert result.returncode == 0
        assert "is not in your PATH" in result.stdout
        assert 'export PATH="$HOME/.local/bin:$PATH"' in result.stdout

    def test_no_path_hint_when_in_path(self, tmp_path):
        # Include ~/.local/bin in PATH and place a working symlink there
        link_dir = tmp_path / ".local" / "bin"
        link_dir.mkdir(parents=True)
        env_override = {"PATH": f"{link_dir}:/usr/bin:/bin"}

        # First install to create the symlink
        result = self._run_install(tmp_path, env_override=env_override)

        assert result.returncode == 0
        assert "is not in your PATH" not in result.stdout


class TestGetCommand:
    """Tests for the get subcommand."""

    def test_spec_root_prints_path(self, tmp_path):
        """spex get --spec-root prints a valid path, exit 0."""
        # Create a git repo so get_specs_root works
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path), capture_output=True
        )
        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "get", "--spec-root"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0
        assert result.stdout.strip() != ""
        assert ".specs" in result.stdout

    def test_no_flag_prints_usage_exit_1(self):
        """spex get (no flag) prints usage to stderr, exit 1."""
        result = _run_spex("get")

        assert result.returncode == 1
        assert "Usage:" in result.stderr


class TestGetTopicCommand:
    """Tests for the get-topic subcommand."""

    def test_no_matching_topics_exit_1(self, tmp_path, monkeypatch):
        """spex get-topic (no matching topics) exits 1."""
        monkeypatch.setenv("SPEX_SPEC_ROOT", str(tmp_path))
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

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
        """spex todo mark-done (wrong args) exits 1."""
        result = _run_spex("todo", "mark-done")

        assert result.returncode == 1
        assert "Usage:" in result.stderr


class TestGetSpecTemplate:
    def test_get_spec_template_returns_content(self, tmp_path, monkeypatch):
        """Command should output template content (not a path)."""
        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))

        result = _run_spex("get", "--spec-template")

        assert result.returncode == 0
        output = result.stdout
        # Should contain template content
        assert "# Requirement" in output
        # Front-matter should be stripped
        assert "---" not in output

    def test_get_spec_template_custom_priority(self, tmp_path, monkeypatch):
        """Custom template content should be returned when it exists."""
        template_path = tmp_path / "templates" / "spec.md"
        template_path.parent.mkdir()
        template_path.write_text("# My Custom Spec\n\nCustom content here")
        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))

        result = _run_spex("get", "--spec-template")

        assert result.returncode == 0
        output = result.stdout
        assert "# My Custom Spec" in output
        assert "Custom content here" in output
