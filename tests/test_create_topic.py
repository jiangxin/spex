"""Tests for create-topic-dir.py (direct import)."""

import importlib
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common  # noqa: E402
import config as cfg  # noqa: E402

create_topic_dir = importlib.import_module("create-topic-dir")
create_topic = create_topic_dir.create_topic


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
            create_topic_dir, "datetime"
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
        create_topic_dir._write_meta(
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
        create_topic_dir._write_meta(
            topic_dir, git_info, ctx, "", "2026-05-24T20:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["prompts"] == []
        assert meta["remote_url"] == ""

    def test_worktree_main_worktree_points_to_main(self, tmp_path):
        """In a linked worktree, main_worktree should point to the main
        worktree's top_workdir, not the current worktree."""
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
        create_topic_dir._write_meta(
            topic_dir, git_info, ctx, "add feature",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["workdir"] == "/home/user/project-wt"
        assert meta["main_worktree"] == "/home/user/project"

    def test_multiple_worktrees_share_main_worktree(self, tmp_path):
        """All worktrees of the same repo should record the same
        main_worktree value."""
        main_repo = Path("/home/user/project")
        worktrees = [
            Path("/home/user/project"),
            Path("/home/user/project-wt1"),
            Path("/home/user/project-wt2"),
        ]
        results = []
        for wt in worktrees:
            topic_dir = tmp_path / wt.name
            topic_dir.mkdir()
            git_info = {
                "workdir": str(wt),
                "remote_url": "git@github.com:user/project.git",
                "branch": "branch",
                "user_name": "Alice",
                "user_email": "alice@example.com",
            }
            ctx = MockSpexContext(
                top_workdir=wt,
                main_worktree=main_repo,
            )
            create_topic_dir._write_meta(
                topic_dir, git_info, ctx, "",
                "2026-05-29T10:00:00+08:00"
            )
            meta = json.loads((topic_dir / "meta.json").read_text())
            results.append(meta["main_worktree"])

        assert all(mw == str(main_repo) for mw in results)

    def test_ctx_none_falls_back_to_git_info(self, tmp_path):
        """When ctx fields are None, fall back to git_info workdir."""
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
        create_topic_dir._write_meta(
            topic_dir, git_info, ctx, "",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((topic_dir / "meta.json").read_text())
        assert meta["workdir"] == "/fallback/project"
        assert meta["main_worktree"] == "/fallback/project"


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_missing_argument_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with pytest.raises(SystemExit) as exc_info:
            create_topic_dir.main()
        assert exc_info.value.code == 2  # argparse exits with 2

    def test_invalid_topic_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["prog", "INVALID"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            create_topic_dir, "get_specs_dir", return_value=str(tmp_path)
        ):
            with pytest.raises(SystemExit) as exc_info:
                create_topic_dir.main()
            assert exc_info.value.code == 1

    def test_existing_topic_exits(self, monkeypatch, tmp_path):
        (tmp_path / "2026-05-20-14-30-existing").mkdir()
        monkeypatch.setattr(
            sys, "argv", ["prog", "2026-05-20-14-30-existing"]
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            create_topic_dir, "get_specs_dir", return_value=str(tmp_path)
        ):
            with pytest.raises(SystemExit) as exc_info:
                create_topic_dir.main()
            assert exc_info.value.code == 1

    def test_success_with_json_flag(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            sys, "argv", ["prog", "2026-05-20-14-30-new-topic", "--json"]
        )
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
        with (
            patch.object(
                create_topic_dir, "get_specs_dir",
                return_value=str(tmp_path)
            ),
            patch.object(
                create_topic_dir, "get_git_info", return_value=mock_git
            ),
            patch.object(
                create_topic_dir, "local_iso_timestamp",
                return_value="2026-05-24T20:00:00+08:00"
            ),
            patch.object(cfg, "get_context", return_value=mock_ctx),
        ):
            create_topic_dir.main()

        output = json.loads(capsys.readouterr().out.strip())
        assert output["topic_name"] == "2026-05-20-14-30-new-topic"
        assert output["topic_path"] == str(
            tmp_path / "2026-05-20-14-30-new-topic"
        )

        # Verify meta.json was written
        meta_path = tmp_path / "2026-05-20-14-30-new-topic" / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["prompts"] == ["hello prompt"]
        assert meta["created_at"] == "2026-05-24T20:00:00+08:00"

    def test_get_without_json_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            sys, "argv",
            ["prog", "2026-05-20-14-30-topic", "--get", "spex_root"]
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            create_topic_dir, "get_specs_dir", return_value=str(tmp_path)
        ):
            with pytest.raises(SystemExit) as exc_info:
                create_topic_dir.main()
            assert exc_info.value.code == 1

    def test_get_invalid_key_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            sys, "argv",
            ["prog", "2026-05-20-14-30-topic", "--json", "--get", "bad-key"]
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            create_topic_dir, "get_specs_dir", return_value=str(tmp_path)
        ):
            with pytest.raises(SystemExit) as exc_info:
                create_topic_dir.main()
            assert exc_info.value.code == 1

    def test_get_prompt(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            sys, "argv",
            ["prog", "2026-05-20-14-30-topic", "--json",
             "--get-prompt", "spec-template"]
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO("req"))

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
                create_topic_dir, "get_specs_dir",
                return_value=str(tmp_path)
            ),
            patch.object(
                create_topic_dir, "get_git_info", return_value=mock_git
            ),
            patch.object(
                create_topic_dir, "local_iso_timestamp",
                return_value="2026-05-24T20:00:00+08:00"
            ),
            patch.object(
                prompt_mod, "render_prompt",
                return_value="# Rendered Template"
            ),
            patch.object(cfg, "get_context", return_value=mock_ctx),
        ):
            create_topic_dir.main()

        output = json.loads(capsys.readouterr().out)
        assert output["topic_name"] == "2026-05-20-14-30-topic"
        assert output["spec_template"] == "# Rendered Template"

    def test_get_multiple_keys(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            sys, "argv",
            ["prog", "2026-05-20-14-30-topic", "--json",
             "--get", "spex_root,specs_dir"]
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO("req"))

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
        with (
            patch.object(
                create_topic_dir, "get_specs_dir",
                return_value=str(tmp_path)
            ),
            patch.object(
                create_topic_dir, "get_git_info", return_value=mock_git
            ),
            patch.object(
                create_topic_dir, "local_iso_timestamp",
                return_value="2026-05-24T20:00:00+08:00"
            ),
            patch.object(
                common, "get_spex_root",
                return_value="/mock/spex-root"
            ),
            patch.object(
                common, "get_specs_dir",
                return_value="/mock/specs-dir"
            ),
            patch.object(cfg, "get_context", return_value=mock_ctx),
        ):
            create_topic_dir.main()

        output = json.loads(capsys.readouterr().out)
        assert output["spex_root"] == "/mock/spex-root"
        assert output["specs_dir"] == "/mock/specs-dir"

    def test_success_without_json_flag(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            sys, "argv", ["prog", "2026-05-20-14-30-new-topic"]
        )
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
        with (
            patch.object(
                create_topic_dir, "get_specs_dir",
                return_value=str(tmp_path)
            ),
            patch.object(
                create_topic_dir, "get_git_info", return_value=mock_git
            ),
            patch.object(
                create_topic_dir, "local_iso_timestamp",
                return_value="2026-05-24T20:00:00+08:00"
            ),
            patch.object(cfg, "get_context", return_value=mock_ctx),
        ):
            create_topic_dir.main()

        output = capsys.readouterr().out.strip()
        assert output == str(tmp_path / "2026-05-20-14-30-new-topic")

        # Verify meta.json was written
        meta_path = tmp_path / "2026-05-20-14-30-new-topic" / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["prompts"] == ["hello prompt"]
