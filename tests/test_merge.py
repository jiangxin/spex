import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import common as spex_common
import merge as spex_merge
import pytest
from config import ProjectContext


def _mock_project_context(top_workdir=None):
    """Create a ProjectContext with the given top_workdir for mocking."""
    tw = Path(top_workdir) if top_workdir else None
    return ProjectContext(
        cwd=Path.cwd(),
        top_workdir=tw,
        main_worktree=tw,
        remote_url="",
        branch="",
        user_name="",
        user_email="",
        config={"submit_method": "merge"},
    )


def _setup_topic(tmp_path, spec_name="my-topic", spex_branch="spex/test",
                 branch="main", completed=True):
    """Create a spec directory with meta.json and todo.json."""
    specs = tmp_path / "specs"
    spec_dir = specs / spec_name
    spec_dir.mkdir(parents=True, exist_ok=True)

    meta = {"spex_branch": spex_branch, "branch": branch}
    (spec_dir / "meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )

    tasks = [
        {
            "id": "1",
            "name": "Task 1",
            "details": "Some details",
            "completed_at": "2026-01-01T00:00:00Z" if completed else "",
            "commit_title": "feat: task 1" if completed else "",
        }
    ]
    (spec_dir / "todo.json").write_text(
        json.dumps(tasks), encoding="utf-8"
    )

    return specs, spec_dir


@pytest.mark.slow
class TestDryRun:
    """Tests for --dry-run flag in cli_submit."""

    def test_dry_run_does_not_merge(self, tmp_path, caplog):
        specs, spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("worktree.find_worktree_for_branch", return_value=None), \
             patch("branch.merge_branch", mock_merge), \
             caplog.at_level(logging.INFO):
            spex_merge.cli_submit(["my-topic", "--dry-run"])

        mock_merge.assert_not_called()
        assert "Would merge" in caplog.text
        assert "Would merge in worktree" in caplog.text

    def test_dry_run_json_output(self, tmp_path, capsys):
        specs, spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("worktree.find_worktree_for_branch", return_value=None), \
             patch("branch.merge_branch", mock_merge):
            spex_merge.cli_submit(["my-topic", "--dry-run"])

        output = capsys.readouterr().out
        # Only JSON remains on stdout (info messages go to logging)
        data = json.loads(output.strip())
        assert data["dry_run"] is True
        assert data["source"] == "spex/test"
        assert data["target"] == "main"
        assert data["archived"] is True
        assert data["errors"] == []
        assert data["merge_cwd"] == str(tmp_path)
        assert data["spex_worktree"] == ""
        assert data["would_remove_worktree"] is False
        assert data["merge_cwd_head"] == ""
        assert data["would_switch"] is True
        assert data["target_checked_out"] is False

    def test_dry_run_logs_switch_and_merge_steps(
        self, tmp_path, caplog,
    ):
        specs, _spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("worktree.find_worktree_for_branch", return_value=None), \
             patch("branch.merge_branch", MagicMock()), \
             caplog.at_level(logging.INFO):
            spex_merge.cli_submit(["my-topic", "--dry-run"])

        assert "Would switch to main" in caplog.text
        assert "Would git merge spex/test" in caplog.text
        assert "current HEAD: unknown" in caplog.text

    def test_dry_run_no_archive(self, tmp_path, capsys, caplog):
        specs, spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("worktree.find_worktree_for_branch", return_value=None), \
             patch("branch.merge_branch", mock_merge), \
             caplog.at_level(logging.INFO):
            spex_merge.cli_submit(["my-topic", "--dry-run", "--no-archive"])

        mock_merge.assert_not_called()
        assert "Would merge" in caplog.text
        assert "Would archive" not in caplog.text
        assert "Would remove worktree" not in caplog.text
        output = capsys.readouterr().out
        data = json.loads(output.strip())
        assert data["archived"] is False
        assert data["would_remove_worktree"] is False

    def test_dry_run_short_flag(self, tmp_path, caplog):
        specs, spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("worktree.find_worktree_for_branch", return_value=None), \
             patch("branch.merge_branch", mock_merge), \
             caplog.at_level(logging.INFO):
            spex_merge.cli_submit(["my-topic", "-n"])

        mock_merge.assert_not_called()
        assert "Would merge" in caplog.text
        assert "Would git merge" in caplog.text


@pytest.mark.slow
class TestAutoSelect:
    """Tests for auto-selection when no spec name is provided."""

    def test_auto_select_single_topic(self, tmp_path, caplog):
        specs, spec_dir = _setup_topic(
            tmp_path, spec_name="auto-topic",
            spex_branch="spex/auto", completed=True,
        )
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()
        target_wt = Path(tmp_path)

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.branch_exists", return_value=True), \
             patch("worktree.find_worktree_for_branch",
                   return_value=target_wt), \
             patch("branch.merge_branch", mock_merge), \
             patch("hooks.run_post_action"), \
             patch("archive.archive_single_spec", return_value=None), \
             caplog.at_level(logging.ERROR):
            spex_merge.cli_submit([])

        mock_merge.assert_called_once()
        call_args = mock_merge.call_args
        assert call_args[0][1] == "spex/auto"
        assert call_args[1]["cwd"] == target_wt
        assert "Auto-selected: auto-topic" in caplog.text

    def test_auto_select_no_topics(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        specs.mkdir(parents=True)
        ctx = _mock_project_context(top_workdir=str(tmp_path))

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             caplog.at_level(logging.ERROR), \
             pytest.raises(SystemExit) as exc_info:
            spex_merge.cli_submit([])

        assert exc_info.value.code == 1
        assert "No submittable specs found" in caplog.text

    def test_auto_select_multiple_topics_non_interactive(
        self, tmp_path, caplog,
    ):
        specs = tmp_path / "specs"
        _setup_topic(tmp_path, spec_name="topic-a",
                     spex_branch="spex/a", completed=True)
        _setup_topic(tmp_path, spec_name="topic-b",
                     spex_branch="spex/b", completed=True)
        ctx = _mock_project_context(top_workdir=str(tmp_path))

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("sys.stdin") as mock_stdin, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.readline.return_value = ""
            spex_merge.cli_submit([])

        assert exc_info.value.code == 1
        assert "[1]" in caplog.text
        assert "[2]" in caplog.text
        assert "topic-a" in caplog.text
        assert "topic-b" in caplog.text


@pytest.mark.slow
class TestNoSpexBranch:
    """Test no spex_branch error path (lines 105-108)."""

    def test_no_spex_branch_exits_with_json(self, monkeypatch, caplog,
                                            capsys, tmp_path):
        """cli_submit exits 1 with JSON error when spec has no spex_branch."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        (repo / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{tmp_path}/spex"\n', encoding="utf-8"
        )
        specs = tmp_path / "spex" / "specs" / "no-branch-spec"
        specs.mkdir(parents=True)
        (specs / "meta.json").write_text(
            json.dumps({
                "name": "no-branch-spec",
                "workdir": str(repo),
                "branch": "main",
            }),
            encoding="utf-8",
        )
        monkeypatch.chdir(repo)
        spex_common.clear_spex_root_cache()

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                spex_merge.cli_submit(["no-branch-spec"])

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "No spex_branch" in data["errors"][0]
        assert data["errors"][0] in caplog.text


@pytest.mark.slow
class TestNonMergeSubmitMethod:
    """Test non-merge submit method error (lines 145-148)."""

    def test_submit_method_not_implemented(self, monkeypatch, caplog,
                                           capsys, tmp_path):
        """cli_submit exits 1 when submit_method is not 'merge'."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        (repo / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{tmp_path}/spex"\nsubmit_method = "pr"\n',
            encoding="utf-8",
        )
        specs = tmp_path / "spex" / "specs" / "pr-spec"
        specs.mkdir(parents=True)
        (specs / "meta.json").write_text(
            json.dumps({
                "name": "pr-spec",
                "workdir": str(repo),
                "branch": "main",
                "spex_branch": "spex/pr-spec",
            }),
            encoding="utf-8",
        )
        monkeypatch.chdir(repo)
        spex_common.clear_spex_root_cache()

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                spex_merge.cli_submit(["pr-spec"])

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "not implemented" in data["errors"][0]
        assert data["errors"][0] in caplog.text


