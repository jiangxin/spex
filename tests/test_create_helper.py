"""Tests for create_helper.py — topic creation and branch validation."""

import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import config as cfg
import create_helper
import pytest
from config import ProjectContext
from create_helper import (
    cli_create_validate,
    cli_prepare_spec,
    create_topic,
    validate_create_branch,
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

        topic_name, topic_dir = create_topic(
            "2026-05-20-14-30-hello", specs_dir
        )

        assert topic_name == "2026-05-20-14-30-hello"
        assert topic_dir == specs_dir / "2026-05-20-14-30-hello"
        assert topic_dir.is_dir()

    def test_creates_specs_dir_if_missing(self, tmp_path):
        specs_dir = tmp_path / "specs"

        topic_name, topic_dir = create_topic(
            "2026-05-20-14-30-new-topic", specs_dir
        )

        assert specs_dir.is_dir()
        assert topic_dir.is_dir()

    def test_invalid_name_no_date(self, tmp_path):
        with pytest.raises(ValueError, match="invalid topic name"):
            create_topic("no-date-prefix", tmp_path, auto_prefix=False)

    def test_invalid_name_uppercase(self, tmp_path):
        with pytest.raises(ValueError, match="invalid topic name"):
            create_topic("2026-05-20-14-30-UpperCase", tmp_path)

    def test_invalid_name_spaces(self, tmp_path):
        with pytest.raises(ValueError, match="invalid topic name"):
            create_topic("2026-05-20-14-30-has space", tmp_path)

    def test_exceeds_max_bytes(self, tmp_path):
        long_name = "2026-05-20-14-30-" + "a" * 54
        with pytest.raises(ValueError, match="exceeds 64 bytes"):
            create_topic(long_name, tmp_path)

    def test_already_exists(self, tmp_path):
        specs_dir = tmp_path / "specs"
        (specs_dir / "2026-05-20-14-30-existing").mkdir(parents=True)

        with pytest.raises(FileExistsError, match="already exists"):
            create_topic("2026-05-20-14-30-existing", specs_dir)

    def test_valid_name_with_numbers(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        topic_name, topic_dir = create_topic(
            "2026-01-01-09-15-add-v2-api", specs_dir
        )

        assert topic_dir.is_dir()

    def test_auto_prefix_adds_date(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        with patch.object(
            create_helper, "datetime"
        ) as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-05-24-20-00"
            topic_name, topic_dir = create_topic("my-topic", specs_dir)

        assert topic_name == "2026-05-24-20-00-my-topic"
        assert topic_dir == specs_dir / "2026-05-24-20-00-my-topic"
        assert topic_dir.is_dir()

    def test_explicit_prefix_kept(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        topic_name, topic_dir = create_topic(
            "2026-05-20-14-30-hello", specs_dir
        )

        assert topic_name == "2026-05-20-14-30-hello"
        assert topic_dir.is_dir()

    def test_auto_prefix_false_no_prefix_fails(self, tmp_path):
        with pytest.raises(ValueError, match="invalid topic name"):
            create_topic("my-topic", tmp_path, auto_prefix=False)


class TestWriteMeta:
    def test_meta_with_prompt(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
            remote_url="git@github.com:user/project.git",
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            topic_dir, ctx, "fix the login bug",
            "2026-05-24T20:00:00+08:00"
        )

        meta_path = topic_dir / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["workdir"] == "/home/user/project"
        assert meta["main_worktree"] == "/home/user/project"
        assert meta["remote_url"] == "git@github.com:user/project.git"
        assert meta["branch"] == "main"
        assert meta["user_name"] == "Alice"
        assert meta["user_email"] == "alice@example.com"
        assert meta["created_at"] == "2026-05-24T20:00:00+08:00"
        assert meta["prompts"] == ["fix the login bug"]

    def test_meta_with_empty_prompt(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            topic_dir, ctx, "", "2026-05-24T20:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["prompts"] == []
        assert meta["remote_url"] == ""

    def test_worktree_main_worktree_points_to_main(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project-wt"),
            main_worktree=Path("/home/user/project"),
            remote_url="git@github.com:user/project.git",
            branch="feature",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            topic_dir, ctx, "add feature",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["workdir"] == "/home/user/project-wt"
        assert meta["main_worktree"] == "/home/user/project"

    def test_ctx_none_workdir_is_empty(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=None,
            main_worktree=None,
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            topic_dir, ctx, "",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["workdir"] == ""
        assert meta["main_worktree"] == ""

    def test_json_field_order_without_description(self, tmp_path):
        """Verify JSON field order from TopicMeta matches legacy format."""
        topic_dir = tmp_path / "2026-01-01-10-00-order-test"
        topic_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/work"),
            main_worktree=Path("/work"),
            remote_url="git@example.com:r.git",
            branch="main",
            user_name="Alice",
            user_email="a@e.com",
        )
        create_helper._write_meta(
            topic_dir, ctx, "hello",
            "2026-01-01T10:00:00+08:00",
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        keys = list(meta.keys())
        expected_keys = [
            "topic", "workdir", "main_worktree", "remote_url",
            "branch", "user_name", "user_email", "created_at",
            "prompts",
        ]
        assert keys == expected_keys
        assert "description" not in meta
        assert "spex_branch" not in meta

    def test_json_field_order_with_description(self, tmp_path):
        """Verify description appears in correct position."""
        topic_dir = tmp_path / "2026-01-01-10-00-desc-order"
        topic_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/work"),
            main_worktree=Path("/work"),
            branch="main",
            user_name="Alice",
            user_email="a@e.com",
        )
        create_helper._write_meta(
            topic_dir, ctx, "",
            "2026-01-01T10:00:00+08:00",
            description="My feature desc",
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
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
                cli_prepare_spec(["--topic", "INVALID"])
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
                    ["--topic", "2026-05-20-14-30-existing"])
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
        ):
            cli_prepare_spec(
                ["--topic", "2026-05-20-14-30-new-topic",
                 "--description", "Test desc"])

        output = json.loads(capsys.readouterr().out.strip())
        assert output["topic_name"] == "2026-05-20-14-30-new-topic"
        assert output["topic_path"] == str(
            tmp_path / "2026-05-20-14-30-new-topic"
        )
        assert output["spec_template"] == "# Rendered Template"

        meta_path = tmp_path / "2026-05-20-14-30-new-topic" / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["prompts"] == ["hello prompt"]
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
    def test_auto_switch_success_output(self, _curr, _switch, capsys):
        result = validate_create_branch({"branch_management": True,
                                         "main_branch_name": "main"})
        assert result == "main"
        err = capsys.readouterr().err
        assert "Warning" in err
        assert "Switching" in err
        assert "Switched to branch" in err

    @patch("branch.switch_branch",
           side_effect=subprocess.CalledProcessError(
               1, "git", stderr="error: pathspec"))
    @patch("branch.get_current_branch", return_value="develop")
    def test_auto_switch_failure_exits(self, _curr, _switch, capsys):
        try:
            validate_create_branch({"branch_management": True,
                                    "main_branch_name": "main"})
            assert False, "Should have called sys.exit(-1)"
        except SystemExit as e:
            assert e.code == -1
        err = capsys.readouterr().err
        assert "failed to switch" in err

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
    def test_spex_prefix_error_includes_hint(self, _mock, capsys):
        try:
            validate_create_branch(
                {"branch_management": True, "main_branch_name": "",
                 "submit_method": "merge"})
        except SystemExit:
            pass
        err = capsys.readouterr().err
        assert "main_branch_name" in err
        assert "Hint" in err


class TestCliPostAction:
    def _setup_topic(self, tmp_path, name, todo_data):
        topic_dir = tmp_path / name
        topic_dir.mkdir()
        (topic_dir / "todo.json").write_text(
            json.dumps(todo_data, indent=2), encoding="utf-8",
        )
        meta = {"topic": name, "workdir": str(tmp_path)}
        (topic_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )
        return topic_dir

    def test_validates_json(self, tmp_path, monkeypatch):
        """post-action validates todo.json successfully."""
        todo = [{"id": "step-1", "name": "First",
                 "details": "D", "completed_at": "",
                 "commit_title": ""}]
        topic_dir = self._setup_topic(
            tmp_path, "my-topic", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--topic", "my-topic"],
            )

        assert (topic_dir / "todo.json").is_file()

    def test_missing_json_fails(self, tmp_path, monkeypatch):
        """post-action errors when todo.json does not exist."""
        topic_dir = tmp_path / "no-json"
        topic_dir.mkdir()
        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--topic", "no-json"],
            )

    def test_missing_required_field_fails(
        self, tmp_path, monkeypatch,
    ):
        """post-action fails when a required field is missing."""
        todo = [{"id": "step-1", "name": "First"}]
        topic_dir = self._setup_topic(
            tmp_path, "bad-field", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--topic", "bad-field"],
            )

    def test_duplicate_id_fails(self, tmp_path, monkeypatch):
        """post-action fails when step IDs are duplicated."""
        todo = [
            {"id": "step-1", "name": "A", "details": "D",
             "completed_at": "", "commit_title": ""},
            {"id": "step-1", "name": "B", "details": "D",
             "completed_at": "", "commit_title": ""},
        ]
        topic_dir = self._setup_topic(
            tmp_path, "dup-id", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--topic", "dup-id"],
            )

    def test_default_event_type_is_create(
        self, tmp_path, monkeypatch,
    ):
        """post-action defaults event-type to 'create'."""
        todo = [{"id": "s1", "name": "N", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        topic_dir = self._setup_topic(
            tmp_path, "evt-topic", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )

        with patch("hooks.run_post_action") as mock_hook:
            create_helper.cli_post_action(
                ["--topic", "evt-topic"],
            )
            mock_hook.assert_called_once()
            assert mock_hook.call_args[0][0] == "create"


class TestCliCreateValidate:
    @patch("branch.get_current_branch", return_value="develop")
    @patch("config.get_project_context", return_value=_fake_project_context(
        config={
            "branch_management": True, "main_branch_name": "",
            "submit_method": "merge", "spex_root": ".spex"}))
    def test_outputs_success(self, _ctx, _branch, capsys):
        cli_create_validate()
        out = capsys.readouterr().out
        assert "develop" in out
        assert "Valid" in out


class TestDescriptionWrapping:
    def test_write_meta_wraps_long_description(self, tmp_path):
        """_write_meta wraps descriptions longer than 68 chars."""
        topic_dir = tmp_path / "2026-01-01-10-00-wrap-test"
        topic_dir.mkdir()

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
            topic_dir, ctx, "",
            "2026-01-01T10:00:00+08:00", long_desc,
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        desc = meta["description"]
        assert "\n" in desc
        for line in desc.splitlines():
            assert len(line) <= 68

    def test_post_action_updates_description_from_spec(
        self, tmp_path, monkeypatch,
    ):
        """post-action updates meta.json description from spec.md."""
        topic_dir = tmp_path / "desc-topic"
        topic_dir.mkdir()

        # Write spec.md with front-matter description
        spec_content = (
            "---\n"
            "description: >\n"
            "  This is a long description from the spec front-matter"
            " that should be wrapped properly when saved to meta\n"
            "---\n"
            "\n# Spec content\n"
        )
        (topic_dir / "spec.md").write_text(
            spec_content, encoding="utf-8",
        )

        # Write valid todo.json
        todo = [{"id": "s1", "name": "Step 1", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        (topic_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )

        # Write initial meta.json
        meta = {"topic": "desc-topic", "workdir": str(tmp_path)}
        (topic_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )

        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--topic", "desc-topic"],
            )

        updated_meta = json.loads(
            (topic_dir / "meta.json").read_text(),
        )
        assert "description" in updated_meta
        assert updated_meta["description"] != ""

    def test_post_action_no_description_leaves_meta_unchanged(
        self, tmp_path, monkeypatch,
    ):
        """post-action leaves meta.json unchanged if no description."""
        topic_dir = tmp_path / "no-desc-topic"
        topic_dir.mkdir()

        # Write spec.md without description in front-matter
        spec_content = (
            "---\n"
            "title: My Spec\n"
            "---\n"
            "\n# Spec content\n"
        )
        (topic_dir / "spec.md").write_text(
            spec_content, encoding="utf-8",
        )

        # Write valid todo.json
        todo = [{"id": "s1", "name": "Step 1", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        (topic_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )

        # Write initial meta.json with existing description
        meta = {
            "topic": "no-desc-topic",
            "workdir": str(tmp_path),
            "description": "original description",
        }
        (topic_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )

        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--topic", "no-desc-topic"],
            )

        updated_meta = json.loads(
            (topic_dir / "meta.json").read_text(),
        )
        assert updated_meta["description"] == "original description"
