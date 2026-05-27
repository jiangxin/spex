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
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    clear_spex_root_cache()
    yield
    clear_spex_root_cache()


# ===================== _resolve_hook_roots =====================


class TestResolveHookRoots:
    def test_returns_two_paths_in_order(self, monkeypatch, tmp_path):
        """_resolve_hook_roots returns [spex_root/hooks, ~/.spex/hooks]."""
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        clear_spex_root_cache()

        roots = hooks._resolve_hook_roots()

        assert len(roots) == 2
        assert str(roots[0]).endswith("hooks")
        assert str(roots[1]) == str(Path.home() / ".spex" / "hooks")


# ===================== find_hook =====================


class TestFindHook:
    def test_finds_in_spex_root(self, monkeypatch, tmp_path):
        """Hook found in spex_root/hooks/ takes priority."""
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        clear_spex_root_cache()

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text("#!/bin/bash\necho ok")
        os.chmod(hook_file, 0o755)

        result = hooks.find_hook("post-action")
        assert result == hook_file

    def test_finds_in_home_spex(self, monkeypatch, tmp_path):
        """Hook found in ~/.spex/hooks/ when spex_root has none."""
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        monkeypatch.setattr("hooks.Path.home", lambda: tmp_path)
        clear_spex_root_cache()

        home_hooks = tmp_path / ".spex" / "hooks"
        home_hooks.mkdir(parents=True)
        hook_file = home_hooks / "post-action"
        hook_file.write_text("#!/bin/bash\necho ok")
        os.chmod(hook_file, 0o755)

        result = hooks.find_hook("post-action")
        assert result == hook_file

    def test_spex_root_overrides_home(self, monkeypatch, tmp_path):
        """spex_root hook wins over ~/.spex hook."""
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        monkeypatch.setattr("hooks.Path.home", lambda: tmp_path)
        clear_spex_root_cache()

        spex_hooks_dir = tmp_path / "hooks"
        spex_hooks_dir.mkdir()
        spex_hook = spex_hooks_dir / "post-action"
        spex_hook.write_text("#!/bin/bash\necho spex")
        os.chmod(spex_hook, 0o755)

        home_hooks = tmp_path / ".spex" / "hooks"
        home_hooks.mkdir(parents=True)
        home_hook = home_hooks / "post-action"
        home_hook.write_text("#!/bin/bash\necho home")
        os.chmod(home_hook, 0o755)

        result = hooks.find_hook("post-action")
        assert result == spex_hook

    def test_skips_non_executable(self, monkeypatch, tmp_path):
        """Non-executable file is skipped."""
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        clear_spex_root_cache()

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text("#!/bin/bash")
        # Do NOT chmod +x

        result = hooks.find_hook("post-action")
        assert result is None

    def test_returns_none_when_missing(self, monkeypatch, tmp_path):
        """No hook found anywhere returns None."""
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        clear_spex_root_cache()

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
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        clear_spex_root_cache()

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        output_file = tmp_path / "hook_output.txt"
        # Create a hook that reads stdin and writes result to a file
        hook_file = hooks_dir / "post-action"
        hook_file.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            "data = json.loads(sys.stdin.read())\n"
            f"open('{output_file}', 'w').write(f'event={{data[\"event_type\"]}}')\n"
        )
        os.chmod(hook_file, 0o755)

        hooks.run_hook(
            "post-action",
            {"event_type": "apply", "payload": {}},
            str(tmp_path),
        )

        assert output_file.read_text() == "event=apply"

    def test_logs_error_on_failure(self, monkeypatch, tmp_path, capfd):
        """run_hook logs stderr when hook exits non-zero."""
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        clear_spex_root_cache()

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text(
            "#!/bin/bash\necho 'intentional error' >&2; exit 1\n"
        )
        os.chmod(hook_file, 0o755)

        # Should not raise
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
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        clear_spex_root_cache()

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
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
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
        clear_spex_root_cache()

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

        hooks.run_post_action(
            "apply", {"foo": "bar"}, str(tmp_path), topic_name="my-topic"
        )

        assert output_file.read_text() == "topic=my-topic"
