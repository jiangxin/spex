"""Tests for debug_log.py: enablement, path resolution, tee, and tracing."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from config import ProjectContext, clear_config_cache
from debug_log import (
    MAX_STREAM_BYTES,
    PROMPT_STDOUT_LOG_BYTES,
    TeeIO,
    debug_enabled,
    emit_apply_anchor,
    is_prompt_argv,
    parse_flag_from_argv,
    parse_name_from_argv,
    resolve_debug_log_path,
    resolve_trace_file_path,
    safe_flush_debug_log_path,
    trace_command,
)


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    monkeypatch.delenv("SPEX_LOG_DIR", raising=False)
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


class TestDebugEnabled:
    def test_enabled_by_cli_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("debug_log.load_config", return_value={}):
            assert debug_enabled(["spex", "-d", "version"]) is True
            assert debug_enabled(["spex", "--debug", "version"]) is True

    def test_enabled_by_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch(
            "debug_log.load_config",
            return_value={"debug": True},
        ):
            assert debug_enabled(["spex", "version"]) is True

    def test_disabled_without_flag_or_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("debug_log.load_config", return_value={}):
            assert debug_enabled(["spex", "version"]) is False


@pytest.mark.parametrize("log_dir", [None, "   ", "trial-logs"])
def test_trace_path_precedence(tmp_path, monkeypatch, log_dir):
    ctx = _make_ctx(tmp_path)
    debug_path = Path(ctx.spex_root) / "specs" / "my-spec" / "logs" / "debug.log"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SPEX_TRACE_FILE", raising=False)
    if log_dir is not None:
        monkeypatch.setenv("SPEX_LOG_DIR", log_dir)
    shared = tmp_path / log_dir if log_dir and log_dir.strip() else None
    with patch("debug_log.get_project_storage", return_value=ctx):
        default = (shared or debug_path.parent) / "trace.jsonl"
        assert resolve_trace_file_path(debug_path).absolute() == default
        ctx.config["trace_file"] = "custom/configured.jsonl"
        configured = (shared or Path(ctx.spex_root)) / "custom/configured.jsonl"
        assert resolve_trace_file_path(debug_path).absolute() == configured
        absolute = tmp_path / "configured.jsonl"
        ctx.config["trace_file"] = str(absolute)
        assert resolve_trace_file_path(debug_path) == absolute
        monkeypatch.setenv("SPEX_TRACE_FILE", "override.jsonl")
        assert resolve_trace_file_path(debug_path).absolute() == (
            shared or tmp_path
        ) / "override.jsonl"
        monkeypatch.setenv("SPEX_TRACE_FILE", str(tmp_path / "explicit.jsonl"))
        assert resolve_trace_file_path(debug_path) == tmp_path / "explicit.jsonl"


def test_shared_cli_logs_preserve_spec_anchors(tmp_path, monkeypatch):
    ctx = _make_ctx(tmp_path, debug=True)
    spec_dir = Path(ctx.spex_root) / "specs" / "my-spec"
    log_dir = tmp_path / "cli-logs"
    monkeypatch.setenv("SPEX_LOG_DIR", str(log_dir))
    monkeypatch.delenv("SPEX_TRACE_FILE", raising=False)
    argv = ["spex", "prompt", "apply-one-task", "my-spec"]

    with patch("debug_log.get_project_storage", return_value=ctx):
        debug_path = resolve_debug_log_path(argv)
        assert debug_path == log_dir / "debug.log"
        with trace_command(debug_path, argv):
            emit_apply_anchor(spec_dir, "===== APPLY task begin =====", argv)

    assert "===== BEGIN " in debug_path.read_text(encoding="utf-8")
    span = json.loads((log_dir / "trace.jsonl").read_text(encoding="utf-8"))
    assert span["attributes"]["process.command_args"] == argv
    assert (spec_dir / "logs" / "debug.log").read_text(encoding="utf-8") == (
        "===== APPLY task begin =====\n"
    )


@pytest.mark.parametrize("trace_override", [None, "environment", "config"])
def test_explicit_log_routes_can_resemble_spec_paths(tmp_path, monkeypatch, trace_override):
    ctx = _make_ctx(tmp_path)
    log_dir = tmp_path / "capture" / "archives" / "trial" / "logs"
    trace_path = tmp_path / "capture" / "specs" / "trial" / "logs" / "explicit.jsonl"
    monkeypatch.setenv("SPEX_LOG_DIR", str(log_dir))
    monkeypatch.delenv("SPEX_TRACE_FILE", raising=False)
    if trace_override == "environment":
        monkeypatch.setenv("SPEX_TRACE_FILE", str(trace_path))
    elif trace_override == "config":
        ctx.config["trace_file"] = str(trace_path)
    else:
        trace_path = log_dir / "trace.jsonl"

    argv = ["spex", "prompt", "show", "my-spec"]
    with patch("debug_log.get_project_storage", return_value=ctx):
        debug_path = resolve_debug_log_path(argv)
        with trace_command(debug_path, argv):
            pass

        assert debug_path.is_file()
        assert trace_path.is_file()
        previous = log_dir.parent / "debug.log.prev_end"
        previous.write_text("2026-08-04T17:00:00+08:00\n")
        with trace_command(debug_path, argv):
            pass

    assert previous.read_text() == "2026-08-04T17:00:00+08:00\n"
    assert (log_dir / "debug.log.prev_end").is_file()
    assert len(trace_path.read_text().splitlines()) == 2


def test_failed_span_write_preserves_command_failure(tmp_path, monkeypatch):
    debug_path = tmp_path / "debug.log"
    monkeypatch.setenv("SPEX_TRACE_FILE", str(tmp_path))
    with (
        patch("debug_log.safe_flush_debug_log_path", return_value=debug_path),
        pytest.raises(SystemExit) as error,
    ):
        with trace_command(debug_path, ["spex", "version"]):
            raise SystemExit(2)
    assert error.value.code == 2
    assert "===== END exit=2 " in debug_path.read_text(encoding="utf-8")


class TestParseNameFromArgv:
    def test_positional_form(self):
        assert parse_name_from_argv(["prompt", "apply-one-task", "foo"]) == "foo"

    def test_rejects_legacy_prompt_option(self):
        assert parse_name_from_argv(["prompt", "apply-one-task", "--name=bar"]) is None

    def test_missing(self):
        assert parse_name_from_argv(["spex", "version"]) is None

    @pytest.mark.parametrize("command", ["version", "unknown"])
    def test_legacy_selector_cannot_route_an_unrelated_command(self, command):
        assert parse_name_from_argv(["spex", command, "--name", "topic"]) is None

    @pytest.mark.parametrize("command, subcommand", [
        ("apply_helper", "dirty"),
        ("create-helper", "post-action"),
    ])
    def test_lifecycle_name_option_still_routes(self, command, subcommand):
        argv = ["spex", "--debug", command, subcommand, "--name", "topic_name"]
        assert parse_name_from_argv(argv) == "topic_name"

    @pytest.mark.parametrize("argv, expected", [
        (["archive", "topic", "--json"], "topic"),
        (["archive", "--restore", "topic"], "topic"),
        (["archive", "--json"], None),
        (["archive", "--restore"], None),
        (["archive", "--restore", ""], None),
        (["archive", "--name=topic"], None),
        (["run-hook", "my-hook", "topic", "--event-type", "apply"], "topic"),
        (["run_hook", "my-hook", "--event-type", "apply", "topic"], "topic"),
        (["run-hook", "my-hook", "--event-type", "apply"], None),
        (["run-hook", "my-hook", "", "--event-type", "apply"], None),
        (["run-hook", "my-hook", "topic"], None),
        (["run-hook", "my-hook", "--name", "topic", "--event-type", "apply"], None),
        (["run-hook", "my-hook", "topic", "--event-type", "apply", "--json-payload", "{"], None),
    ])
    def test_archive_and_hook_selector(self, argv, expected, capsys):
        assert parse_name_from_argv(["spex", "--debug", *argv]) == expected
        assert not capsys.readouterr().err


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


class TestResolveDebugLogPath:
    def test_with_name_resolves_spec_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "apply-one-task", "my-spec"])
        assert path == Path(ctx.spex_root) / "specs" / "my-spec" / "logs" / "debug.log"

    def test_legacy_pointer_is_ignored(self, tmp_path, monkeypatch):
        ctx = _make_ctx(tmp_path)
        legacy = Path(ctx.spex_root) / "sessions"
        legacy.mkdir()
        (legacy / "active").write_text("legacy-session\n")
        (legacy / "legacy-session").mkdir()
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = resolve_debug_log_path(["spex", "version"])
        assert path == Path(ctx.spex_root) / "debug.log"
        assert (legacy / "active").read_text() == "legacy-session\n"


    def test_without_name_uses_spex_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = resolve_debug_log_path(["spex", "version"])
        assert path == Path(ctx.spex_root) / "debug.log"

    def test_unknown_name_falls_back_to_spex_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "apply-one-task", "missing"])
        assert path == Path(ctx.spex_root) / "debug.log"

    def test_ambiguous_name_falls_back_to_spex_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        specs_dir = Path(ctx.spex_root) / "specs"
        (specs_dir / "2026-01-01-foo").mkdir()
        (specs_dir / "2026-01-01-foo-bar").mkdir()
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "apply-one-task", "foo"])
        assert path == Path(ctx.spex_root) / "debug.log"

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
        with patch("debug_log.get_project_storage", return_value=ctx):
            assert resolve_debug_log_path(["spex", "version"]) is None

    def test_name_only_in_archives_resolves_archived_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        archived = spex_root / "archives" / "my-spec"
        archived.mkdir(parents=True)
        # Remove the specs copy created by _make_ctx so only archives matches.
        shutil.rmtree(spex_root / "specs" / "my-spec")
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = resolve_debug_log_path(["spex", "archive", "my-spec"])
        assert path == archived / "logs" / "debug.log"

    def test_specs_match_wins_over_archives(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        archived = spex_root / "archives" / "my-spec"
        archived.mkdir(parents=True)
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = resolve_debug_log_path(["spex", "prompt", "apply-one-task", "my-spec"])
        assert path == spex_root / "specs" / "my-spec" / "logs" / "debug.log"

    def test_archived_exact_wins_over_specs_fuzzy_sibling(
        self, tmp_path, monkeypatch
    ):
        """Exact archives match must beat a unique fuzzy specs sibling."""
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        specs_dir = spex_root / "specs"
        archives_dir = spex_root / "archives"
        shutil.rmtree(specs_dir / "my-spec")
        (specs_dir / "foo-v2").mkdir()
        (archives_dir / "foo").mkdir(parents=True)
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = resolve_debug_log_path(["spex", "archive", "foo"])
        assert path == archives_dir / "foo" / "logs" / "debug.log"


class TestSafeFlushDebugLogPath:
    def test_prefers_post_resolve(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        pre = tmp_path / "pre" / "debug.log"
        pre.parent.mkdir()
        resolved = Path(ctx.spex_root) / "specs" / "my-spec" / "logs" / "debug.log"
        with patch("debug_log.get_project_storage", return_value=ctx):
            path = safe_flush_debug_log_path(
                ["spex", "prompt", "apply-one-task", "my-spec"],
                pre,
            )
        assert path == resolved

    def test_falls_back_to_pre_when_parent_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pre = tmp_path / "still-here" / "debug.log"
        pre.parent.mkdir()
        with patch("debug_log.resolve_debug_log_path", return_value=None):
            with patch(
                "debug_log.get_project_storage",
                return_value=ProjectContext(
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
                ),
            ):
                path = safe_flush_debug_log_path(["spex", "version"], pre)
        assert path == pre

    def test_vanished_pre_falls_back_to_spex_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        pre = spex_root / "specs" / "gone" / "debug.log"
        # parent does not exist
        with patch("debug_log.resolve_debug_log_path", return_value=None):
            with patch("debug_log.get_project_storage", return_value=ctx):
                path = safe_flush_debug_log_path(
                    ["spex", "archive", "gone"],
                    pre,
                )
        assert path == spex_root / "debug.log"

    def test_vanished_pre_without_spex_root_skips(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pre = tmp_path / "specs" / "gone" / "debug.log"
        with patch("debug_log.resolve_debug_log_path", return_value=None):
            with patch(
                "debug_log.get_project_storage",
                return_value=ProjectContext(
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
                ),
            ):
                path = safe_flush_debug_log_path(["spex", "version"], pre)
        assert path is None


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
        span = json.loads(log_path.with_name("trace.jsonl").read_text(encoding="utf-8"))
        assert span["schema_version"] == 1
        assert span["name"] == "version"
        assert span["attributes"]["process.command_args"] == argv
        assert span["attributes"]["process.exit.code"] == 0
        assert span["end_time_unix_nano"] >= span["start_time_unix_nano"] > 0
        assert span["spex"]["duration_ms"] >= 0
        assert f'===== BEGIN {span["spex"]["debug_logged_at"]} =====' in content

    def test_records_nonzero_exit_on_system_exit(self, tmp_path):
        log_path = tmp_path / "debug.log"

        with pytest.raises(SystemExit) as exc_info:
            with trace_command(log_path, ["spex", "bad"]):
                raise SystemExit(2)

        assert exc_info.value.code == 2
        content = log_path.read_text(encoding="utf-8")
        assert "===== END exit=2 duration_ms=" in content
        span = json.loads(log_path.with_name("trace.jsonl").read_text(encoding="utf-8"))
        assert span["attributes"]["process.exit.code"] == 2
        assert span["status"]["code"] == "ERROR"

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
        spec_log = tmp_path / "specs" / "my-spec" / "logs" / "debug.log"
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
        argv = ["spex", "prompt", "apply-one-task", "my-spec", "--json"]
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
        argv = ["spex", "prompt", "apply-commit", "my-spec"]
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


class TestTraceCommandArchiveFollow:
    """Flush must follow archive moves and never recreate specs stubs."""

    def test_flush_follows_move_to_archives(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path, debug=True)
        spex_root = Path(ctx.spex_root)
        spec_dir = spex_root / "specs" / "my-spec"
        archives_dir = spex_root / "archives"
        archives_dir.mkdir(parents=True)
        pre_log = spec_dir / "logs" / "debug.log"
        pre_log.parent.mkdir()
        pre_log.write_text("===== pre-archive =====\n", encoding="utf-8")
        argv = ["spex", "archive", "my-spec"]

        with patch("debug_log.get_project_storage", return_value=ctx):
            with trace_command(pre_log, argv):
                shutil.move(str(spec_dir), str(archives_dir / "my-spec"))

        assert not spec_dir.exists()
        archived_log = archives_dir / "my-spec" / "logs" / "debug.log"
        content = archived_log.read_text(encoding="utf-8")
        assert "===== pre-archive =====\n" in content
        assert "argv: spex archive my-spec" in content
        span = json.loads(archived_log.with_name("trace.jsonl").read_text(encoding="utf-8"))
        assert span["name"] == "archive"
        assert "===== END exit=0 duration_ms=" in content
        # Must not recreate a specs stub for tee.
        assert not (spex_root / "specs" / "my-spec").exists()

    @pytest.mark.parametrize("outside_logs", [False, True])
    def test_runtime_logs_and_legacy_sidecars(self, tmp_path, monkeypatch, outside_logs):
        from debug_log import end_apply_span, has_open_apply_span

        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path, debug=True)
        spec_dir = Path(ctx.spex_root) / "specs" / "my-spec"
        (spec_dir / "debug.log").write_text("legacy\n")
        previous = spec_dir / "debug.log.prev_end"
        previous.write_text("2026-08-04T17:00:00+08:00\n")
        open_span = spec_dir / "debug.log.apply_span"
        open_span.write_text(json.dumps({"review": {"start_ns": 0, "fields": {}}}))
        logs = spec_dir / "logs"
        outside = tmp_path / "outside"
        if outside_logs:
            outside.mkdir()
            logs.symlink_to(outside, target_is_directory=True)

        argv = ["spex", "prompt", "show", "my-spec"]
        with (
            patch("debug_log.get_project_storage", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
            patch("debug_log.local_iso_timestamp", return_value="2026-08-04T17:00:03+08:00"),
        ):
            with trace_command(resolve_debug_log_path(argv), argv):
                pass
            if not outside_logs:
                assert has_open_apply_span(spec_dir, "review")
                end_apply_span(spec_dir, "review")
                assert not has_open_apply_span(spec_dir, "review")

        assert (spec_dir / "debug.log").read_text() == "legacy\n"
        if outside_logs:
            assert not list(outside.iterdir())
            assert previous.is_file() and open_span.is_file()
        else:
            assert not previous.exists() and not open_span.exists()
            assert "gap_ms=3000" in (logs / "debug.log").read_text()
            assert (logs / "debug.log.prev_end").is_file()
            assert (logs / "trace.jsonl").is_file()

    def test_vanished_specs_without_archives_uses_spex_root(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path, debug=True)
        spex_root = Path(ctx.spex_root)
        spec_dir = spex_root / "specs" / "my-spec"
        pre_log = spec_dir / "logs" / "debug.log"
        pre_log.parent.mkdir()
        pre_log.write_text("keep\n", encoding="utf-8")
        argv = ["spex", "archive", "my-spec"]

        with patch("debug_log.get_project_storage", return_value=ctx):
            with trace_command(pre_log, argv):
                # Spec vanished with no archives counterpart.
                shutil.rmtree(spec_dir)

        assert not spec_dir.exists()
        root_log = spex_root / "debug.log"
        assert root_log.is_file()
        content = root_log.read_text(encoding="utf-8")
        assert "argv: spex archive my-spec" in content
        assert not (spex_root / "specs" / "my-spec").exists()

    def test_refuses_mkdir_for_vanished_specs_parent(self, tmp_path, monkeypatch):
        """Direct append must not recreate specs/<name>/ when parent is gone."""
        from debug_log import _append_trace

        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        vanished = spex_root / "specs" / "ghost" / "debug.log"
        # Ensure specs/ exists but ghost/ does not.
        assert (spex_root / "specs").is_dir()
        assert not vanished.parent.exists()

        with patch("debug_log.get_project_storage", return_value=ctx):
            _append_trace(
                vanished,
                ["spex", "version"],
                ["out"],
                {"buffered_bytes": 3, "total_bytes": 3, "truncated": False},
                [],
                {"buffered_bytes": 0, "total_bytes": 0, "truncated": False},
                0,
                1,
            )

        assert not vanished.parent.exists()
        assert not vanished.exists()

    def test_refuses_mkdir_when_entire_specs_tree_missing(
        self, tmp_path, monkeypatch
    ):
        """Even if specs/ itself is gone, do not recreate specs/<name>/."""
        from debug_log import _append_trace

        monkeypatch.chdir(tmp_path)
        ctx = _make_ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        shutil.rmtree(spex_root / "specs")
        vanished = spex_root / "specs" / "ghost" / "debug.log"
        assert not (spex_root / "specs").exists()

        with patch("debug_log.get_project_storage", return_value=ctx):
            _append_trace(
                vanished,
                ["spex", "version"],
                ["out"],
                {"buffered_bytes": 3, "total_bytes": 3, "truncated": False},
                [],
                {"buffered_bytes": 0, "total_bytes": 0, "truncated": False},
                0,
                1,
            )

        assert not (spex_root / "specs").exists()
        assert not vanished.exists()


class TestApplyFlowTelemetryHelpers:
    """Structured APPLY span helpers used by review/fix instrumentation."""

    def test_format_apply_event_omits_empty(self):
        from debug_log import format_apply_event

        line = format_apply_event(
            "review begin",
            step="step-7",
            mode="full",
            findings=0,
            empty="",
            none=None,
        )
        assert line.startswith("===== APPLY review begin ")
        assert "step=step-7" in line
        assert "mode=full" in line
        assert "findings=0" in line
        assert "empty=" not in line
        assert "none=" not in line
        assert line.endswith(" =====")

    def test_start_end_span_records_duration(self, tmp_path, monkeypatch):
        import time

        from debug_log import (
            DEBUG_LOG_NAME,
            end_apply_span,
            has_open_apply_span,
            start_apply_span,
        )

        monkeypatch.setattr("sys.argv", ["spex", "-d"])
        with patch("debug_log.debug_enabled", return_value=True):
            start_apply_span(
                tmp_path,
                "review",
                step="step-7",
                mode="delta",
                commit="abc",
                prompt_bytes=100,
            )
            assert has_open_apply_span(tmp_path, "review")
            time.sleep(0.02)
            closed = end_apply_span(
                tmp_path,
                "review",
                findings=2,
                has_major=True,
            )

        assert closed is not None
        assert closed["duration_ms"] >= 10
        assert not has_open_apply_span(tmp_path, "review")
        content = (tmp_path / "logs" / DEBUG_LOG_NAME).read_text(encoding="utf-8")
        assert "===== APPLY review begin" in content
        assert "===== APPLY review end" in content
        assert f"duration_ms={closed['duration_ms']}" in content
        assert "mode=delta" in content
        assert "findings=2" in content

    def test_sum_check_evidence_duration_ms(self):
        from debug_log import sum_check_evidence_duration_ms

        assert sum_check_evidence_duration_ms(None) == 0
        assert sum_check_evidence_duration_ms({"checks": []}) == 0
        assert sum_check_evidence_duration_ms({
            "checks": [
                {"command": "a", "exit_code": 0, "duration_ms": 100},
                {"command": "b", "exit_code": 0, "duration_ms": 50},
                {"command": "c", "exit_code": 0},
            ],
        }) == 150

    def test_trace_gap_ms_still_works_with_apply_anchors(
        self, tmp_path, monkeypatch,
    ):
        """APPLY anchors must not break CLI tee gap_ms / duration_ms."""
        from debug_log import append_debug_anchor, format_apply_event

        # Match TestTraceCommand: keep flush on the explicit log path.
        monkeypatch.setattr(
            "debug_log.resolve_debug_log_path",
            lambda _argv: None,
        )
        log_path = tmp_path / "debug.log"

        with trace_command(log_path, ["spex", "version"]):
            print("first")
        append_debug_anchor(
            log_path,
            format_apply_event(
                "review begin", step="step-7", mode="full",
            ),
        )
        with trace_command(log_path, ["spex", "version"]):
            print("second")

        content = log_path.read_text(encoding="utf-8")
        assert content.count("===== BEGIN ") == 2
        assert "duration_ms=" in content
        assert "gap_ms=" in content
        assert "===== APPLY review begin" in content
