"""Tests for create_helper.py — spec creation and branch validation."""

import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import config as cfg
import create_helper
import pytest
from config import ProjectContext, clear_config_cache
from create_helper import (
    cli_create_validate,
    cli_prepare_spec,
    create_spec,
    validate_create_branch,
)
from debug_log import (
    get_active_session_id,
    resolve_debug_log_path,
    session_debug_log_path,
    trace_command,
)


def _fake_project_context(**overrides):
    """Build a ProjectContext with sensible defaults, overriding as needed."""
    defaults = {
        "cwd": Path("."),
        "top_workdir": None,
        "main_worktree": None,
        "remote_url": "",
        "branch": "",
        "user_name": "",
        "user_email": "",
        "spex_tomls": [],
        "config": {},
        "spex_root": "",
        "spex_roots": [],
    }
    defaults.update(overrides)
    return ProjectContext(**defaults)


def _mock_ctx(
    top_workdir=None,
    main_worktree=None,
    remote_url="",
    branch="",
    user_name="",
    user_email="",
):
    """Build a ProjectContext for _write_meta tests."""
    return ProjectContext(
        cwd=top_workdir or Path("."),
        top_workdir=top_workdir,
        main_worktree=main_worktree,
        remote_url=remote_url,
        branch=branch,
        user_name=user_name,
        user_email=user_email,
    )


