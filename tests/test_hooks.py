"""Tests for hooks.py: hook resolution, execution, and event data."""

import json
import logging
import os
from pathlib import Path

import hooks
import pytest
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

        from config import ProjectContext

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            roots = hooks._resolve_hook_roots()

        assert len(roots) >= 1
        assert roots[0] == Path(str(tmp_path)) / "hooks"


# ===================== find_hook =====================


class TestFindHook:
    def test_finds_in_spex_root(self, monkeypatch, tmp_path):
        """Hook found in spex_root/hooks/ takes priority."""
        from unittest.mock import patch

        from config import ProjectContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text("#!/bin/bash\necho ok")
        os.chmod(hook_file, 0o755)

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.find_hook("post-action")
        assert result == hook_file

    def test_ignores_hooks_outside_selected_root(self, monkeypatch, tmp_path):
        from unittest.mock import patch

        from config import ProjectContext

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

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(primary),
            spex_roots=[str(primary), str(secondary)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            clear_spex_root_cache()
            result = hooks.find_hook("post-action")
            assert result is None

    def test_primary_spex_root_overrides_secondary(self, monkeypatch, tmp_path):
        """Primary spex_root hook wins over secondary spex_root hook."""
        from unittest.mock import patch

        from config import ProjectContext

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

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(primary),
            spex_roots=[str(primary), str(secondary)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            clear_spex_root_cache()
            result = hooks.find_hook("post-action")
            assert result == primary_hook

    def test_skips_non_executable(self, monkeypatch, tmp_path):
        """Non-executable file is skipped."""
        from unittest.mock import patch

        from config import ProjectContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text("#!/bin/bash")
        # Do NOT chmod +x

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.find_hook("post-action")
        assert result is None

    def test_returns_none_when_missing(self, monkeypatch, tmp_path):
        """No hook found anywhere returns None."""
        from unittest.mock import patch

        from config import ProjectContext

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.find_hook("post-action")
        assert result is None


# ===================== _build_event_data =====================


@pytest.mark.slow
class TestBuildEventData:
    def test_builds_envelope(self, monkeypatch, tmp_path):
        """_build_event_data builds correct structure."""
        monkeypatch.chdir(tmp_path)
        # Prevent GIT_CONFIG_PARAMETERS (set by git -c) from overriding
        # the local repo config in subprocess calls.
        monkeypatch.delenv("GIT_CONFIG_PARAMETERS", raising=False)

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


@pytest.mark.slow
class TestRunHook:
    def test_executes_and_passes_json(self, monkeypatch, tmp_path):
        """run_hook executes hook and passes JSON to stdin."""
        from unittest.mock import patch

        from config import ProjectContext

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

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            hooks.run_hook(
                "post-action",
                {"event_type": "apply", "payload": {}},
                str(tmp_path),
            )

        assert output_file.read_text() == "event=apply"

    def test_logs_error_on_failure(self, monkeypatch, tmp_path, caplog):
        """run_hook logs stderr when hook exits non-zero."""
        from unittest.mock import patch

        from config import ProjectContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "post-action"
        hook_file.write_text(
            "#!/bin/bash\necho 'intentional error' >&2; exit 1\n"
        )
        os.chmod(hook_file, 0o755)

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with caplog.at_level(logging.WARNING):
            with patch("common.get_project_storage", return_value=ctx):
                hooks.run_hook(
                    "post-action",
                    {"event_type": "create", "payload": {}},
                    str(tmp_path),
                )

        assert "intentional error" in caplog.text
        assert "exited with code 1" in caplog.text

    def test_silent_when_no_hook(self, monkeypatch, tmp_path, capfd):
        """run_hook is silent when no hook exists."""
        from unittest.mock import patch

        from config import ProjectContext

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            hooks.run_hook(
                "post-action",
                {"event_type": "init", "payload": {}},
            )

        stdout, stderr = capfd.readouterr()
        assert stdout == ""
        assert stderr == ""


# ===================== run_post_action =====================


@pytest.mark.slow
class TestRunPostAction:
    def test_delegates_to_run_hook(self, monkeypatch, tmp_path):
        """run_post_action calls run_hook with 'post-action' name."""
        from unittest.mock import patch

        from config import ProjectContext

        monkeypatch.setattr(
            "hooks._build_event_data",
            lambda *a, **k: {
                "user": "Test",
                "email": "test@test.com",
                "workdir": "/tmp",
                "event_type": "apply",
                "payload": {"foo": "bar", "spec_name": "my-topic"},
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
            f"open('{output_file}', 'w').write(f'topic={{data[\"payload\"][\"spec_name\"]}}')\n"
        )
        os.chmod(hook_file, 0o755)

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            hooks.run_post_action(
                "apply", {"foo": "bar"}, str(tmp_path), spec_name="my-topic"
            )

        assert output_file.read_text() == "topic=my-topic"


# ===================== run_hook return value =====================


@pytest.mark.slow
class TestRunHookReturnValue:
    def test_returns_none_when_no_hook(self, monkeypatch, tmp_path):
        """run_hook returns None when no hook is found."""
        from unittest.mock import patch

        from config import ProjectContext

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.run_hook(
                "pre-action",
                {"event_type": "create", "payload": {}},
            )

        assert result is None

    def test_returns_completed_process_on_success(self, monkeypatch, tmp_path):
        """run_hook returns CompletedProcess when hook succeeds."""
        import subprocess
        from unittest.mock import patch

        from config import ProjectContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "pre-action"
        hook_file.write_text("#!/bin/bash\nexit 0\n")
        os.chmod(hook_file, 0o755)

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.run_hook(
                "pre-action",
                {"event_type": "create", "payload": {}},
                str(tmp_path),
            )

        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 0

    def test_returns_completed_process_on_failure(self, monkeypatch, tmp_path):
        """run_hook returns CompletedProcess even when hook fails."""
        import subprocess
        from unittest.mock import patch

        from config import ProjectContext

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "pre-action"
        hook_file.write_text("#!/bin/bash\nexit 2\n")
        os.chmod(hook_file, 0o755)

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.run_hook(
                "pre-action",
                {"event_type": "create", "payload": {}},
                str(tmp_path),
            )

        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 2


# ===================== run_pre_action =====================


@pytest.mark.slow
class TestRunPreAction:
    def test_delegates_to_run_hook(self, monkeypatch, tmp_path):
        """run_pre_action calls run_hook with 'pre-action' name."""
        from unittest.mock import patch

        from config import ProjectContext

        monkeypatch.setattr(
            "hooks._build_event_data",
            lambda *a, **k: {
                "user": "Test",
                "email": "test@test.com",
                "workdir": "/tmp",
                "event_type": "create",
                "payload": {"topic": "feat", "spec_name": "my-spec"},
            },
        )

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        output_file = tmp_path / "hook_output.txt"
        hook_file = hooks_dir / "pre-action"
        hook_file.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            "data = json.loads(sys.stdin.read())\n"
            f"open('{output_file}', 'w').write(f'spec={{data[\"payload\"][\"spec_name\"]}}')\n"
        )
        os.chmod(hook_file, 0o755)

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            hooks.run_pre_action(
                "create", {"topic": "feat"}, str(tmp_path),
                spec_name="my-spec",
            )

        assert output_file.read_text() == "spec=my-spec"

    def test_exits_on_hook_failure(self, monkeypatch, tmp_path):
        """run_pre_action calls sys.exit(1) when hook exits non-zero."""
        from unittest.mock import patch

        from config import ProjectContext

        monkeypatch.setattr(
            "hooks._build_event_data",
            lambda *a, **k: {
                "user": "Test",
                "email": "test@test.com",
                "workdir": "/tmp",
                "event_type": "apply",
                "payload": {},
            },
        )

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "pre-action"
        hook_file.write_text(
            "#!/bin/bash\necho 'denied by policy' >&2; exit 1\n"
        )
        os.chmod(hook_file, 0o755)

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            with pytest.raises(SystemExit) as exc_info:
                hooks.run_pre_action(
                    "apply", {}, str(tmp_path),
                )

        assert exc_info.value.code == 1

    def test_no_exit_on_hook_success(self, monkeypatch, tmp_path):
        """run_pre_action does not exit when hook succeeds."""
        from unittest.mock import patch

        from config import ProjectContext

        monkeypatch.setattr(
            "hooks._build_event_data",
            lambda *a, **k: {
                "user": "Test",
                "email": "test@test.com",
                "workdir": "/tmp",
                "event_type": "create",
                "payload": {},
            },
        )

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "pre-action"
        hook_file.write_text("#!/bin/bash\nexit 0\n")
        os.chmod(hook_file, 0o755)

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            # Should not raise SystemExit
            hooks.run_pre_action(
                "create", {}, str(tmp_path),
            )

    def test_no_exit_when_no_hook(self, monkeypatch, tmp_path):
        """run_pre_action does not exit when no hook is found."""
        from unittest.mock import patch

        from config import ProjectContext

        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        with patch("common.get_project_storage", return_value=ctx):
            # Should not raise SystemExit
            hooks.run_pre_action(
                "create", {}, str(tmp_path),
            )


# ===================== hook path confinement =====================


def _hook_project_ctx(tmp_path):
    from config import ProjectContext

    return ProjectContext(
        cwd=tmp_path,
        top_workdir=tmp_path,
        main_worktree=tmp_path,
        remote_url="",
        branch="",
        user_name="",
        user_email="",
        spex_tomls=[],
        config={},
        spex_root=str(tmp_path),
        spex_roots=[str(tmp_path)],
    )


@pytest.mark.parametrize("action", ["pre", "post"])
@pytest.mark.parametrize(
    "hook_state",
    ["missing", "non-executable", "outside-root", "world-writable"],
)
def test_action_skips_event_construction(tmp_path, monkeypatch, action, hook_state):
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    hook = hook_dir / f"{action}-action"
    if hook_state == "outside-root":
        outside = tmp_path / "outside"
        outside.touch(mode=0o755)
        hook.symlink_to(outside)
    elif hook_state != "missing":
        hook.touch()
        hook.chmod(0o777 if hook_state == "world-writable" else 0o644)

    monkeypatch.setattr(hooks, "_resolve_hook_roots", lambda _cwd: [hook_dir])

    def unexpected(*_args, **_kwargs):
        pytest.fail("Skipped hook must not build an event or start a process")

    monkeypatch.setattr(hooks, "get_project_context", unexpected)
    monkeypatch.setattr(hooks.subprocess, "run", unexpected)
    getattr(hooks, f"run_{action}_action")("modify", {}, str(tmp_path))


@pytest.mark.parametrize("action", ["pre", "post"])
def test_action_preserves_event_and_nonzero_behavior(
    tmp_path, monkeypatch, caplog, action,
):
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    hook = hook_dir / f"{action}-action"
    hook.touch(mode=0o755)
    workdir = str(tmp_path)
    ctx = _hook_project_ctx(tmp_path)
    ctx.user_name = "Spex User"
    ctx.user_email = "spex@example.org"
    monkeypatch.setattr(hooks, "_resolve_hook_roots", lambda _cwd: [hook_dir])

    def get_context(cwd):
        assert cwd == workdir
        return ctx

    monkeypatch.setattr(hooks, "get_project_context", get_context)
    payload = {"spex_branch": "spex/example"}

    def run(argv, *, input, capture_output, text, cwd):
        assert argv == [str(hook)]
        assert capture_output and text
        assert cwd == workdir
        event = json.loads(input)
        assert event.pop("time")
        assert event == {
            "user": "Spex User",
            "email": "spex@example.org",
            "workdir": workdir,
            "event_type": "modify",
            "payload": {**payload, "spec_name": "example"},
        }
        return hooks.subprocess.CompletedProcess(argv, 7, stderr="hook failure")

    monkeypatch.setattr(hooks.subprocess, "run", run)
    if action == "pre":
        with pytest.raises(SystemExit) as exc_info:
            hooks.run_pre_action("modify", payload, workdir, spec_name="example")
        assert exc_info.value.code == 1
    else:
        hooks.run_post_action("modify", payload, workdir, spec_name="example")
    assert "exited with code 7" in caplog.text
    assert "hook failure" in caplog.text
    assert payload == {"spex_branch": "spex/example"}


class TestHookConfinement:
    def test_normal_0755_hook_still_runs(self, tmp_path):
        """A mode 0755 hook inside the hook root is executed."""
        from unittest.mock import patch

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        marker = tmp_path / "ran.txt"
        hook_file = hooks_dir / "post-action"
        hook_file.write_text(f"#!/bin/bash\necho ran > '{marker}'\n")
        os.chmod(hook_file, 0o755)

        ctx = _hook_project_ctx(tmp_path)
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.run_hook(
                "post-action",
                {"event_type": "apply", "payload": {}},
                str(tmp_path),
            )

        assert result is not None
        assert result.returncode == 0
        assert marker.read_text().strip() == "ran"

    def test_symlink_outside_hook_root_not_executed(self, tmp_path):
        """A symlink pointing outside the hook root is not executed."""
        from unittest.mock import patch

        outside = tmp_path / "outside"
        outside.mkdir()
        marker = tmp_path / "pwned.txt"
        evil = outside / "evil.sh"
        evil.write_text(f"#!/bin/bash\necho pwned > '{marker}'\nexit 1\n")
        os.chmod(evil, 0o755)

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "pre-action"
        hook_file.symlink_to(evil)

        ctx = _hook_project_ctx(tmp_path)
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.run_hook(
                "pre-action",
                {"event_type": "create", "payload": {}},
                str(tmp_path),
            )
            hooks.run_pre_action("create", {}, str(tmp_path))

        assert result is None
        assert not marker.exists()

    def test_world_writable_hook_not_executed(self, tmp_path):
        """A world-writable hook file is not executed."""
        from unittest.mock import patch

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        marker = tmp_path / "ran.txt"
        hook_file = hooks_dir / "pre-action"
        hook_file.write_text(f"#!/bin/bash\necho ran > '{marker}'\nexit 1\n")
        os.chmod(hook_file, 0o777)

        ctx = _hook_project_ctx(tmp_path)
        with patch("common.get_project_storage", return_value=ctx):
            result = hooks.run_hook(
                "pre-action",
                {"event_type": "create", "payload": {}},
                str(tmp_path),
            )
            hooks.run_pre_action("create", {}, str(tmp_path))

        assert result is None
        assert not marker.exists()
