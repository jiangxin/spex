import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from apply_helper import (
    cli_post_action,
    cli_precheck,
    validate_apply_branch,
)
from branch import (
    branch_exists,
    get_current_branch,
    merge_branch,
)
from common import SpecMeta, strip_date_prefix
from config import ProjectContext
from merge import cli_submit


def _fake_context(**overrides):
    """Build a ProjectContext with sensible defaults, overriding as needed."""
    defaults = {
        "cwd": Path.cwd(),
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


class TestStripDatePrefix:
    def test_removes_datetime_prefix(self):
        result = strip_date_prefix("2026-05-26-21-28-add-branch-management")
        assert result == "add-branch-management"

    def test_no_prefix_unchanged(self):
        assert strip_date_prefix("add-login-api") == "add-login-api"

    def test_minimal_suffix(self):
        assert strip_date_prefix("2026-01-01-00-00-x") == "x"


class TestGetCurrentBranch:
    @patch("branch.subprocess.run")
    def test_returns_branch_name(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="main\n", stderr=""
        )
        assert get_current_branch() == "main"
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=None,
        )


class TestBranchExists:
    @patch("branch.subprocess.run")
    def test_branch_exists(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        assert branch_exists("spex/add-feature") is True

    @patch("branch.subprocess.run")
    def test_branch_not_exists(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: not a valid ref"
        )
        assert branch_exists("spex/nonexistent") is False


class TestMergeBranch:
    @patch("branch.subprocess.run")
    def test_merge_calls_switch_and_merge(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        merge_branch("main", "spex/feature")
        assert mock_run.call_count == 2
        mock_run.assert_any_call(
            ["git", "switch", "main"],
            capture_output=True, text=True, check=True, cwd=None,
        )
        mock_run.assert_any_call(
                ["git", "-c", "merge.branchdesc=true", "-c", "merge.log=true",
                 "merge", "spex/feature", "--no-ff", "--no-edit"],
            capture_output=True, text=True, check=True, cwd=None,
        )

    @patch("branch.subprocess.run")
    def test_merge_raises_on_conflict(self, mock_run):
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="",
                                       stderr=""),
            subprocess.CalledProcessError(1, "git merge",
                                          stderr="CONFLICT"),
        ]
        try:
            merge_branch("main", "spex/feature")
            assert False, "Should have raised"
        except subprocess.CalledProcessError:
            pass


class TestValidateApplyBranch:
    def test_disabled_returns_immediately(self, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps({}), encoding="utf-8")
        # Should return without error when branch_management is False
        validate_apply_branch({"branch_management": False}, tmp_path)

    @patch("common.is_spec_completed", return_value=True)
    def test_completed_topic_exits(self, _mock, tmp_path, capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps({}), encoding="utf-8")
        try:
            validate_apply_branch({"branch_management": True}, tmp_path)
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("branch.get_current_branch", return_value="spex/feat")
    @patch("branch.branch_exists", return_value=True)
    def test_spex_branch_matches_current_noop(self, _exists, _curr, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/feat"}), encoding="utf-8"
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        # Should not call switch_branch since current already matches

    @patch("branch.switch_branch")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=True)
    @patch("common.is_spec_completed", return_value=False)
    def test_spex_branch_switches(self, _completed, _exists, _curr, mock_switch, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/feat"}), encoding="utf-8"
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        mock_switch.assert_called_once_with("spex/feat", None)

    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("common.is_spec_completed", return_value=False)
    def test_spex_branch_missing_exits(self, _completed, _exists, _curr, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/missing"}), encoding="utf-8"
        )
        try:
            validate_apply_branch({"branch_management": True}, tmp_path)
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("branch.switch_branch")
    @patch("branch.set_branch_description")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_branch")
    @patch("common.is_spec_completed", return_value=False)
    def test_creates_branch_with_short_name(
        self, _completed, mock_create, _exists, _curr, _desc, mock_switch,
        tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"topic": "2026-05-27-10-00-add-feature"}),
            encoding="utf-8",
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        mock_create.assert_called_once_with("spex/add-feature", None)
        mock_switch.assert_called_once_with("spex/add-feature", None)

    @patch("branch.switch_branch")
    @patch("branch.set_branch_description")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_branch", side_effect=[
        subprocess.CalledProcessError(1, "git"),
        None,
    ])
    @patch("common.is_spec_completed", return_value=False)
    def test_fallback_to_long_name(
        self, _completed, mock_create, _exists, _curr, _desc, mock_switch,
        tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"topic": "2026-05-27-10-00-add-feature"}),
            encoding="utf-8",
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        # First call with short name fails, second with long name succeeds
        assert mock_create.call_count == 2
        mock_create.assert_any_call("spex/add-feature", None)
        mock_create.assert_any_call("spex/2026-05-27-10-00-add-feature", None)
        mock_switch.assert_called_once_with(
            "spex/2026-05-27-10-00-add-feature", None
        )

    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_branch", side_effect=subprocess.CalledProcessError(1, "git"))
    @patch("common.is_spec_completed", return_value=False)
    def test_both_candidates_fail_exits(
        self, _completed, _create, _exists, _curr, tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"topic": "add-feature"}), encoding="utf-8"
        )
        try:
            validate_apply_branch({"branch_management": True}, tmp_path)
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1


class TestCliPrecheck:
    @patch("common.resolve_topic_dir")
    @patch("config.get_project_context", return_value=_fake_context(
        config={"branch_management": False}))
    def test_disabled_no_output(self, _ctx, mock_resolve, tmp_path,
                                capsys):
        mock_resolve.return_value = tmp_path
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps({}), encoding="utf-8")
        cli_precheck(["--topic", "test-topic"])
        out = capsys.readouterr().out
        assert out == ""