class TestMergeErrorsToStderr:
    """P0-4 / R4-F4: JSON errors must also appear on stderr via logger."""

    def test_merge_conflict_logs_error_to_stderr(self, tmp_path, capsys, caplog):
        specs, _ = _setup_topic(tmp_path, spex_branch="spex/conflict")
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        conflict = subprocess.CalledProcessError(
            1, "git", stderr="CONFLICT (content)",
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.branch_exists", return_value=True), \
             patch("worktree.find_worktree_for_branch",
                   return_value=Path(tmp_path)), \
             patch("branch.merge_branch", side_effect=conflict), \
             patch("hooks.run_pre_action"), \
             caplog.at_level(logging.ERROR), \
             pytest.raises(SystemExit) as exc_info:
            spex_merge.cli_submit(["my-topic"])

        assert exc_info.value.code == 1
        data = json.loads(capsys.readouterr().out)
        assert "Merge failed" in data["errors"][0]
        assert data["errors"][0] in caplog.text

    def test_target_branch_create_failure_logs_to_stderr(
        self, tmp_path, capsys, caplog,
    ):
        specs, _ = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        create_err = subprocess.CalledProcessError(
            1, "git", stderr="fatal: cannot create branch",
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.branch_exists", return_value=False), \
             patch("worktree.find_worktree_for_branch", return_value=None), \
             patch("branch.create_and_switch_branch", side_effect=create_err), \
             patch("hooks.run_pre_action"), \
             caplog.at_level(logging.ERROR), \
             pytest.raises(SystemExit) as exc_info:
            spex_merge.cli_submit(["my-topic"])

        assert exc_info.value.code == 1
        data = json.loads(capsys.readouterr().out)
        assert "Failed to create target branch" in data["errors"][0]
        assert data["errors"][0] in caplog.text

    def test_target_not_checked_out_falls_back_to_main(
        self, tmp_path, capsys,
    ):
        """When target is free, merge in main_worktree (legacy path)."""
        specs, _ = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.branch_exists", return_value=True), \
             patch("worktree.find_worktree_for_branch", return_value=None), \
             patch("branch.merge_branch", mock_merge), \
             patch("hooks.run_pre_action"), \
             patch("hooks.run_post_action"), \
             patch("archive.archive_single_spec", return_value=None):
            spex_merge.cli_submit(["my-topic", "--no-archive"])

        data = json.loads(capsys.readouterr().out)
        assert data["errors"] == []
        mock_merge.assert_called_once()
        assert mock_merge.call_args[1]["cwd"] == ctx.main_worktree

    def test_success_path_has_no_error_logs(self, tmp_path, capsys, caplog):
        specs, _ = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.branch_exists", return_value=True), \
             patch("worktree.find_worktree_for_branch",
                   return_value=Path(tmp_path)), \
             patch("branch.merge_branch"), \
             patch("hooks.run_pre_action"), \
             patch("hooks.run_post_action"), \
             patch("archive.archive_single_spec", return_value=None), \
             caplog.at_level(logging.ERROR):
            spex_merge.cli_submit(["my-topic", "--no-archive"])

        data = json.loads(capsys.readouterr().out)
        assert data["errors"] == []
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)
