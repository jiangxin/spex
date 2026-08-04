"""Tests for APPLY debug.log script anchors (no agent mark-phase)."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import apply_helper
import prompt
import pytest
import review_helper
import todo_helper
from debug_log import DEBUG_LOG_NAME, append_debug_anchor, emit_apply_anchor


def _read_log(spec_dir: Path) -> str:
    return (spec_dir / DEBUG_LOG_NAME).read_text(encoding="utf-8")


class TestAppendDebugAnchor:
    def test_appends_newline(self, tmp_path):
        log_path = tmp_path / "debug.log"
        append_debug_anchor(log_path, "===== APPLY task begin id=step-1 =====")
        assert log_path.read_text(encoding="utf-8") == (
            "===== APPLY task begin id=step-1 =====\n"
        )

    def test_swallows_oserror(self, tmp_path, monkeypatch):
        log_path = tmp_path / "missing" / "debug.log"

        def fail_open(*_args, **_kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "open", fail_open)
        append_debug_anchor(log_path, "===== APPLY task begin id=step-1 =====")
        assert not log_path.exists()

    def test_emit_apply_anchor_respects_debug_flag(self, tmp_path):
        with patch("debug_log.debug_enabled", return_value=False):
            emit_apply_anchor(tmp_path, "===== APPLY post-action ok =====")
        assert not (tmp_path / DEBUG_LOG_NAME).exists()

        with patch("debug_log.debug_enabled", return_value=True):
            emit_apply_anchor(tmp_path, "===== APPLY post-action ok =====")
        assert _read_log(tmp_path) == "===== APPLY post-action ok =====\n"


class TestPromptApplyAnchors:
    def test_apply_one_task_emits_begin_when_not_all_done(
        self, tmp_path, monkeypatch, capsys,
    ):
        spec_dir = tmp_path / "my-spec"
        spec_dir.mkdir()
        monkeypatch.setattr(
            "sys.argv",
            ["spex", "-d", "prompt", "apply-one-task", "--name", "my-spec"],
        )
        metadata = {
            "current_task_id": "step-4",
            "current_task_description": "Add apply script anchors",
            "resume_phase": "implement",
            "current_commit_title": "",
        }
        args = Namespace(
            name="my-spec", json_mode=True, output=None,
        )
        with (
            patch("prompt._build_metadata", return_value=metadata),
            patch("prompt.render_prompt", return_value="PROMPT"),
            patch("prompt.resolve_spec_dir", return_value=spec_dir),
            patch("debug_log.debug_enabled", return_value=True),
        ):
            prompt._do_apply_one_task(args)

        assert "===== APPLY task begin id=step-4 =====\n" in _read_log(
            spec_dir,
        )
        out = json.loads(capsys.readouterr().out)
        assert out["task_id"] == "step-4"

    def test_apply_one_task_all_done_skips_anchor(
        self, tmp_path, monkeypatch,
    ):
        spec_dir = tmp_path / "my-spec"
        spec_dir.mkdir()
        monkeypatch.setattr(
            "sys.argv",
            ["spex", "-d", "prompt", "apply-one-task", "--name", "my-spec"],
        )
        metadata = {
            "current_task_id": "",
            "current_task_description": "",
            "resume_phase": "implement",
            "current_commit_title": "",
        }
        args = Namespace(name="my-spec", json_mode=True, output=None)
        with (
            patch("prompt._build_metadata", return_value=metadata),
            patch("debug_log.debug_enabled", return_value=True),
            pytest.raises(SystemExit) as exc,
        ):
            prompt._do_apply_one_task(args)
        assert exc.value.code == 0
        assert not (spec_dir / DEBUG_LOG_NAME).exists()

    def test_apply_review_emits_begin_anchor(
        self, tmp_path, monkeypatch, capsys,
    ):
        spec_dir = tmp_path / "my-spec"
        spec_dir.mkdir()
        monkeypatch.setattr(
            "sys.argv",
            ["spex", "-d", "prompt", "apply-review", "--name", "my-spec"],
        )
        metadata = {
            "current_task_description": "task",
            "step_id": "step-4",
            "commit_sha": "abc1234",
            "review_round": 2,
            "review_file": str(spec_dir / "review-step-4.json"),
        }
        args = Namespace(
            name="my-spec",
            json_mode=True,
            output=None,
            commit_sha="abc1234",
        )
        with (
            patch("prompt._build_metadata", return_value=metadata),
            patch("prompt._enrich_review_metadata", return_value=metadata),
            patch("prompt.render_prompt", return_value="REVIEW"),
            patch("prompt.resolve_spec_dir", return_value=spec_dir),
            patch("debug_log.debug_enabled", return_value=True),
        ):
            prompt._do_apply_review(args)

        assert (
            "===== APPLY review begin round=2 commit=abc1234 =====\n"
            in _read_log(spec_dir)
        )
        assert json.loads(capsys.readouterr().out)["review_round"] == 2


class TestTodoEditAnchors:
    def test_commit_title_emits_committed_anchor(self, tmp_path, monkeypatch):
        todo = tmp_path / "todo.json"
        todo.write_text(
            json.dumps([{
                "id": "step-4",
                "name": "Anchors",
                "details": "details",
                "completed_at": "",
                "commit_title": "",
            }]) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["spex", "-d", "todo-helper", "edit", "--id", "step-4"],
        )
        args = Namespace(
            id="step-4",
            step_name=None,
            details=None,
            details_from_stdin=False,
            completed_at=None,
            commit_title="abc1234: feat: add apply anchors",
            name="my-spec",
        )
        with patch("debug_log.debug_enabled", return_value=True):
            todo_helper.cmd_edit(todo, False, args)

        assert (
            "===== APPLY task committed id=step-4 sha=abc1234 =====\n"
            in _read_log(tmp_path)
        )

    def test_completed_at_emits_done_anchor(self, tmp_path, monkeypatch):
        todo = tmp_path / "todo.json"
        todo.write_text(
            json.dumps([{
                "id": "step-4",
                "name": "Anchors",
                "details": "details",
                "completed_at": "",
                "commit_title": "abc1234: feat: add apply anchors",
            }]) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("sys.argv", ["spex", "-d", "todo-helper"])
        args = Namespace(
            id="step-4",
            step_name=None,
            details=None,
            details_from_stdin=False,
            completed_at="now",
            commit_title="abc1234: feat: add apply anchors",
            name="my-spec",
        )
        with patch("debug_log.debug_enabled", return_value=True):
            todo_helper.cmd_edit(todo, False, args)

        content = _read_log(tmp_path)
        assert "===== APPLY task done id=step-4 =====\n" in content
        assert "task committed" not in content

    def test_no_anchor_when_debug_off(self, tmp_path, monkeypatch):
        todo = tmp_path / "todo.json"
        todo.write_text(
            json.dumps([{
                "id": "step-4",
                "name": "Anchors",
                "details": "details",
                "completed_at": "",
                "commit_title": "",
            }]) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("sys.argv", ["spex", "todo-helper"])
        args = Namespace(
            id="step-4",
            step_name=None,
            details=None,
            details_from_stdin=False,
            completed_at=None,
            commit_title="title",
            name=None,
        )
        with patch("debug_log.debug_enabled", return_value=False):
            todo_helper.cmd_edit(todo, False, args)
        assert not (tmp_path / DEBUG_LOG_NAME).exists()


class TestReviewAndPostActionAnchors:
    def test_bump_round_emits_anchor(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            review_helper, "resolve_spec_dir",
            lambda name, **kw: tmp_path,
        )
        monkeypatch.setattr("sys.argv", ["spex", "-d", "review-helper"])
        review_helper.main([
            "--name", "my-spec", "init",
            "--step", "step-1", "--commit", "aaa1111",
        ])
        with patch("debug_log.debug_enabled", return_value=True):
            review_helper.main([
                "--name", "my-spec", "bump-round",
                "--step", "step-1", "--commit", "bbb2222",
            ])
        assert "===== APPLY review round → 2 =====\n" in _read_log(tmp_path)
        capsys.readouterr()

    def test_post_action_emits_anchor(self, tmp_path, monkeypatch):
        from common import SpecMeta

        monkeypatch.setattr("sys.argv", ["spex", "-d", "apply-helper"])
        args = Namespace(name="my-spec")

        class _Ctx:
            top_workdir = tmp_path

        with (
            patch(
                "common.resolve_spec_dir",
                return_value=tmp_path,
            ),
            patch(
                "common.load_meta",
                return_value=SpecMeta(
                    spex_branch="spex/apply-debug-log-fixes",
                    branch="main",
                ),
            ),
            patch("config.get_project_context", return_value=_Ctx()),
            patch("hooks.run_post_action"),
            patch("hooks.find_hook", return_value=None),
            patch("debug_log.debug_enabled", return_value=True),
        ):
            apply_helper._do_post_action(args)

        assert "===== APPLY post-action ok =====\n" in _read_log(tmp_path)


class TestApplyAnchorSequence:
    def test_apply_like_sequence_produces_readable_anchors(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Simulate apply-one-task → commit-title → completed_at → bump."""
        spec_dir = tmp_path / "my-spec"
        spec_dir.mkdir()
        todo = spec_dir / "todo.json"
        todo.write_text(
            json.dumps([{
                "id": "step-4",
                "name": "Anchors",
                "details": "details",
                "completed_at": "",
                "commit_title": "",
            }]) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("sys.argv", ["spex", "-d"])

        metadata = {
            "current_task_id": "step-4",
            "current_task_description": "Add apply script anchors",
            "resume_phase": "implement",
            "current_commit_title": "",
        }
        with (
            patch("prompt._build_metadata", return_value=metadata),
            patch("prompt.render_prompt", return_value="PROMPT"),
            patch("prompt.resolve_spec_dir", return_value=spec_dir),
            patch("debug_log.debug_enabled", return_value=True),
        ):
            prompt._do_apply_one_task(
                Namespace(name="my-spec", json_mode=True, output=None),
            )

        with patch("debug_log.debug_enabled", return_value=True):
            todo_helper.cmd_edit(
                todo,
                False,
                Namespace(
                    id="step-4",
                    step_name=None,
                    details=None,
                    details_from_stdin=False,
                    completed_at=None,
                    commit_title="deadbee: feat: anchors",
                    name="my-spec",
                ),
            )
            todo_helper.cmd_edit(
                todo,
                False,
                Namespace(
                    id="step-4",
                    step_name=None,
                    details=None,
                    details_from_stdin=False,
                    completed_at="now",
                    commit_title="deadbee: feat: anchors",
                    name="my-spec",
                ),
            )

        monkeypatch.setattr(
            review_helper, "resolve_spec_dir",
            lambda name, **kw: spec_dir,
        )
        review_helper.main([
            "--name", "my-spec", "init",
            "--step", "step-4", "--commit", "deadbee",
        ])
        with patch("debug_log.debug_enabled", return_value=True):
            review_helper.main([
                "--name", "my-spec", "bump-round",
                "--step", "step-4", "--commit", "cafebabe",
            ])

        content = _read_log(spec_dir)
        begin = content.index("===== APPLY task begin id=step-4 =====\n")
        committed = content.index(
            "===== APPLY task committed id=step-4 sha=deadbee =====\n",
        )
        done = content.index("===== APPLY task done id=step-4 =====\n")
        bumped = content.index("===== APPLY review round → 2 =====\n")
        assert begin < committed < done < bumped
        capsys.readouterr()