class TestCreateTopic:
    def test_creates_directory(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        spec_name, spec_dir = create_spec(
            "2026-05-20-14-30-hello", specs_dir
        )

        assert spec_name == "2026-05-20-14-30-hello"
        assert spec_dir == specs_dir / "2026-05-20-14-30-hello"
        assert spec_dir.is_dir()

    def test_creates_specs_dir_if_missing(self, tmp_path):
        specs_dir = tmp_path / "specs"

        spec_name, spec_dir = create_spec(
            "2026-05-20-14-30-new-topic", specs_dir
        )

        assert specs_dir.is_dir()
        assert spec_dir.is_dir()

    def test_invalid_name_no_date(self, tmp_path):
        with pytest.raises(ValueError, match="invalid spec name"):
            create_spec("no-date-prefix", tmp_path, auto_prefix=False)

    def test_invalid_name_uppercase(self, tmp_path):
        with pytest.raises(ValueError, match="invalid spec name"):
            create_spec("2026-05-20-14-30-UpperCase", tmp_path)

    def test_invalid_name_spaces(self, tmp_path):
        with pytest.raises(ValueError, match="invalid spec name"):
            create_spec("2026-05-20-14-30-has space", tmp_path)

    def test_exceeds_max_bytes(self, tmp_path):
        long_name = "2026-05-20-14-30-" + "a" * 54
        with pytest.raises(ValueError, match="exceeds 64 bytes"):
            create_spec(long_name, tmp_path)

    def test_already_exists(self, tmp_path):
        specs_dir = tmp_path / "specs"
        (specs_dir / "2026-05-20-14-30-existing").mkdir(parents=True)

        with pytest.raises(FileExistsError, match="already exists"):
            create_spec("2026-05-20-14-30-existing", specs_dir)

    def test_valid_name_with_numbers(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        spec_name, spec_dir = create_spec(
            "2026-01-01-09-15-add-v2-api", specs_dir
        )

        assert spec_dir.is_dir()

    def test_auto_prefix_adds_date(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        with patch.object(
            create_helper, "datetime"
        ) as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-05-24-20-00"
            spec_name, spec_dir = create_spec("my-topic", specs_dir)

        assert spec_name == "2026-05-24-20-00-my-topic"
        assert spec_dir == specs_dir / "2026-05-24-20-00-my-topic"
        assert spec_dir.is_dir()

    def test_explicit_prefix_kept(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        spec_name, spec_dir = create_spec(
            "2026-05-20-14-30-hello", specs_dir
        )

        assert spec_name == "2026-05-20-14-30-hello"
        assert spec_dir.is_dir()

    def test_auto_prefix_false_no_prefix_fails(self, tmp_path):
        with pytest.raises(ValueError, match="invalid spec name"):
            create_spec("my-topic", tmp_path, auto_prefix=False)


class TestWriteMeta:
    def test_meta_with_prompt(self, tmp_path):
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
            remote_url="git@github.com:user/project.git",
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "fix the login bug",
            "2026-05-24T20:00:00+08:00"
        )

        meta_path = spec_dir / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["workdir"] == "/home/user/project"
        assert meta["main_worktree"] == "/home/user/project"
        assert meta["remote_url"] == "git@github.com:user/project.git"
        assert meta["branch"] == "main"
        assert meta["user_name"] == "Alice"
        assert meta["user_email"] == "alice@example.com"
        assert meta["created_at"] == "2026-05-24T20:00:00+08:00"
        assert meta["prompts"] == [
            {"text": "fix the login bug",
             "timestamp": "2026-05-24T20:00:00+08:00"},
        ]

    def test_meta_with_empty_prompt(self, tmp_path):
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "", "2026-05-24T20:00:00+08:00"
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        assert meta["prompts"] == []
        assert meta["remote_url"] == ""

    def test_worktree_main_worktree_points_to_main(self, tmp_path):
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project-wt"),
            main_worktree=Path("/home/user/project"),
            remote_url="git@github.com:user/project.git",
            branch="feature",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "add feature",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        assert meta["workdir"] == "/home/user/project-wt"
        assert meta["main_worktree"] == "/home/user/project"

    def test_ctx_none_workdir_is_empty(self, tmp_path):
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=None,
            main_worktree=None,
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        assert meta["workdir"] == ""
        assert meta["main_worktree"] == ""

    def test_json_field_order_without_description(self, tmp_path):
        """Verify JSON field order from SpecMeta matches legacy format."""
        spec_dir = tmp_path / "2026-01-01-10-00-order-test"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/work"),
            main_worktree=Path("/work"),
            remote_url="git@example.com:r.git",
            branch="main",
            user_name="Alice",
            user_email="a@e.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "hello",
            "2026-01-01T10:00:00+08:00",
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        keys = list(meta.keys())
        expected_keys = [
            "name", "workdir", "main_worktree", "remote_url",
            "branch", "user_name", "user_email", "created_at",
            "prompts",
        ]
        assert keys == expected_keys
        assert "description" not in meta
        assert "spex_branch" not in meta

    def test_json_field_order_with_description(self, tmp_path):
        """Verify description appears in correct position."""
        spec_dir = tmp_path / "2026-01-01-10-00-desc-order"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/work"),
            main_worktree=Path("/work"),
            branch="main",
            user_name="Alice",
            user_email="a@e.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "",
            "2026-01-01T10:00:00+08:00",
            description="My feature desc",
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        keys = list(meta.keys())
        assert "description" in keys
        assert keys.index("description") == keys.index("prompts") + 1


class TestCliPrepareSpec:
    def test_missing_topic_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with pytest.raises(SystemExit) as exc_info:
            cli_prepare_spec([])
        assert exc_info.value.code == 2

    def test_invalid_topic_exits(self, monkeypatch, tmp_path):
        import common
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            common, "get_specs_dir", return_value=str(tmp_path)
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_prepare_spec(["--name", "INVALID"])
            assert exc_info.value.code == 1

    def test_existing_topic_exits(self, monkeypatch, tmp_path):
        import common
        (tmp_path / "2026-05-20-14-30-existing").mkdir()
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            common, "get_specs_dir", return_value=str(tmp_path)
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_prepare_spec(
                    ["--name", "2026-05-20-14-30-existing"])
            assert exc_info.value.code == 1

    def test_success_outputs_json(self, monkeypatch, tmp_path, capsys):
        import common
        monkeypatch.setattr(sys, "stdin", io.StringIO("hello prompt"))

        mock_ctx = _mock_ctx(
            top_workdir=Path("/tmp/proj"),
            main_worktree=Path("/tmp/proj"),
            branch="main",
            user_name="Test",
            user_email="test@test.com",
        )

        import prompt as prompt_mod

        with (
            patch.object(
                common, "get_specs_dir",
                return_value=str(tmp_path)),
            patch.object(
                common, "local_iso_timestamp",
                return_value="2026-05-24T20:00:00+08:00"),
            patch.object(
                cfg, "get_project_context",
                return_value=mock_ctx),
            patch.object(
                prompt_mod, "render_prompt",
                return_value="# Rendered Template"),
            patch("hooks.run_pre_action"),
        ):
            cli_prepare_spec(
                ["--name", "2026-05-20-14-30-new-topic",
                 "--description", "Test desc"])

        output = json.loads(capsys.readouterr().out.strip())
        assert output["spec_name"] == "2026-05-20-14-30-new-topic"
        assert output["spec_path"] == str(
            tmp_path / "2026-05-20-14-30-new-topic"
        )
        assert output["spec_template"] == "# Rendered Template"

        meta_path = tmp_path / "2026-05-20-14-30-new-topic" / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["prompts"] == [
            {"text": "hello prompt",
             "timestamp": "2026-05-24T20:00:00+08:00"},
        ]
        assert meta["description"] == "Test desc"


class TestValidateCreateBranch:
    @patch("branch.get_current_branch", return_value="main")
    def test_returns_current_branch(self, _mock):
        result = validate_create_branch(
            {"branch_management": True, "main_branch_name": "",
             "submit_method": "merge"})
        assert result == "main"

    @patch("branch.get_current_branch", return_value="main")
    def test_disabled_returns_current_branch(self, _mock):
        result = validate_create_branch(
            {"branch_management": False, "main_branch_name": "",
             "submit_method": "merge"})
        assert result == "main"

    @patch("branch.get_current_branch",
           side_effect=subprocess.CalledProcessError(1, "git"))
    def test_git_error_exits(self, _mock):
        try:
            validate_create_branch({"branch_management": True})
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("branch.switch_branch")
    @patch("branch.get_current_branch", return_value="develop")
    def test_wrong_main_branch_auto_switches(self, _curr, _switch):
        result = validate_create_branch({"branch_management": True,
                                         "main_branch_name": "main"})
        assert result == "main"
        _switch.assert_called_once_with("main", None)

    @patch("branch.switch_branch")
    @patch("branch.get_current_branch", return_value="develop")
    def test_auto_switch_success_output(self, _curr, _switch, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            result = validate_create_branch({"branch_management": True,
                                             "main_branch_name": "main"})
        assert result == "main"
        assert "Warning" in caplog.text
        assert "Switching" in caplog.text
        assert "Switched to branch" in caplog.text

    @patch("branch.switch_branch",
           side_effect=subprocess.CalledProcessError(
               1, "git", stderr="error: pathspec"))
    @patch("branch.get_current_branch", return_value="develop")
    def test_auto_switch_failure_exits(self, _curr, _switch, caplog):
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                validate_create_branch({"branch_management": True,
                                        "main_branch_name": "main"})
                assert False, "Should have called sys.exit(-1)"
            except SystemExit as e:
                assert e.code == -1
        assert "failed to switch" in caplog.text

    @patch("branch.get_current_branch", return_value="spex/feature")
    def test_spex_prefix_exits(self, _mock):
        try:
            validate_create_branch(
                {"branch_management": True, "main_branch_name": "",
                 "submit_method": "merge"})
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("branch.get_current_branch", return_value="spex/feature")
    def test_spex_prefix_error_includes_hint(self, _mock, caplog):
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                validate_create_branch(
                    {"branch_management": True, "main_branch_name": "",
                     "submit_method": "merge"})
            except SystemExit:
                pass
        assert "main_branch_name" in caplog.text
        assert "Hint" in caplog.text


class TestCliPostAction:
    def _setup_topic(self, tmp_path, name, todo_data):
        spec_dir = tmp_path / name
        spec_dir.mkdir()
        (spec_dir / "todo.json").write_text(
            json.dumps(todo_data, indent=2), encoding="utf-8",
        )
        meta = {"name": name, "workdir": str(tmp_path)}
        (spec_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )
        return spec_dir

    def test_validates_json(self, tmp_path, monkeypatch):
        """post-action validates todo.json successfully."""
        todo = [{"id": "step-1", "name": "First",
                 "details": "D", "completed_at": "",
                 "commit_title": ""}]
        spec_dir = self._setup_topic(
            tmp_path, "my-topic", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--name", "my-topic"],
            )

        assert (spec_dir / "todo.json").is_file()

    def test_missing_json_fails(self, tmp_path, monkeypatch):
        """post-action errors when todo.json does not exist."""
        spec_dir = tmp_path / "no-json"
        spec_dir.mkdir()
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--name", "no-json"],
            )

    def test_missing_required_field_fails(
        self, tmp_path, monkeypatch,
    ):
        """post-action fails when a required field is missing."""
        todo = [{"id": "step-1", "name": "First"}]
        spec_dir = self._setup_topic(
            tmp_path, "bad-field", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--name", "bad-field"],
            )

    def test_duplicate_id_fails(self, tmp_path, monkeypatch):
        """post-action fails when step IDs are duplicated."""
        todo = [
            {"id": "step-1", "name": "A", "details": "D",
             "completed_at": "", "commit_title": ""},
            {"id": "step-1", "name": "B", "details": "D",
             "completed_at": "", "commit_title": ""},
        ]
        spec_dir = self._setup_topic(
            tmp_path, "dup-id", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--name", "dup-id"],
            )

    def test_default_event_type_is_create(
        self, tmp_path, monkeypatch,
    ):
        """post-action defaults event-type to 'create'."""
        todo = [{"id": "s1", "name": "N", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        spec_dir = self._setup_topic(
            tmp_path, "evt-topic", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action") as mock_hook:
            create_helper.cli_post_action(
                ["--name", "evt-topic"],
            )
            mock_hook.assert_called_once()
            assert mock_hook.call_args[0][0] == "create"


class TestCliCreateValidate:
    @patch("branch.get_current_branch", return_value="develop")
    @patch("config.get_project_context", return_value=_fake_project_context(
        config={
            "branch_management": True, "main_branch_name": "",
            "submit_method": "merge", "spex_root": ".spex"}))
    def test_outputs_success(self, _ctx, _branch, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            cli_create_validate()
        assert "develop" in caplog.text
        assert "Valid" in caplog.text



class TestDescriptionWrapping:
    def test_write_meta_wraps_long_description(self, tmp_path):
        """_write_meta wraps descriptions longer than 68 chars."""
        spec_dir = tmp_path / "2026-01-01-10-00-wrap-test"
        spec_dir.mkdir()

        long_desc = (
            "This is a very long description that should definitely "
            "exceed the sixty-eight character limit and be wrapped "
            "into multiple lines by the wrap_text function"
        )
        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "",
            "2026-01-01T10:00:00+08:00", long_desc,
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        desc = meta["description"]
        assert "\n" in desc
        for line in desc.splitlines():
            assert len(line) <= 68

    def test_post_action_updates_description_from_spec(
        self, tmp_path, monkeypatch,
    ):
        """post-action updates meta.json description from spec.md."""
        spec_dir = tmp_path / "desc-topic"
        spec_dir.mkdir()

        # Write spec.md with front-matter description
        spec_content = (
            "---\n"
            "description: >\n"
            "  This is a long description from the spec front-matter"
            " that should be wrapped properly when saved to meta\n"
            "---\n"
            "\n# Spec content\n"
        )
        (spec_dir / "spec.md").write_text(
            spec_content, encoding="utf-8",
        )

        # Write valid todo.json
        todo = [{"id": "s1", "name": "Step 1", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )

        # Write initial meta.json
        meta = {"name": "desc-topic", "workdir": str(tmp_path)}
        (spec_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )

        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--name", "desc-topic"],
            )

        updated_meta = json.loads(
            (spec_dir / "meta.json").read_text(),
        )
        assert "description" in updated_meta
        assert updated_meta["description"] != ""

    def test_post_action_no_description_leaves_meta_unchanged(
        self, tmp_path, monkeypatch,
    ):
        """post-action leaves meta.json unchanged if no description."""
        spec_dir = tmp_path / "no-desc-topic"
        spec_dir.mkdir()

        # Write spec.md without description in front-matter
        spec_content = (
            "---\n"
            "title: My Spec\n"
            "---\n"
            "\n# Spec content\n"
        )
        (spec_dir / "spec.md").write_text(
            spec_content, encoding="utf-8",
        )

        # Write valid todo.json
        todo = [{"id": "s1", "name": "Step 1", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )

        # Write initial meta.json with existing description
        meta = {
            "name": "no-desc-topic",
            "workdir": str(tmp_path),
            "description": "original description",
        }
        (spec_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )

        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--name", "no-desc-topic"],
            )

        updated_meta = json.loads(
            (spec_dir / "meta.json").read_text(),
        )
        assert updated_meta["description"] == "original description"


class TestBeginEndSession:
    """Tests for create-helper begin-session / end-session."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_config_cache()
        yield
        clear_config_cache()

    def _ctx(self, tmp_path, *, debug=False):
        spex_root = tmp_path / ".spex"
        (spex_root / "specs").mkdir(parents=True)
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

    def test_begin_session_creates_pointer_and_json(
        self, tmp_path, monkeypatch, capsys,
    ):
        ctx = self._ctx(tmp_path)
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
        ):
            create_helper.main(["begin-session"])

        out = json.loads(capsys.readouterr().out.strip())
        assert out["active"] is True
        assert out["session_id"]
        assert out["log_path"] == str(
            session_debug_log_path(ctx.spex_root, out["session_id"])
        )
        assert get_active_session_id(ctx.spex_root) == out["session_id"]
        session_dir = Path(out["log_path"]).parent
        assert session_dir.is_dir()
        assert not Path(out["log_path"]).exists()

    def test_begin_session_reuses_active_session(
        self, tmp_path, monkeypatch, capsys,
    ):
        ctx = self._ctx(tmp_path, debug=True)
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
            patch(
                "common.local_iso_timestamp",
                return_value="2026-08-04T15:50:00+08:00",
            ),
        ):
            create_helper.main(["begin-session"])
            first = json.loads(capsys.readouterr().out.strip())
            create_helper.main(["begin-session"])
            second = json.loads(capsys.readouterr().out.strip())

        assert first == second
        log_path = Path(first["log_path"])
        content = log_path.read_text(encoding="utf-8")
        assert content.count("===== CREATE session begin") == 1
        assert f"id={first['session_id']}" in content

    def test_begin_session_writes_anchor_when_debug_enabled(
        self, tmp_path, monkeypatch, capsys,
    ):
        ctx = self._ctx(tmp_path, debug=True)
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
            patch(
                "common.local_iso_timestamp",
                return_value="2026-08-04T15:50:00+08:00",
            ),
        ):
            create_helper.main(["begin-session"])

        out = json.loads(capsys.readouterr().out.strip())
        content = Path(out["log_path"]).read_text(encoding="utf-8")
        assert (
            f"===== CREATE session begin id={out['session_id']} "
            "ts=2026-08-04T15:50:00+08:00 =====\n"
        ) == content

    def test_end_session_without_name_keeps_session_files(
        self, tmp_path, monkeypatch, capsys,
    ):
        ctx = self._ctx(tmp_path)
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            log_path = Path(begin["log_path"])
            log_path.write_text("session history\n", encoding="utf-8")
            create_helper.main(["end-session"])
            end = json.loads(capsys.readouterr().out.strip())

        assert end == {
            "ended": True,
            "merged_into": None,
            "deleted": False,
        }
        assert get_active_session_id(ctx.spex_root) is None
        assert log_path.is_file()
        assert log_path.read_text(encoding="utf-8") == "session history\n"

    def test_end_session_with_name_cleans_empty_session_dir(
        self, tmp_path, monkeypatch, capsys,
    ):
        """begin without debug leaves an empty session dir; end --name removes it.

        Locks the no-log-file edge path: session dir exists, debug.log was
        never created, merge has nothing to append, but empty dir is cleaned.
        """
        ctx = self._ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        spec_dir = spex_root / "specs" / "2026-08-04-15-50-demo"
        spec_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_dir = Path(begin["log_path"]).parent
            assert session_dir.is_dir()
            assert not Path(begin["log_path"]).exists()
            assert not (spec_dir / "debug.log").exists()
            create_helper.main(
                ["end-session", "--name", "2026-08-04-15-50-demo"]
            )
            end = json.loads(capsys.readouterr().out.strip())

        assert end == {
            "ended": True,
            "merged_into": None,
            "deleted": False,
        }
        assert get_active_session_id(ctx.spex_root) is None
        assert not session_dir.exists()
        assert not (spex_root / "sessions" / begin["session_id"]).exists()
        assert not (spec_dir / "debug.log").exists()

    def test_end_session_with_name_merges_then_deletes(
        self, tmp_path, monkeypatch, capsys,
    ):
        ctx = self._ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        spec_dir = spex_root / "specs" / "2026-08-04-15-50-demo"
        spec_dir.mkdir()
        (spec_dir / "debug.log").write_text(
            "===== existing =====\n", encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_log = Path(begin["log_path"])
            session_log.write_text(
                "===== session history =====\n", encoding="utf-8",
            )
            create_helper.main(
                ["end-session", "--name", "2026-08-04-15-50-demo"]
            )
            end = json.loads(capsys.readouterr().out.strip())

        assert end["ended"] is True
        assert end["deleted"] is True
        assert end["merged_into"] == str(spec_dir / "debug.log")
        assert get_active_session_id(ctx.spex_root) is None
        assert not session_log.exists()
        assert not session_log.parent.exists()
        assert (spec_dir / "debug.log").read_text(encoding="utf-8") == (
            "===== existing =====\n"
            "===== session history =====\n"
        )
        assert not (spec_dir / "debug.session-pre.log").exists()
        assert not list(spex_root.glob("**/debug.session-pre.log"))

    def test_end_session_with_spec_path_merges(
        self, tmp_path, monkeypatch, capsys,
    ):
        ctx = self._ctx(tmp_path)
        spec_dir = Path(ctx.spex_root) / "specs" / "via-path"
        spec_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            Path(begin["log_path"]).write_text(
                "pre-name timeline\n", encoding="utf-8",
            )
            create_helper.main(
                ["end-session", "--spec-path", str(spec_dir)]
            )
            end = json.loads(capsys.readouterr().out.strip())

        assert end["deleted"] is True
        assert (spec_dir / "debug.log").read_text(encoding="utf-8") == (
            "pre-name timeline\n"
        )
        assert get_active_session_id(ctx.spex_root) is None

    def test_end_session_ambiguous_name_keeps_active_session(
        self, tmp_path, monkeypatch, capsys, caplog,
    ):
        import logging

        ctx = self._ctx(tmp_path)
        spex_root = Path(ctx.spex_root)
        (spex_root / "specs" / "2026-08-04-15-50-demo").mkdir()
        (spex_root / "specs" / "2026-08-04-16-00-demo").mkdir()
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_id = begin["session_id"]
            session_log = Path(begin["log_path"])
            session_log.write_text("keep me\n", encoding="utf-8")
            with caplog.at_level(logging.ERROR):
                with pytest.raises(SystemExit) as exc_info:
                    create_helper.main(["end-session", "--name", "demo"])

        assert exc_info.value.code == 1
        assert "multiple specs match 'demo'" in caplog.text
        assert get_active_session_id(ctx.spex_root) == session_id
        assert session_log.is_file()
        assert session_log.read_text(encoding="utf-8") == "keep me\n"

    def test_end_session_missing_name_keeps_active_session(
        self, tmp_path, monkeypatch, capsys, caplog,
    ):
        import logging

        ctx = self._ctx(tmp_path)
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_id = begin["session_id"]
            session_log = Path(begin["log_path"])
            session_log.write_text("orphan risk\n", encoding="utf-8")
            with caplog.at_level(logging.ERROR):
                with pytest.raises(SystemExit) as exc_info:
                    create_helper.main(
                        ["end-session", "--name", "no-such-spec"]
                    )

        assert exc_info.value.code == 1
        assert "no spec matching 'no-such-spec'" in caplog.text
        assert get_active_session_id(ctx.spex_root) == session_id
        assert session_log.is_file()

    def test_begin_session_fails_without_spex_root(
        self, tmp_path, monkeypatch,
    ):
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
        monkeypatch.chdir(tmp_path)
        with patch.object(cfg, "get_project_context", return_value=ctx):
            with pytest.raises(SystemExit) as exc_info:
                create_helper.main(["begin-session"])
        assert exc_info.value.code == 1


class TestPreparePostActionSession:
    """Tests for prepare-spec handoff and post-action debug anchors."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_config_cache()
        yield
        clear_config_cache()

    def _ctx(self, tmp_path, *, debug=False):
        spex_root = tmp_path / ".spex"
        (spex_root / "specs").mkdir(parents=True, exist_ok=True)
        return ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="main",
            user_name="Test",
            user_email="test@test.com",
            spex_tomls=[],
            config={"debug": debug},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

    def _run_prepare(self, tmp_path, ctx, monkeypatch, capsys, name):
        import common
        import prompt as prompt_mod

        specs_dir = Path(ctx.spex_root) / "specs"
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        monkeypatch.chdir(tmp_path)
        with (
            patch.object(common, "get_specs_dir", return_value=str(specs_dir)),
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch.object(
                prompt_mod, "render_prompt", return_value="# Template",
            ),
            patch("hooks.run_pre_action"),
        ):
            create_helper.main(
                ["prepare-spec", "--name", name, "--description", "desc"],
            )
        return json.loads(capsys.readouterr().out.strip())

    def test_prepare_merges_session_then_anchor_and_deletes(
        self, tmp_path, monkeypatch, capsys,
    ):
        ctx = self._ctx(tmp_path, debug=True)
        name = "2026-08-04-15-50-handoff"
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_log = Path(begin["log_path"])
            session_log.write_text(
                "===== session history =====\n", encoding="utf-8",
            )

            with patch("debug_log.debug_enabled", return_value=True):
                out = self._run_prepare(
                    tmp_path, ctx, monkeypatch, capsys, name,
                )

        spec_dir = Path(out["spec_path"])
        debug_log = spec_dir / "debug.log"
        assert out["spec_name"] == name
        assert get_active_session_id(ctx.spex_root) is None
        assert not session_log.exists()
        assert not session_log.parent.exists()
        content = debug_log.read_text(encoding="utf-8")
        assert content.index("===== session history =====\n") < content.index(
            f"===== CREATE prepare-spec ok name={name} =====\n"
        )
        assert not (spec_dir / "debug.session-pre.log").exists()

    def test_prepare_debug_false_clears_pointer_without_anchor(
        self, tmp_path, monkeypatch, capsys,
    ):
        ctx = self._ctx(tmp_path, debug=False)
        name = "2026-08-04-15-50-no-debug"
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_dir = Path(begin["log_path"]).parent
            assert session_dir.is_dir()
            assert not Path(begin["log_path"]).exists()

            out = self._run_prepare(
                tmp_path, ctx, monkeypatch, capsys, name,
            )

        spec_dir = Path(out["spec_path"])
        assert get_active_session_id(ctx.spex_root) is None
        assert not session_dir.exists()
        assert not (spec_dir / "debug.log").exists()

    def test_prepare_keeps_pointer_when_merge_fails(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Failed merge must not clear the active pointer (retryable handoff)."""
        ctx = self._ctx(tmp_path, debug=True)
        name = "2026-08-04-15-50-merge-fail"
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_id = begin["session_id"]
            session_log = Path(begin["log_path"])
            session_log.write_text(
                "===== session history =====\n", encoding="utf-8",
            )

            with patch(
                "debug_log.merge_session_log_into_spec",
                return_value=None,
            ):
                # Simulate OSError failure: merge returns None but log remains.
                out = self._run_prepare(
                    tmp_path, ctx, monkeypatch, capsys, name,
                )

        assert out["spec_name"] == name
        assert get_active_session_id(ctx.spex_root) == session_id
        assert session_log.is_file()
        # Prepare still succeeded; debug anchor may be written.
        content = (Path(out["spec_path"]) / "debug.log").read_text(
            encoding="utf-8",
        )
        assert f"===== CREATE prepare-spec ok name={name} =====\n" in content

    def test_prepare_growth_isolation_before_handoff(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Session size stays put when --name resolves elsewhere; handoff deletes."""
        ctx = self._ctx(tmp_path, debug=True)
        spex_root = Path(ctx.spex_root)
        side_spec = spex_root / "specs" / "2026-08-04-15-50-side"
        side_spec.mkdir()
        name = "2026-08-04-15-50-isolate"
        monkeypatch.chdir(tmp_path)

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_log = Path(begin["log_path"])
            session_log.write_text("session-entry\n", encoding="utf-8")
            session_size = session_log.stat().st_size

            with patch("debug_log.get_project_context", return_value=ctx):
                named_path = resolve_debug_log_path(
                    ["spex", "prompt", "--name", "2026-08-04-15-50-side"],
                )
            assert named_path == side_spec / "debug.log"
            named_path.write_text("spec-entry\n", encoding="utf-8")

            assert session_log.stat().st_size == session_size
            assert named_path.read_text(encoding="utf-8") == "spec-entry\n"

            out = self._run_prepare(
                tmp_path, ctx, monkeypatch, capsys, name,
            )

        new_spec = Path(out["spec_path"])
        assert not session_log.exists()
        assert get_active_session_id(ctx.spex_root) is None
        content = (new_spec / "debug.log").read_text(encoding="utf-8")
        assert content.startswith("session-entry\n")
        assert f"===== CREATE prepare-spec ok name={name} =====\n" in content
        # Side-spec log was never the handoff target.
        assert (side_spec / "debug.log").read_text(encoding="utf-8") == (
            "spec-entry\n"
        )

    def test_prepare_under_trace_command_handoff_cli_path(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Regression: spex resolve + trace_command must not orphan session log."""
        import common
        import prompt as prompt_mod

        ctx = self._ctx(tmp_path, debug=True)
        name = "2026-08-04-15-50-cli-path"
        monkeypatch.chdir(tmp_path)
        specs_dir = Path(ctx.spex_root) / "specs"

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("debug_log.get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
        ):
            create_helper.main(["begin-session"])
            begin = json.loads(capsys.readouterr().out.strip())
            session_log = Path(begin["log_path"])
            session_log.write_text(
                "===== session history =====\n", encoding="utf-8",
            )

            argv = [
                "spex", "create-helper", "prepare-spec",
                "--name", name, "--description", "desc",
            ]
            # Same pre-command resolve as spex: new --name does not exist yet.
            log_path = resolve_debug_log_path(argv)
            assert log_path == session_log

            monkeypatch.setattr(sys, "stdin", io.StringIO(""))
            with (
                patch.object(
                    common, "get_specs_dir", return_value=str(specs_dir),
                ),
                patch.object(
                    prompt_mod, "render_prompt", return_value="# Template",
                ),
                patch("hooks.run_pre_action"),
                trace_command(log_path, argv),
            ):
                create_helper.main(
                    ["prepare-spec", "--name", name, "--description", "desc"],
                )
            out = json.loads(capsys.readouterr().out.strip())

        spec_dir = Path(out["spec_path"])
        debug_log = spec_dir / "debug.log"
        assert get_active_session_id(ctx.spex_root) is None
        assert not session_log.exists()
        assert not session_log.parent.exists()
        content = debug_log.read_text(encoding="utf-8")
        history = "===== session history =====\n"
        anchor = f"===== CREATE prepare-spec ok name={name} =====\n"
        assert content.index(history) < content.index(anchor)
        assert "argv: spex create-helper prepare-spec" in content
        assert content.index(anchor) < content.index(
            "argv: spex create-helper prepare-spec",
        )
        assert "===== END exit=0 duration_ms=" in content

    def test_post_action_writes_anchor_when_debug_enabled(
        self, tmp_path, monkeypatch,
    ):
        todo = [
            {"id": "step-1", "name": "First", "details": "D",
             "completed_at": "", "commit_title": ""},
            {"id": "step-2", "name": "Second", "details": "D",
             "completed_at": "", "commit_title": ""},
        ]
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "2026-08-04-15-50-post"
        spec_dir.mkdir(parents=True)
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "post", "workdir": str(tmp_path)}),
            encoding="utf-8",
        )
        ctx = self._ctx(tmp_path, debug=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("config.get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
            patch("hooks.run_post_action"),
        ):
            create_helper.cli_post_action(
                ["--name", "2026-08-04-15-50-post"],
            )

        content = (spec_dir / "debug.log").read_text(encoding="utf-8")
        assert content == (
            "===== CREATE post-action ok "
            "name=2026-08-04-15-50-post steps=2 =====\n"
        )

    def test_post_action_skips_anchor_when_debug_disabled(
        self, tmp_path, monkeypatch,
    ):
        todo = [{"id": "s1", "name": "N", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "2026-08-04-15-50-quiet"
        spec_dir.mkdir(parents=True)
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "quiet", "workdir": str(tmp_path)}),
            encoding="utf-8",
        )
        ctx = self._ctx(tmp_path, debug=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("config.get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
            patch("hooks.run_post_action"),
        ):
            create_helper.cli_post_action(
                ["--name", "2026-08-04-15-50-quiet"],
            )

        assert not (spec_dir / "debug.log").exists()