class TestCliPostAction:
    @patch("config.get_project_context", return_value=_fake_context())
    @patch("common.resolve_topic_dir")
    def test_outputs_text_with_branch(self, mock_resolve, _ctx,
                                      tmp_path, caplog):
        import logging
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/my-feat"}), encoding="utf-8"
        )
        mock_resolve.return_value = tmp_path
        with caplog.at_level(logging.INFO):
            cli_post_action(["--topic", "my-feat"])
        assert "spex/my-feat" in caplog.text
        assert "Development completed" in caplog.text
        assert "main" in caplog.text

    @patch("config.get_project_context", return_value=_fake_context())
    @patch("common.resolve_topic_dir")
    @patch("common.load_meta", return_value=SpecMeta())
    def test_no_branch_no_output(self, _meta, _resolve, _ctx, capsys,
                                 tmp_path):
        _resolve.return_value = tmp_path
        cli_post_action(["--topic", "no-branch"])
        out = capsys.readouterr().out
        assert out == ""


class TestCliSubmit:
    @patch("merge._find_submittable_topics", return_value=[])
    def test_no_topic_arg_exits(self, _mock, caplog):
        """Empty topic argument causes error exit."""
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                cli_submit([])
                assert False, "Should have called sys.exit(1)"
            except SystemExit as e:
                assert e.code == 1
        assert "topic" in caplog.text.lower()

    @patch("config.get_project_context")
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_topic_dir")
    def test_unrelated_topic_exits(self, mock_resolve, _specs, mock_ctx,
                                   tmp_path, caplog):
        """Topic not related to current project causes error exit."""
        import logging
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({
                "spex_branch": "spex/done",
                "branch": "main",
                "workdir": "/other/project",
            }),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        # Create a context with a different top_workdir so is_related_to fails
        ctx = _fake_context(
            top_workdir=Path("/my/project"),
            main_worktree=Path("/my/project"),
            config={"submit_method": "merge"},
        )
        mock_ctx.return_value = ctx
        with caplog.at_level(logging.ERROR):
            try:
                cli_submit(["done-topic"])
                assert False, "Should have called sys.exit(1)"
            except SystemExit as e:
                assert e.code == 1
        assert "not related to current project" in caplog.text
        assert "/other/project" in caplog.text

    @patch("archive.archive_single_topic", return_value=Path("/fake/archive"))
    @patch("branch.merge_branch")
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_topic_dir")
    def test_merge_success(self, mock_resolve, _specs, _ctx, mock_merge,
                           mock_archive, tmp_path, capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/done", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        cli_submit(["done-topic"])
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "merge"
        assert out["source"] == "spex/done"
        assert out["target"] == "main"
        assert out["errors"] == []
        assert "archived" in out
        mock_merge.assert_called_once_with("main", "spex/done", cwd=None)

    @patch("archive.archive_single_topic", return_value=Path("/fake/archive"))
    @patch("branch.merge_branch")
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_topic_dir")
    def test_merge_success_archives(self, mock_resolve, _specs, _ctx,
                                    mock_merge, mock_archive, tmp_path,
                                    capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/done", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        cli_submit(["done-topic"])
        out = json.loads(capsys.readouterr().out)
        assert out["archived"] is True
        mock_archive.assert_called_once()

    @patch("archive.archive_single_topic")
    @patch("branch.merge_branch")
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_topic_dir")
    def test_merge_success_no_archive_flag(self, mock_resolve, _specs, _ctx,
                                           mock_merge, mock_archive,
                                           tmp_path, capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/done", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        cli_submit(["done-topic", "--no-archive"])
        out = json.loads(capsys.readouterr().out)
        assert out["archived"] is False
        mock_archive.assert_not_called()

    @patch("archive.archive_single_topic")
    @patch("branch.merge_branch",
           side_effect=subprocess.CalledProcessError(1, "git", stderr="CONFLICT"))
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_topic_dir")
    def test_merge_failure_no_archive(self, mock_resolve, _specs, _ctx,
                                      _merge, mock_archive, tmp_path,
                                      capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/conflict", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        try:
            cli_submit(["conflict"])
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "Merge failed" in out["errors"][0]
        mock_archive.assert_not_called()

    @patch("branch.merge_branch",
           side_effect=subprocess.CalledProcessError(1, "git", stderr="CONFLICT"))
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_topic_dir")
    def test_merge_failure_exits_nonzero(self, mock_resolve, _specs, _ctx,
                                         _merge, tmp_path, capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/conflict", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        try:
            cli_submit(["conflict"])
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "Merge failed" in out["errors"][0]


class TestCliRouting:
    """Test that the spex CLI routes to branch handlers."""

    SPEX_SCRIPT = str(
        Path(__file__).resolve().parent.parent / "scripts" / "spex"
    )

    def _run_spex(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, self.SPEX_SCRIPT, *args],
            capture_output=True,
            text=True,
            cwd=cwd,
        )

    def test_create_helper_no_flag_exits(self, tmp_path):
        result = self._run_spex("create-helper", cwd=tmp_path)
        assert result.returncode in (1, 2)
        assert "usage:" in result.stderr

    def test_apply_helper_no_flag_exits(self, tmp_path):
        result = self._run_spex("apply-helper", cwd=tmp_path)
        assert result.returncode in (1, 2)
        assert "usage:" in result.stderr

    def test_submit_no_topic_exits(self, tmp_path):
        result = self._run_spex("submit", cwd=tmp_path)
        assert result.returncode in (1, 2)
        err = result.stderr.lower()
        assert "topic" in err or "auto-selected" in err
