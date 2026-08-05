"""Tests for debug_log.py: enablement, path resolution, tee, and tracing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from config import ProjectContext, clear_config_cache
from debug_log import (
    MAX_STREAM_BYTES,
    PROMPT_STDOUT_LOG_BYTES,
    TeeIO,
    clear_active_session,
    debug_enabled,
    get_active_session_id,
    is_prompt_argv,
    merge_session_log_into_spec,
    parse_flag_from_argv,
    parse_name_from_argv,
    resolve_debug_log_path,
    session_debug_log_path,
    set_active_session,
    trace_command,
    validate_session_id,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_config_cache()
    yield
    clear_config_cache()


def _make_ctx(tmp_path: Path, *, debug: bool = False) -> ProjectContext:
    spex_root = tmp_path / ".spex"
    specs_dir = spex_root / "specs"
    spec_dir = specs_dir / "my-spec"
    spec_dir.mkdir(parents=True)
    return ProjectContext(
        cwd=tmp_path,
        top_workdir=tmp_path,
        main_worktree=tmp_path,
        remote_url="",
        branch="",
        user_name="",
        user_email="",
        spex_tomls=[],
        config={"debug": debug},
        spex_root=str(spex_root),
        spex_roots=[str(spex_root)],
    )


def _activate_session(spex_root: str | Path, session_id: str = "20260804T155021-a1b2") -> str:
    set_active_session(spex_root, session_id)
    log_path = session_debug_log_path(spex_root, session_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return session_id


class TestDebugEnabled:
    def test_enabled_by_cli_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("debug_log.get_project_context", return_value=_make_ctx(tmp_path)):
            assert debug_enabled(["spex", "-d", "version"]) is True
            assert debug_enabled(["spex", "--debug", "version"]) is True

    def test_enabled_by_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch(
            "debug_log.get_project_context",
            return_value=_make_ctx(tmp_path, debug=True),
        ):
            assert debug_enabled(["spex", "version"]) is True

    def test_disabled_without_flag_or_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("debug_log.get_project_context", return_value=_make_ctx(tmp_path)):
            assert debug_enabled(["spex", "version"]) is False


class TestParseNameFromArgv:
    def test_space_form(self):
        assert parse_name_from_argv(["prompt", "--name", "foo"]) == "foo"

    def test_equals_form(self):
        assert parse_name_from_argv(["todo-helper", "--name=bar"]) == "bar"

    def test_missing(self):
        assert parse_name_from_argv(["spex", "version"]) is None


class TestParseFlagFromArgv:
    def test_step_and_commit(self):
        argv = ["spex", "prompt", "apply-review", "--step", "step-1", "--commit=abc"]
        assert parse_flag_from_argv(argv, "--step") == "step-1"
        assert parse_flag_from_argv(argv, "--commit") == "abc"

    def test_missing(self):
        assert parse_flag_from_argv(["spex", "version"], "--step") is None


class TestIsPromptArgv:
    def test_prompt_after_debug_flag(self):
        assert is_prompt_argv(["spex", "-d", "prompt", "apply-one-task"]) is True

    def test_non_prompt(self):
        assert is_prompt_argv(["spex", "todo-helper", "show"]) is False


class TestSessionHelpers:
    def test_get_set_clear_active_session(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        assert get_active_session_id(spex_root) is None

        set_active_session(spex_root, "sess-1")
        assert get_active_session_id(spex_root) == "sess-1"
        assert session_debug_log_path(spex_root, "sess-1") == (
            (spex_root / "sessions").resolve() / "sess-1" / "debug.log"
        )

        clear_active_session(spex_root)
        assert get_active_session_id(spex_root) is None

    @pytest.mark.parametrize(
        "bad_id",
        [
            "",
            "   ",
            ".",
            "..",
            "../outside",
            "../../outside",
            "a/b",
            "a\\b",
            "id with space",
            "active",
            "Active",
            "ACTIVE",
        ],
    )
    def test_validate_session_id_rejects_unsafe(self, bad_id):
        with pytest.raises(ValueError):
            validate_session_id(bad_id)

    @pytest.mark.parametrize(
        "bad_id",
        ["..", "../outside", "../../outside", "a/b", ".", "active", "ACTIVE"],
    )
    def test_set_active_session_rejects_path_traversal(self, tmp_path, bad_id):
        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        with pytest.raises(ValueError):
            set_active_session(spex_root, bad_id)
        assert get_active_session_id(spex_root) is None

    def test_set_active_session_rejects_reserved_active_id(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        with pytest.raises(ValueError, match="reserved"):
            set_active_session(spex_root, "active")
        assert get_active_session_id(spex_root) is None
        set_active_session(spex_root, "sess-ok")
        assert get_active_session_id(spex_root) == "sess-ok"

    def test_get_active_session_id_ignores_unsafe_pointer(self, tmp_path):
        spex_root = tmp_path / ".spex"
        pointer = spex_root / "sessions" / "active"
        pointer.parent.mkdir(parents=True)
        pointer.write_text("../../outside\n", encoding="utf-8")
        assert get_active_session_id(spex_root) is None

    def test_session_debug_log_path_stays_under_sessions(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        sessions = (spex_root / "sessions").resolve()
        path = session_debug_log_path(spex_root, "20260804T155021-a1b2")
        assert path == sessions / "20260804T155021-a1b2" / "debug.log"
        assert path.is_relative_to(sessions)
        with pytest.raises(ValueError):
            session_debug_log_path(spex_root, "../../outside")

    def test_merge_invalid_session_id_returns_none(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "my-spec"
        spec_dir.mkdir(parents=True)
        assert merge_session_log_into_spec(spex_root, "../outside", spec_dir) is None

    def test_merge_session_log_into_spec_copies_then_deletes(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "my-spec"
        spec_dir.mkdir(parents=True)
        session_id = _activate_session(spex_root)
        session_log = session_debug_log_path(spex_root, session_id)
        session_log.write_text("===== session history =====\n", encoding="utf-8")

        target = merge_session_log_into_spec(spex_root, session_id, spec_dir)

        assert target == spec_dir / "debug.log"
        assert target.read_text(encoding="utf-8").startswith(
            "===== session history =====\n"
        )
        assert not session_log.exists()
        assert not session_log.parent.exists()
        assert not (spec_dir / "debug.session-pre.log").exists()
        # merge does not clear the active pointer
        assert get_active_session_id(spex_root) == session_id

    def test_merge_appends_to_existing_spec_debug_log(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "my-spec"
        spec_dir.mkdir(parents=True)
        existing = "===== existing spec log =====\n"
        (spec_dir / "debug.log").write_text(existing, encoding="utf-8")
        session_id = _activate_session(spex_root)
        session_log = session_debug_log_path(spex_root, session_id)
        session_body = "===== session history =====\n"
        session_log.write_text(session_body, encoding="utf-8")

        target = merge_session_log_into_spec(spex_root, session_id, spec_dir)

        assert target == spec_dir / "debug.log"
        assert target.read_text(encoding="utf-8") == existing + session_body
        assert not session_log.exists()
        assert not session_log.parent.exists()
        assert get_active_session_id(spex_root) == session_id

    def test_merge_empty_session_log_deletes_without_creating_target(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "my-spec"
        spec_dir.mkdir(parents=True)
        session_id = _activate_session(spex_root)
        session_log = session_debug_log_path(spex_root, session_id)
        session_log.write_text("", encoding="utf-8")

        target = merge_session_log_into_spec(spex_root, session_id, spec_dir)

        assert target == spec_dir / "debug.log"
        assert not session_log.exists()
        assert not (spec_dir / "debug.log").exists()

    def test_merge_missing_session_log_returns_none(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "my-spec"
        spec_dir.mkdir(parents=True)
        assert merge_session_log_into_spec(spex_root, "missing", spec_dir) is None

    def test_merge_missing_log_removes_empty_session_dir(self, tmp_path):
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "my-spec"
        spec_dir.mkdir(parents=True)
        session_id = _activate_session(spex_root)
        session_log = session_debug_log_path(spex_root, session_id)
        assert session_log.parent.is_dir()
        assert not session_log.exists()

        target = merge_session_log_into_spec(spex_root, session_id, spec_dir)

        assert target is None
        assert not session_log.parent.exists()
        assert get_active_session_id(spex_root) == session_id

    def test_merge_relocates_prev_end_sidecar_and_gap_continues(
        self, tmp_path, monkeypatch
    ):
        """Session .prev_end must move with merge so dir cleans and gap_ms works."""
        from datetime import datetime, timedelta, timezone

        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path, debug=True)
        spex_root = Path(ctx.spex_root)
        spec_dir = spex_root / "specs" / "my-spec"
        session_id = _activate_session(spex_root)
        session_log = session_debug_log_path(spex_root, session_id)

        tz = timezone(timedelta(hours=8))
        t0 = datetime(2026, 8, 4, 17, 0, 0, tzinfo=tz)
        t1 = t0 + timedelta(seconds=3)
        stamps = iter([t0.isoformat(), t1.isoformat()])
        monkeypatch.setattr(
            "debug_log.local_iso_timestamp",
            lambda: next(stamps),
        )

        with patch("debug_log.get_project_context", return_value=ctx):
            with trace_command(session_log, ["spex", "version"]):
                print("session")

        session_sidecar = Path(str(session_log) + ".prev_end")
        assert session_sidecar.is_file()

        target = merge_session_log_into_spec(spex_root, session_id, spec_dir)

        assert target == spec_dir / "debug.log"
        assert not session_log.exists()
        assert not session_sidecar.exists()
        assert not session_log.parent.exists()

        target_sidecar = Path(str(target) + ".prev_end")
        assert target_sidecar.is_file()
        assert target_sidecar.read_text(encoding="utf-8").strip() == t0.isoformat()

        with patch("debug_log.get_project_context", return_value=ctx):
            with trace_command(
                target, ["spex", "version", "--name", "my-spec"]
            ):
                print("after-merge")

        metas = [
            line
            for line in target.read_text(encoding="utf-8").splitlines()
            if line.startswith("meta:")
        ]
        assert metas
        last_meta = metas[-1]
        assert "gap_ms=" in last_meta
        gap = int(last_meta.split("gap_ms=")[1].split()[0])
        assert gap == 3000


class TestResolveDebugLogPath:
    def test_with_name_resolves_spec_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "--name", "my-spec"])
        assert path == Path(ctx.spex_root) / "specs" / "my-spec" / "debug.log"

    def test_name_wins_over_active_session(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        session_id = _activate_session(ctx.spex_root)
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "--name", "my-spec"])
        assert path == Path(ctx.spex_root) / "specs" / "my-spec" / "debug.log"
        assert path != session_debug_log_path(ctx.spex_root, session_id)

    def test_active_session_without_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        session_id = _activate_session(ctx.spex_root)
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "version"])
        assert path == session_debug_log_path(ctx.spex_root, session_id)

    def test_unsafe_active_pointer_falls_back_to_spex_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        pointer = Path(ctx.spex_root) / "sessions" / "active"
        pointer.parent.mkdir(parents=True)
        pointer.write_text("../../outside\n", encoding="utf-8")
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "version"])
        assert path == Path(ctx.spex_root) / "debug.log"

    def test_without_name_uses_spex_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "version"])
        assert path == Path(ctx.spex_root) / "debug.log"

    def test_unknown_name_falls_back_to_spex_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "--name", "missing"])
        assert path == Path(ctx.spex_root) / "debug.log"

    def test_unknown_name_uses_active_session(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        session_id = _activate_session(ctx.spex_root)
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "--name", "missing"])
        assert path == session_debug_log_path(ctx.spex_root, session_id)

    def test_ambiguous_name_falls_back_to_spex_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        specs_dir = Path(ctx.spex_root) / "specs"
        (specs_dir / "2026-01-01-foo").mkdir()
        (specs_dir / "2026-01-01-foo-bar").mkdir()
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "--name", "foo"])
        assert path == Path(ctx.spex_root) / "debug.log"

    def test_ambiguous_name_uses_active_session(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        specs_dir = Path(ctx.spex_root) / "specs"
        (specs_dir / "2026-01-01-foo").mkdir()
        (specs_dir / "2026-01-01-foo-bar").mkdir()
        session_id = _activate_session(ctx.spex_root)
        with patch("debug_log.get_project_context", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "--name", "foo"])
        assert path == session_debug_log_path(ctx.spex_root, session_id)

    def test_no_spex_root_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
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
            spex_root="",
            spex_roots=[],
        )
        with patch("debug_log.get_project_context", return_value=ctx):
            assert resolve_debug_log_path(["spex", "version"]) is None


class TestTeeIO:
    def test_truncates_after_cap(self):
        parts: list[str] = []
        meta = {"buffered_bytes": 0, "total_bytes": 0, "truncated": False}

        class FakeStream:
            def write(self, data: str) -> int:
                return len(data)

            def flush(self) -> None:
                pass

        tee = TeeIO(FakeStream(), parts, meta)
        chunk = "x" * (MAX_STREAM_BYTES + 1024)
        tee.write(chunk)

        captured = "".join(parts)
        assert len(captured.encode("utf-8")) <= MAX_STREAM_BYTES
        assert meta["truncated"] is True
        assert meta["total_bytes"] == len(chunk.encode("utf-8"))


class TestTraceCommand:
    @pytest.fixture(autouse=True)
    def _fallback_flush_path(self, monkeypatch):
        """Keep flush on the explicit log_path unless a test overrides resolve."""
        monkeypatch.setattr(
            "debug_log.resolve_debug_log_path",
            lambda _argv: None,
        )

    def test_writes_begin_end_and_preserves_stdout(self, tmp_path, capsys):
        log_path = tmp_path / "debug.log"
        argv = ["spex", "version"]

        with trace_command(log_path, argv):
            print("hello stdout")
            print("hello stderr", file=__import__("sys").stderr)

        output = capsys.readouterr()
        assert output.out == "hello stdout\n"
        assert output.err == "hello stderr\n"

        content = log_path.read_text(encoding="utf-8")
        assert "===== BEGIN " in content
        assert "argv: spex version" in content
        assert "meta:" in content
        assert "----- stdout -----" in content
        assert "hello stdout" in content
        assert "----- stderr -----" in content
        assert "hello stderr" in content
        assert "===== END exit=0 duration_ms=" in content

    def test_records_nonzero_exit_on_system_exit(self, tmp_path):
        log_path = tmp_path / "debug.log"

        with pytest.raises(SystemExit) as exc_info:
            with trace_command(log_path, ["spex", "bad"]):
                raise SystemExit(2)

        assert exc_info.value.code == 2
        content = log_path.read_text(encoding="utf-8")
        assert "===== END exit=2 duration_ms=" in content

    def test_records_exit_one_on_runtime_error(self, tmp_path):
        log_path = tmp_path / "debug.log"

        with pytest.raises(RuntimeError, match="boom"):
            with trace_command(log_path, ["spex", "bad"]):
                raise RuntimeError("boom")

        content = log_path.read_text(encoding="utf-8")
        assert "===== END exit=1 duration_ms=" in content

    def test_truncation_marker_in_log(self, tmp_path):
        log_path = tmp_path / "debug.log"
        big = "y" * (MAX_STREAM_BYTES + 512)

        with trace_command(log_path, ["spex", "big"]):
            print(big)

        content = log_path.read_text(encoding="utf-8")
        assert "[truncated, total" in content

    def test_io_error_does_not_change_stdout(self, tmp_path, capsys, monkeypatch):
        log_path = tmp_path / "readonly" / "debug.log"

        def fail_open(*_args, **_kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "open", fail_open)

        with trace_command(log_path, ["spex", "version"]):
            print("still works")

        assert capsys.readouterr().out == "still works\n"
        assert not log_path.exists()

    def test_reresolves_flush_path_after_handoff(self, tmp_path, monkeypatch):
        """Flush must not recreate a deleted session log after routing changes."""
        session_log = tmp_path / "sessions" / "sess-1" / "debug.log"
        spec_log = tmp_path / "specs" / "my-spec" / "debug.log"
        session_log.parent.mkdir(parents=True)
        spec_log.parent.mkdir(parents=True)
        argv = [
            "spex", "create-helper", "prepare-spec",
            "--name", "my-spec", "--description", "d",
        ]

        def resolve_after_handoff(_argv):
            return spec_log

        monkeypatch.setattr(
            "debug_log.resolve_debug_log_path",
            resolve_after_handoff,
        )

        with trace_command(session_log, argv):
            # Simulate prepare-spec handoff: session log removed mid-command.
            if session_log.exists():
                session_log.unlink()

        assert not session_log.exists()
        content = spec_log.read_text(encoding="utf-8")
        assert "argv: spex create-helper prepare-spec" in content
        assert "===== END exit=0 duration_ms=" in content

    def test_prompt_stdout_summarized_caller_sees_full(
        self, tmp_path, capsys
    ):
        import json
        import sys

        log_path = tmp_path / "debug.log"
        argv = ["spex", "prompt", "apply-one-task", "--name", "my-spec", "--json"]
        prompt_body = "x" * 8000
        payload = {
            "task_id": "step-3",
            "prompt": prompt_body,
            "resume_phase": "implement",
            "commit_title": "fix(debug): truncate prompt stdout",
        }
        full = json.dumps(payload)

        with trace_command(log_path, argv):
            sys.stdout.write(full)
            sys.stdout.flush()

        assert capsys.readouterr().out == full

        content = log_path.read_text(encoding="utf-8")
        stdout_section = content.split("----- stdout -----", 1)[1].split(
            "----- stderr -----", 1
        )[0]
        assert "truncated prompt stdout" in stdout_section
        assert f"total={len(full.encode('utf-8'))}B" in stdout_section
        assert "task_id=step-3" in stdout_section
        assert "prompt_len=8000" in stdout_section
        assert "keys=" in stdout_section
        assert prompt_body not in stdout_section
        assert len(stdout_section) < len(full)

    def test_prompt_plain_stdout_truncated_in_log(self, tmp_path, capsys):
        import sys

        log_path = tmp_path / "debug.log"
        argv = ["spex", "prompt", "apply-commit", "--name", "my-spec"]
        big = "P" * (PROMPT_STDOUT_LOG_BYTES + 1500)

        with trace_command(log_path, argv):
            sys.stdout.write(big)
            sys.stdout.flush()

        assert capsys.readouterr().out == big
        content = log_path.read_text(encoding="utf-8")
        stdout_section = content.split("----- stdout -----", 1)[1].split(
            "----- stderr -----", 1
        )[0]
        assert "truncated prompt stdout" in stdout_section
        assert f"total={len(big.encode('utf-8'))}B" in stdout_section
        assert big not in stdout_section

    def test_non_prompt_stdout_still_recorded_in_full(self, tmp_path):
        log_path = tmp_path / "debug.log"
        body = "keep-me-" + ("n" * 500)

        with trace_command(log_path, ["spex", "todo-helper", "show"]):
            print(body)

        content = log_path.read_text(encoding="utf-8")
        assert body in content
        assert "truncated prompt stdout" not in content

    def test_meta_gap_ms_and_argv_fields(self, tmp_path, monkeypatch):
        from datetime import datetime, timedelta, timezone

        log_path = tmp_path / "debug.log"
        tz = timezone(timedelta(hours=8))
        t0 = datetime(2026, 8, 4, 17, 0, 0, tzinfo=tz)
        t1 = t0 + timedelta(seconds=5)
        stamps = iter([t0.isoformat(), t1.isoformat()])
        monkeypatch.setattr(
            "debug_log.local_iso_timestamp",
            lambda: next(stamps),
        )

        with trace_command(log_path, ["spex", "version"]):
            print("first")

        with trace_command(
            log_path,
            [
                "spex",
                "review-helper",
                "status",
                "--step",
                "step-3",
                "--commit",
                "deadbeef",
            ],
        ):
            print("second")

        content = log_path.read_text(encoding="utf-8")
        blocks = content.split("===== BEGIN ")
        assert len(blocks) == 3  # leading empty + 2 blocks
        first_meta = [
            line for line in blocks[1].splitlines() if line.startswith("meta:")
        ][0]
        second_meta = [
            line for line in blocks[2].splitlines() if line.startswith("meta:")
        ][0]
        assert "gap_ms=" not in first_meta
        assert "step=step-3" in second_meta
        assert "commit=deadbeef" in second_meta
        assert "gap_ms=" in second_meta
        gap = int(second_meta.split("gap_ms=")[1].split()[0])
        # BEGIN is stamped at flush (end); gap is stamp delta, not minus duration
        assert gap == 5000

    def test_meta_gap_ms_ignores_begin_end_in_stdout(self, tmp_path, monkeypatch):
        """Embedded BEGIN/END in stdout must not poison gap_ms."""
        from datetime import datetime, timedelta, timezone

        log_path = tmp_path / "debug.log"
        tz = timezone(timedelta(hours=8))
        t0 = datetime(2026, 8, 4, 17, 0, 0, tzinfo=tz)
        t1 = t0 + timedelta(seconds=5)
        stamps = iter([t0.isoformat(), t1.isoformat()])
        monkeypatch.setattr(
            "debug_log.local_iso_timestamp",
            lambda: next(stamps),
        )

        fake_later = (t0 + timedelta(hours=1)).isoformat()
        poison = (
            f"===== BEGIN {fake_later} =====\n"
            "argv: spex version\n"
            "meta:\n"
            "===== END exit=0 duration_ms=999999 =====\n"
        )
        with trace_command(log_path, ["spex", "version"]):
            print(poison, end="")

        with trace_command(log_path, ["spex", "version"]):
            print("second")

        content = log_path.read_text(encoding="utf-8")
        # Last structural meta is the second real block (poison meta is earlier).
        metas = [
            line for line in content.splitlines() if line.startswith("meta:")
        ]
        assert metas
        last_meta = metas[-1]
        assert "gap_ms=" in last_meta
        gap = int(last_meta.split("gap_ms=")[1].split()[0])
        assert gap == 5000
