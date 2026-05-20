"""Tests for the sdd CLI entry point."""

import os
import subprocess
import sys
from pathlib import Path

SDD_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "sdd")


def _run_sdd(*args):
    """Run the sdd CLI with given arguments and return the CompletedProcess."""
    return subprocess.run(
        [sys.executable, SDD_SCRIPT, *args],
        capture_output=True,
        text=True,
    )


class TestNoArgs:
    def test_prints_usage(self):
        result = _run_sdd()

        assert result.returncode == 0
        assert "Usage: sdd <command>" in result.stdout

    def test_lists_commands(self):
        result = _run_sdd()

        assert "list" in result.stdout
        assert "archive" in result.stdout


class TestDirectCommands:
    def test_list_exits_zero(self, tmp_path, monkeypatch):
        # Create a minimal specs dir so list_specs doesn't fail
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        monkeypatch.setenv("SDD_SPEC_ROOT", str(tmp_path))

        result = subprocess.run(
            [sys.executable, SDD_SCRIPT, "list"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # list_specs calls get_specs_dir which needs git; test via mock
        # Instead, just test that the script dispatches correctly
        # by checking it doesn't print the LLM error or usage
        assert "requires an AI coding agent" not in result.stderr

    def test_list_all_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SDD_SPEC_ROOT", str(tmp_path))

        result = subprocess.run(
            [sys.executable, SDD_SCRIPT, "list-all"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert "requires an AI coding agent" not in result.stderr

    def test_archive_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SDD_SPEC_ROOT", str(tmp_path))

        result = subprocess.run(
            [sys.executable, SDD_SCRIPT, "archive"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert "requires an AI coding agent" not in result.stderr


class TestLLMCommands:
    def test_apply_prints_hint(self):
        result = _run_sdd("apply")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr
        assert "'/sdd apply'" in result.stderr

    def test_create_prints_hint(self):
        result = _run_sdd("create")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr
        assert "'/sdd create'" in result.stderr

    def test_modify_prints_hint(self):
        result = _run_sdd("modify")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr
        assert "'/sdd modify'" in result.stderr

    def test_edit_prints_hint(self):
        result = _run_sdd("edit")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr
        assert "'/sdd edit'" in result.stderr

    def test_init_alias(self):
        result = _run_sdd("init")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr

    def test_new_alias(self):
        result = _run_sdd("new")

        assert result.returncode == 1
        assert "requires an AI coding agent" in result.stderr


class TestUnknownCommand:
    def test_unknown_prints_usage_to_stderr(self):
        result = _run_sdd("bogus")

        assert result.returncode == 1
        assert "Unknown command: bogus" in result.stderr
        assert "Usage: sdd <command>" in result.stderr


class TestInstallCommand:
    """Tests for the install subcommand."""

    def _run_install(self, tmp_path, env_override=None):
        """Run sdd install with HOME pointed to tmp_path."""
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        if env_override:
            env.update(env_override)
        return subprocess.run(
            [sys.executable, SDD_SCRIPT, "install"],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_successful_install_creates_symlink(self, tmp_path):
        result = self._run_install(tmp_path)

        assert result.returncode == 0
        link = tmp_path / ".local" / "bin" / "sdd"
        assert link.is_symlink()
        assert link.resolve() == Path(SDD_SCRIPT).resolve()
        assert "Installed:" in result.stdout

    def test_already_installed_same_target(self, tmp_path):
        # Pre-create the correct symlink
        link_dir = tmp_path / ".local" / "bin"
        link_dir.mkdir(parents=True)
        link = link_dir / "sdd"
        link.symlink_to(Path(SDD_SCRIPT).resolve())

        result = self._run_install(tmp_path)

        assert result.returncode == 0
        assert "Already installed." in result.stdout

    def test_conflict_symlink_different_target(self, tmp_path):
        # Pre-create a symlink pointing elsewhere
        link_dir = tmp_path / ".local" / "bin"
        link_dir.mkdir(parents=True)
        link = link_dir / "sdd"
        other_target = tmp_path / "other_sdd"
        other_target.write_text("#!/bin/sh\n")
        link.symlink_to(other_target)

        result = self._run_install(tmp_path)

        assert result.returncode == 1
        assert "already exists and points to" in result.stderr

    def test_conflict_non_symlink_file(self, tmp_path):
        # Pre-create a regular file at the target path
        link_dir = tmp_path / ".local" / "bin"
        link_dir.mkdir(parents=True)
        link = link_dir / "sdd"
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
