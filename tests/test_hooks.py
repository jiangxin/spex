"""Tests for hooks.py: hook resolution, execution, and event data."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hooks
from common import clear_spex_root_cache


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    clear_spex_root_cache()
    yield
    clear_spex_root_cache()


# ===================== _resolve_hook_roots =====================


class TestResolveHookRoots:
    def test_returns_paths_from_spex_roots(self, monkeypatch, tmp_path):
        """_resolve_hook_roots returns <spex_root>/hooks for each spex_root."""
        from unittest.mock import patch

        from config import SpexContext

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            roots = hooks._resolve_hook_roots()

        assert len(roots) >= 1
        assert roots[0] == Path(str(tmp_path)) / "hooks"


# ===================== find_hook =====================


class TestFindHook:
    def test_finds_in_spex_root(self, monkeypatch, tmp_path):
        """Hook found in spex_root/hooks/ takes priority."""
        from unittest.mock import patch

        from config import SpexContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text("#!/bin/bash\necho ok")
        os.chmod(hook_file, 0o755)

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            result = hooks.find_hook("post-action")
        assert result == hook_file

    def test_finds_in_secondary_spex_root(self, monkeypatch, tmp_path):
        """Hook found in secondary spex_root/hooks/ when primary has none."""
        from unittest.mock import patch

        from config import SpexContext

        # Primary spex_root has no hooks, secondary does
        primary = tmp_path / "primary"
        secondary = tmp_path / "secondary"
        primary.mkdir()
        secondary.mkdir()

        sec_hooks = secondary / "hooks"
        sec_hooks.mkdir()
        hook_file = sec_hooks / "post-action"
        hook_file.write_text("#!/bin/bash\necho ok")
        os.chmod(hook_file, 0o755)

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(primary),
            spex_roots=[str(primary), str(secondary)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            clear_spex_root_cache()
            result = hooks.find_hook("post-action")
            assert result == hook_file

    def test_primary_spex_root_overrides_secondary(self, monkeypatch, tmp_path):
        """Primary spex_root hook wins over secondary spex_root hook."""
        from unittest.mock import patch

        from config import SpexContext

        primary = tmp_path / "primary"
        secondary = tmp_path / "secondary"
        primary.mkdir()
        secondary.mkdir()

        # Both have hooks
        primary_hooks = primary / "hooks"
        primary_hooks.mkdir()
        primary_hook = primary_hooks / "post-action"
        primary_hook.write_text("#!/bin/bash\necho primary")
        os.chmod(primary_hook, 0o755)

        secondary_hooks = secondary / "hooks"
        secondary_hooks.mkdir()
        secondary_hook = secondary_hooks / "post-action"
        secondary_hook.write_text("#!/bin/bash\necho secondary")
        os.chmod(secondary_hook, 0o755)

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(primary),
            spex_roots=[str(primary), str(secondary)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            clear_spex_root_cache()
            result = hooks.find_hook("post-action")
            assert result == primary_hook

    def test_skips_non_executable(self, monkeypatch, tmp_path):
        """Non-executable file is skipped."""
        from unittest.mock import patch

        from config import SpexContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text("#!/bin/bash")
        # Do NOT chmod +x

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            result = hooks.find_hook("post-action")
        assert result is None

    def test_returns_none_when_missing(self, monkeypatch, tmp_path):
        """No hook found anywhere returns None."""
        from unittest.mock import patch

        from config import SpexContext

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            result = hooks.find_hook("post-action")
        assert result is None


# ===================== _build_event_data =====================


class TestBuildEventData:
    def test_builds_envelope(self, monkeypatch, tmp_path):
        """_build_event_data builds correct structure."""
        monkeypatch.chdir(tmp_path)

        # Create a minimal git repo for git config to work
        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=tmp_path, capture_output=True,
        )

        data = hooks._build_event_data("create", {"topic": "foo"}, str(tmp_path))

        assert data["user"] == "Test User"
        assert data["email"] == "test@example.com"
        assert data["workdir"] == str(tmp_path)
        assert data["event_type"] == "create"
        assert data["time"] != ""
        assert data["payload"] == {"topic": "foo"}


# ===================== run_hook =====================


class TestRunHook:
    def test_executes_and_passes_json(self, monkeypatch, tmp_path):
        """run_hook executes hook and passes JSON to stdin."""
        from unittest.mock import patch

        from config import SpexContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        output_file = tmp_path / "hook_output.txt"
        hook_file = hooks_dir / "post-action"
        hook_file.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            "data = json.loads(sys.stdin.read())\n"
            f"open('{output_file}', 'w').write(f'event={{data[\"event_type\"]}}')\n"
        )
        os.chmod(hook_file, 0o755)

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            hooks.run_hook(
                "post-action",
                {"event_type": "apply", "payload": {}},
                str(tmp_path),
            )

        assert output_file.read_text() == "event=apply"

    def test_logs_error_on_failure(self, monkeypatch, tmp_path, capfd):
        """run_hook logs stderr when hook exits non-zero."""
        from unittest.mock import patch

        from config import SpexContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text(
            "#!/bin/bash\necho 'intentional error' >&2; exit 1\n"
        )
        os.chmod(hook_file, 0o755)

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            hooks.run_hook(
                "post-action",
                {"event_type": "create", "payload": {}},
                str(tmp_path),
            )

        _, stderr = capfd.readouterr()
        assert "intentional error" in stderr
        assert "exited with code 1" in stderr

    def test_silent_when_no_hook(self, monkeypatch, tmp_path, capfd):
        """run_hook is silent when no hook exists."""
        from unittest.mock import patch

        from config import SpexContext

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            hooks.run_hook(
                "post-action",
                {"event_type": "init", "payload": {}},
            )

        stdout, stderr = capfd.readouterr()
        assert stdout == ""
        assert stderr == ""


# ===================== run_post_action =====================


class TestRunPostAction:
    def test_delegates_to_run_hook(self, monkeypatch, tmp_path):
        """run_post_action calls run_hook with 'post-action' name."""
        from unittest.mock import patch

        from config import SpexContext

        monkeypatch.setattr(
            "hooks._build_event_data",
            lambda *a, **k: {
                "user": "Test",
                "email": "test@test.com",
                "workdir": "/tmp",
                "event_type": "apply",
                "payload": {"foo": "bar", "topic_name": "my-topic"},
            },
        )

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        output_file = tmp_path / "hook_output.txt"
        hook_file = hooks_dir / "post-action"
        hook_file.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            "data = json.loads(sys.stdin.read())\n"
            f"open('{output_file}', 'w').write(f'topic={{data[\"payload\"][\"topic_name\"]}}')\n"
        )
        os.chmod(hook_file, 0o755)

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            hooks.run_post_action(
                "apply", {"foo": "bar"}, str(tmp_path), topic_name="my-topic"
            )

        assert output_file.read_text() == "topic=my-topic"
