"""Tests for create_helper.py — topic creation and branch validation."""

import io
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import config as cfg
import create_helper
import pytest
from config import SpexContext
from create_helper import (
    cli_create_validate,
    cli_prepare_spec,
    create_topic,
    validate_create_branch,
)


def _fake_context(**overrides):
    """Build a SpexContext with sensible defaults, overriding as needed."""
    defaults = {
        "spex_tomls": [],
        "config": {},
        "spex_root": "",
        "spex_roots": [],
        "top_workdir": None,
        "main_worktree": None,
    }
    defaults.update(overrides)
    return SpexContext(**defaults)


@dataclass
class MockSpexContext:
    top_workdir: Path | None = None
    main_worktree: Path | None = None


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

        git_info = {
            "workdir": "/home/user/project",
            "remote_url": "git@github.com:user/project.git",
            "branch": "main",
            "user_name": "Alice",
            "user_email": "alice@example.com",
        }
        ctx = MockSpexContext(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
        )
        create_helper._write_meta(
            topic_dir, git_info, ctx, "fix the login bug",
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

        git_info = {
            "workdir": "/home/user/project",
            "remote_url": "",
            "branch": "main",
            "user_name": "Alice",
            "user_email": "alice@example.com",
        }
        ctx = MockSpexContext(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
        )
        create_helper._write_meta(
            topic_dir, git_info, ctx, "", "2026-05-24T20:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["prompts"] == []
        assert meta["remote_url"] == ""

    def test_worktree_main_worktree_points_to_main(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()

        git_info = {
            "workdir": "/home/user/project-wt",
            "remote_url": "git@github.com:user/project.git",
            "branch": "feature",
            "user_name": "Alice",
            "user_email": "alice@example.com",
        }
        ctx = MockSpexContext(
            top_workdir=Path("/home/user/project-wt"),
            main_worktree=Path("/home/user/project"),
        )
        create_helper._write_meta(
            topic_dir, git_info, ctx, "add feature",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["workdir"] == "/home/user/project-wt"
        assert meta["main_worktree"] == "/home/user/project"

    def test_ctx_none_falls_back_to_git_info(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()

        git_info = {
            "workdir": "/fallback/project",
            "remote_url": "",
            "branch": "main",
            "user_name": "Alice",
            "user_email": "alice@example.com",
        }
        ctx = MockSpexContext(top_workdir=None, main_worktree=None)
        create_helper._write_meta(
            topic_dir, git_info, ctx, "",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["workdir"] == "/fallback/project"
        assert meta["main_worktree"] == "/fallback/project"


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

        mock_git = {
            "workdir": "/tmp/proj",
            "remote_url": "",
            "branch": "main",
            "user_name": "Test",
            "user_email": "test@test.com",
        }
        mock_ctx = MockSpexContext(
            top_workdir=Path("/tmp/proj"),
            main_worktree=Path("/tmp/proj"),
        )

        import prompt as prompt_mod

        with (
            patch.object(
                common, "get_specs_dir",
                return_value=str(tmp_path)),
            patch.object(
                common, "get_git_info", return_value=mock_git),
            patch.object(
                common, "local_iso_timestamp",
                return_value="2026-05-24T20:00:00+08:00"),
            patch.object(cfg, "get_context", return_value=mock_ctx),
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
    def _setup_topic(self, tmp_path, name, xml_content):
        topic_dir = tmp_path / name
        topic_dir.mkdir()
        (topic_dir / "todo.xml").write_text(
            xml_content, encoding="utf-8",
        )
        meta = {"topic": name, "workdir": str(tmp_path)}
        (topic_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )
        return topic_dir

    def test_converts_xml_to_json(self, tmp_path, monkeypatch):
        """post-action converts todo.xml and deletes the XML file."""
        topic_dir = self._setup_topic(tmp_path, "my-topic", (
            "<todo>\n  <step>\n"
            "    <step-id>step-1</step-id>\n"
            "    <step-name>First</step-name>\n"
            "    <step-details>Details here</step-details>\n"
            "    <completed-at></completed-at>\n"
            "    <commit-title></commit-title>\n"
            "  </step>\n</todo>\n"
        ))
        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--topic", "my-topic"],
            )

        assert (topic_dir / "todo.json").is_file()
        assert not (topic_dir / "todo.xml").exists()
        data = json.loads(
            (topic_dir / "todo.json").read_text(encoding="utf-8"),
        )
        assert len(data) == 1
        assert data[0]["id"] == "step-1"

    def test_missing_xml_fails(self, tmp_path, monkeypatch):
        """post-action errors when todo.xml does not exist."""
        topic_dir = tmp_path / "no-xml"
        topic_dir.mkdir()
        monkeypatch.setattr(
            "create_helper.resolve_topic_dir",
            lambda _name: topic_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--topic", "no-xml"],
            )

    def test_default_event_type_is_create(self, tmp_path, monkeypatch):
        """post-action defaults event-type to 'create'."""
        topic_dir = self._setup_topic(tmp_path, "evt-topic", (
            "<todo>\n  <step>\n"
            "    <step-id>s1</step-id>\n"
            "    <step-name>N</step-name>\n"
            "    <step-details>D</step-details>\n"
            "  </step>\n</todo>\n"
        ))
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
    @patch("config.get_context", return_value=_fake_context(config={
        "branch_management": True, "main_branch_name": "",
        "submit_method": "merge", "spex_root": ".spex"}))
    def test_outputs_success(self, _ctx, _branch, capsys):
        cli_create_validate()
        out = capsys.readouterr().out
        assert "develop" in out
        assert "Valid" in out
