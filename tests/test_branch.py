import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from apply_helper import (
    cli_ensure_branch,
    cli_post_action,
    cli_precheck,
    validate_apply_branch,
)
from branch import (
    branch_exists,
    create_and_switch_branch,
    get_current_branch,
    merge_branch,
    resolve_default_branch,
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
            ["git", "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=None,
        )

    @patch("branch.subprocess.run")
    def test_detached_head_raises(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="fatal: ref HEAD is not a symbolic ref",
        )
        import unittest

        class _TestCase(unittest.TestCase):
            pass

        tc = _TestCase()
        with tc.assertRaises(RuntimeError) as ctx:
            get_current_branch()
        assert "detached HEAD" in str(ctx.exception)


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


def _git_init_with_commit(tmp_path, branch_name="master"):
    """Init a git repo with one commit on *branch_name*; return tip SHA."""
    subprocess.run(
        ["git", "init", "-b", branch_name],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    (tmp_path / "README").write_text("init\n")
    subprocess.run(
        ["git", "add", "."], cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    tip = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    return tip.stdout.strip()


@pytest.mark.slow
class TestCreateBranch:
    def test_create_branch_on_unborn_branch(self, tmp_path):
        """create_and_switch_branch should work on an unborn branch (no commits)."""
        subprocess.run(
            ["git", "init"], cwd=tmp_path, capture_output=True, check=True,
        )
        # Verify we're on an unborn branch
        current = get_current_branch(tmp_path)
        assert current  # e.g., "master" or "main"

        create_and_switch_branch("spex/test-feature", cwd=tmp_path)

        # On an unborn branch, git switch -c succeeds and switches HEAD,
        # but the branch won't show in rev-parse --verify until a commit
        # is made. Verify we're on the new branch via symbolic-ref.
        assert get_current_branch(tmp_path) == "spex/test-feature"

    def test_create_branch_from_explicit_base(self, tmp_path):
        """create_and_switch_branch with base starts from that ref."""
        master_tip = _git_init_with_commit(tmp_path, "master")
        # Advance HEAD on a divergent branch so current HEAD != master
        create_and_switch_branch("spex/other", cwd=tmp_path)
        (tmp_path / "other.txt").write_text("other\n")
        subprocess.run(
            ["git", "add", "."], cwd=tmp_path, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "other"],
            cwd=tmp_path, capture_output=True, check=True,
        )

        create_and_switch_branch("spex/from-master", cwd=tmp_path, base="master")
        assert get_current_branch(tmp_path) == "spex/from-master"
        tip = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert tip == master_tip
        # Must not contain the divergent commit
        contains = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "spex/other", "HEAD"],
            cwd=tmp_path, capture_output=True,
        )
        assert contains.returncode != 0


class TestMergeBranch:
    @patch("branch.subprocess.run")
    def test_merge_calls_switch_and_merge(self, mock_run):
        mock_run.side_effect = [
            # get_current_branch (not on target)
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="other\n", stderr="",
            ),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            ),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            ),
        ]
        merge_branch("main", "spex/feature")
        assert mock_run.call_count == 3
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
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="other\n", stderr="",
            ),
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
    def test_completed_spec_exits(self, _mock, tmp_path, capsys):
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

    @patch("branch.switch_branch")
    @patch(
        "branch.get_current_branch",
        side_effect=RuntimeError("Currently in detached HEAD state, no branch name."),
    )
    @patch("branch.branch_exists", return_value=True)
    @patch("common.is_spec_completed", return_value=False)
    def test_detached_head_reattaches_to_spex_branch(
        self, _completed, _exists, _curr, mock_switch, tmp_path, caplog,
    ):
        """Review agents that `git checkout <sha>` leave detached HEAD."""
        import logging

        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/feat"}), encoding="utf-8"
        )
        with caplog.at_level(logging.INFO):
            validate_apply_branch({"branch_management": True}, tmp_path)
        mock_switch.assert_called_once_with("spex/feat", None)
        assert "Re-attached detached HEAD" in caplog.text
        assert "spex/feat" in caplog.text

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

    @patch("branch.set_branch_description")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_and_switch_branch")
    @patch("common.is_spec_completed", return_value=False)
    def test_creates_branch_with_short_name(
        self, _completed, mock_create, _exists, _curr, _desc,
        tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"name": "2026-05-27-10-00-add-feature"}),
            encoding="utf-8",
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        # base "main" does not exist (branch_exists mocked False) → base=None
        mock_create.assert_called_once_with("spex/add-feature", None, base=None)

    @patch("branch.set_branch_description")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_and_switch_branch", side_effect=[
        subprocess.CalledProcessError(1, "git"),
        None,
    ])
    @patch("common.is_spec_completed", return_value=False)
    def test_fallback_to_long_name(
        self, _completed, mock_create, _exists, _curr, _desc,
        tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"name": "2026-05-27-10-00-add-feature"}),
            encoding="utf-8",
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        # First call with short name fails, second with long name succeeds
        assert mock_create.call_count == 2
        mock_create.assert_any_call("spex/add-feature", None, base=None)
        mock_create.assert_any_call(
            "spex/2026-05-27-10-00-add-feature", None, base=None,
        )

    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_and_switch_branch", side_effect=subprocess.CalledProcessError(1, "git"))
    @patch("common.is_spec_completed", return_value=False)
    def test_both_candidates_fail_exits(
        self, _completed, _create, _exists, _curr, tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"name": "add-feature"}), encoding="utf-8"
        )
        try:
            validate_apply_branch({"branch_management": True}, tmp_path)
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("branch.set_branch_description")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.create_and_switch_branch")
    @patch("common.is_spec_completed", return_value=False)
    def test_creates_branch_with_meta_branch_base(
        self, _completed, mock_create, _curr, _desc, tmp_path,
    ):
        """When meta.branch exists, pass it as base to create_and_switch_branch."""
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({
                "name": "2026-05-27-10-00-add-feature",
                "branch": "master",
            }),
            encoding="utf-8",
        )

        def _exists(name, cwd=None):
            return name == "master"

        with patch("branch.branch_exists", side_effect=_exists):
            validate_apply_branch({"branch_management": True}, tmp_path)
        mock_create.assert_called_once_with(
            "spex/add-feature", None, base="master",
        )

    @patch("branch.set_branch_description")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.create_and_switch_branch")
    @patch("common.is_spec_completed", return_value=False)
    def test_missing_base_falls_back_with_warning(
        self, _completed, mock_create, _curr, _desc, tmp_path, caplog,
    ):
        """Missing meta.branch base → warn, fall back to HEAD (base=None)."""
        import logging

        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({
                "name": "2026-05-27-10-00-add-feature",
                "branch": "does-not-exist",
            }),
            encoding="utf-8",
        )
        with patch("branch.branch_exists", return_value=False), \
             caplog.at_level(logging.WARNING):
            validate_apply_branch({"branch_management": True}, tmp_path)
        mock_create.assert_called_once_with(
            "spex/add-feature", None, base=None,
        )
        assert "does-not-exist" in caplog.text
        assert "current HEAD" in caplog.text


@pytest.mark.slow
class TestValidateApplyBranchBaseIntegration:
    """Integration: new spex branches start from meta.branch, not prior tip."""

    def test_no_cross_spec_commit_leakage(self, tmp_path):
        """HEAD on spex/a + meta.branch=master → B's branch merge-base is master."""
        master_tip = _git_init_with_commit(tmp_path, "master")

        # Spec A branch with an extra commit (simulates --all after applying A)
        create_and_switch_branch("spex/a", cwd=tmp_path, base="master")
        (tmp_path / "a.txt").write_text("spec-a\n")
        subprocess.run(
            ["git", "add", "."], cwd=tmp_path, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "spec-a work"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        a_tip = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert a_tip != master_tip
        assert get_current_branch(tmp_path) == "spex/a"

        # Spec B: incomplete todo so validate_apply_branch proceeds
        spec_b = tmp_path / "spec-b"
        spec_b.mkdir()
        (spec_b / "meta.json").write_text(
            json.dumps({
                "name": "2026-05-27-10-00-b-feature",
                "branch": "master",
            }),
            encoding="utf-8",
        )
        (spec_b / "todo.json").write_text(
            json.dumps([{"id": "t1", "name": "do something"}]),
            encoding="utf-8",
        )

        validate_apply_branch(
            {"branch_management": True}, spec_b, cwd=tmp_path,
        )

        assert get_current_branch(tmp_path) == "spex/b-feature"
        merge_base = subprocess.run(
            ["git", "merge-base", "HEAD", "master"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert merge_base == master_tip
        # Spec A's commit must NOT be an ancestor of B's branch
        contains_a = subprocess.run(
            ["git", "merge-base", "--is-ancestor", a_tip, "HEAD"],
            cwd=tmp_path, capture_output=True,
        )
        assert contains_a.returncode != 0

    def test_missing_base_falls_back_to_head_integration(
        self, tmp_path, caplog,
    ):
        """Missing base branch → create from current HEAD + warning, no exit."""
        import logging

        _git_init_with_commit(tmp_path, "master")
        create_and_switch_branch("spex/a", cwd=tmp_path, base="master")
        (tmp_path / "a.txt").write_text("spec-a\n")
        subprocess.run(
            ["git", "add", "."], cwd=tmp_path, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "spec-a work"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        a_tip = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()

        spec_b = tmp_path / "spec-b"
        spec_b.mkdir()
        (spec_b / "meta.json").write_text(
            json.dumps({
                "name": "2026-05-27-10-00-b-feature",
                "branch": "nonexistent-base",
            }),
            encoding="utf-8",
        )
        (spec_b / "todo.json").write_text(
            json.dumps([{"id": "t1", "name": "do something"}]),
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING):
            validate_apply_branch(
                {"branch_management": True}, spec_b, cwd=tmp_path,
            )

        assert get_current_branch(tmp_path) == "spex/b-feature"
        tip = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        # Fell back to current HEAD (spex/a tip), so A's commit is present
        assert tip == a_tip
        assert "nonexistent-base" in caplog.text


@pytest.mark.slow
class TestCliPrecheck:
    @patch("common.resolve_spec_dir")
    @patch("config.get_project_context", return_value=_fake_context(
        config={"branch_management": False}))
    def test_disabled_no_output(self, _ctx, mock_resolve, tmp_path,
                                capsys):
        mock_resolve.return_value = tmp_path
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps({}), encoding="utf-8")
        cli_precheck(["--name", "test-topic"])
        out = capsys.readouterr().out
        assert out == ""


class TestCliEnsureBranch:
    @patch("apply_helper.validate_apply_branch")
    @patch("common.resolve_spec_dir")
    def test_ensure_branch_calls_validate_only(
        self, mock_resolve, mock_validate, tmp_path,
    ):
        """ensure-branch re-attaches without firing apply hooks."""
        mock_resolve.return_value = tmp_path
        # Real dir so rev-parse fails cleanly (not a git repo) and
        # the ancestor guard is skipped before validate_apply_branch.
        with patch(
            "config.get_project_context",
            return_value=_fake_context(
                config={"branch_management": True},
                top_workdir=tmp_path,
            ),
        ):
            cli_ensure_branch(["--name", "test-topic"])
        mock_validate.assert_called_once_with(
            {"branch_management": True}, tmp_path, cwd=tmp_path,
        )


@pytest.mark.slow
class TestEnsureBranchAncestorGuard:
    """Integration: ensure-branch refuses discarding detached amends."""

    def _setup_spex_branch(self, tmp_path):
        _git_init_with_commit(tmp_path, "master")
        create_and_switch_branch("spex/feat", cwd=tmp_path, base="master")
        tip = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        spec_dir = tmp_path / "spec"
        spec_dir.mkdir()
        (spec_dir / "meta.json").write_text(
            json.dumps({
                "name": "feat",
                "spex_branch": "spex/feat",
                "branch": "master",
            }),
            encoding="utf-8",
        )
        (spec_dir / "todo.json").write_text(
            json.dumps([{"id": "t1", "name": "work"}]),
            encoding="utf-8",
        )
        return tip, spec_dir

    def test_detached_with_new_commit_refuses(self, tmp_path, caplog):
        """Detached amend → non-zero, recovery hint, branch unchanged."""
        import logging

        tip, spec_dir = self._setup_spex_branch(tmp_path)
        subprocess.run(
            ["git", "checkout", "--detach", "HEAD"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        (tmp_path / "fix.txt").write_text("amend\n")
        subprocess.run(
            ["git", "add", "."], cwd=tmp_path, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "detached amend"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        dangling = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert dangling != tip

        with patch(
            "config.get_project_context",
            return_value=_fake_context(
                config={"branch_management": True},
                top_workdir=tmp_path,
            ),
        ), patch(
            "common.resolve_spec_dir", return_value=spec_dir,
        ), caplog.at_level(logging.ERROR):
            try:
                cli_ensure_branch(["--name", "feat"])
                assert False, "Should have called sys.exit(1)"
            except SystemExit as e:
                assert e.code == 1

        assert "git branch -f" in caplog.text
        assert dangling in caplog.text
        # Still detached at the dangling commit; branch tip unchanged
        with pytest.raises(RuntimeError):
            get_current_branch(tmp_path)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert head == dangling
        branch_tip = subprocess.run(
            ["git", "rev-parse", "spex/feat"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert branch_tip == tip

    def test_detached_at_tip_reattaches(self, tmp_path):
        """Detached HEAD exactly at branch tip → normal re-attach."""
        tip, spec_dir = self._setup_spex_branch(tmp_path)
        subprocess.run(
            ["git", "checkout", "--detach", "HEAD"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        with pytest.raises(RuntimeError):
            get_current_branch(tmp_path)

        with patch(
            "config.get_project_context",
            return_value=_fake_context(
                config={"branch_management": True},
                top_workdir=tmp_path,
            ),
        ), patch("common.resolve_spec_dir", return_value=spec_dir):
            cli_ensure_branch(["--name", "feat"])

        assert get_current_branch(tmp_path) == "spex/feat"
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert head == tip

    def test_on_branch_unchanged(self, tmp_path):
        """Normal on-branch ensure-branch → exit 0, stay on branch."""
        tip, spec_dir = self._setup_spex_branch(tmp_path)
        assert get_current_branch(tmp_path) == "spex/feat"

        with patch(
            "config.get_project_context",
            return_value=_fake_context(
                config={"branch_management": True},
                top_workdir=tmp_path,
            ),
        ), patch("common.resolve_spec_dir", return_value=spec_dir):
            cli_ensure_branch(["--name", "feat"])

        assert get_current_branch(tmp_path) == "spex/feat"
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert head == tip

class TestCliPostAction:
    @patch("config.get_project_context", return_value=_fake_context())
    @patch("common.resolve_spec_dir")
    def test_outputs_text_with_branch(self, mock_resolve, _ctx,
                                      tmp_path, caplog):
        import logging
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/my-feat"}), encoding="utf-8"
        )
        mock_resolve.return_value = tmp_path
        with caplog.at_level(logging.INFO):
            cli_post_action(["--name", "my-feat"])
        assert "spex/my-feat" in caplog.text
        assert "Development completed" in caplog.text
        assert "main" in caplog.text

    @patch("config.get_project_context", return_value=_fake_context())
    @patch("common.resolve_spec_dir")
    @patch("common.load_meta", return_value=SpecMeta())
    def test_no_branch_no_output(self, _meta, _resolve, _ctx, capsys,
                                 tmp_path):
        _resolve.return_value = tmp_path
        cli_post_action(["--name", "no-branch"])
        out = capsys.readouterr().out
        assert out == ""


class TestCliSubmit:
    @patch("merge._find_submittable_specs", return_value=[])
    def test_no_spec_arg_exits(self, _mock, caplog):
        """Empty spec argument causes error exit."""
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                cli_submit([])
                assert False, "Should have called sys.exit(1)"
            except SystemExit as e:
                assert e.code == 1
        assert "spec" in caplog.text.lower()

    @patch("config.get_project_context")
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_spec_dir")
    def test_unrelated_spec_exits(self, mock_resolve, _specs, mock_ctx,
                                   tmp_path, caplog):
        """Spec not related to current project causes error exit."""
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


    @patch("archive.archive_single_spec", return_value=Path("/fake/archive"))
    @patch("worktree.find_worktree_for_branch", return_value=Path("/fake/main"))
    @patch("branch.merge_branch")
    @patch("branch.branch_exists", return_value=True)
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_spec_dir")
    def test_merge_success(self, mock_resolve, _specs, _ctx, _exists, mock_merge,
                           _find_wt, mock_archive, tmp_path, capsys):
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
        mock_merge.assert_called_once_with(
            "main", "spex/done", cwd=Path("/fake/main"),
        )

    @patch("archive.archive_single_spec", return_value=Path("/fake/archive"))
    @patch("worktree.find_worktree_for_branch", return_value=Path("/fake/main"))
    @patch("branch.merge_branch")
    @patch("branch.branch_exists", return_value=True)
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_spec_dir")
    def test_merge_success_archives(self, mock_resolve, _specs, _ctx,
                                    _exists, mock_merge, _find_wt, mock_archive,
                                    tmp_path, capsys):
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

    @patch("archive.archive_single_spec")
    @patch("worktree.find_worktree_for_branch", return_value=Path("/fake/main"))
    @patch("branch.branch_exists", return_value=True)
    @patch("branch.merge_branch")
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_spec_dir")
    def test_merge_success_no_archive_flag(self, mock_resolve, _specs, _ctx,
                                           mock_merge, _exists, _find_wt,
                                           mock_archive, tmp_path, capsys):
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

    @patch("archive.archive_single_spec")
    @patch("worktree.find_worktree_for_branch", return_value=Path("/fake/main"))
    @patch("branch.branch_exists", return_value=True)
    @patch("branch.merge_branch",
           side_effect=subprocess.CalledProcessError(1, "git", stderr="CONFLICT"))
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_spec_dir")
    def test_merge_failure_no_archive(self, mock_resolve, _specs, _ctx,
                                      _merge, _exists, _find_wt, mock_archive,
                                      tmp_path, capsys, caplog):
        import logging
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/conflict", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        with caplog.at_level(logging.ERROR):
            try:
                cli_submit(["conflict"])
                assert False, "Should have called sys.exit(1)"
            except SystemExit as e:
                assert e.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "Merge failed" in out["errors"][0]
        assert out["errors"][0] in caplog.text
        mock_archive.assert_not_called()

    @patch("worktree.find_worktree_for_branch", return_value=Path("/fake/main"))
    @patch("branch.branch_exists", return_value=True)
    @patch("branch.merge_branch",
           side_effect=subprocess.CalledProcessError(1, "git", stderr="CONFLICT"))
    @patch("config.get_project_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.get_specs_dir", return_value=Path("/fake/specs"))
    @patch("common.resolve_spec_dir")
    def test_merge_failure_exits_nonzero(self, mock_resolve, _specs, _ctx,
                                         _merge, _exists, _find_wt, tmp_path,
                                         capsys, caplog):
        import logging
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/conflict", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        with caplog.at_level(logging.ERROR):
            try:
                cli_submit(["conflict"])
                assert False, "Should have called sys.exit(1)"
            except SystemExit as e:
                assert e.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "Merge failed" in out["errors"][0]
        assert out["errors"][0] in caplog.text


@pytest.mark.slow
class TestCliRouting:
    """Test that the spex CLI routes to branch handlers."""

    SPEX_SCRIPT = str(
        Path(__file__).resolve().parent.parent / "skills" / "spex" / "scripts" / "spex"
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

    def test_submit_no_spec_exits(self, tmp_path):
        result = self._run_spex("submit", cwd=tmp_path)
        assert result.returncode in (1, 2)
        err = result.stderr.lower()
        assert "spec" in err or "auto-selected" in err


class TestStripRefsPrefix:
    """Test _strip_refs_prefix (line 12)."""

    def test_strips_refs_heads_prefix(self):
        """_strip_refs_prefix strips refs/heads/ prefix."""
        from branch import _strip_refs_prefix
        assert _strip_refs_prefix("refs/heads/feature-x") == "feature-x"

    def test_returns_short_name_unchanged(self):
        """_strip_refs_prefix returns short names unchanged."""
        from branch import _strip_refs_prefix
        assert _strip_refs_prefix("main") == "main"


class TestResolveDefaultBranch:
    """Test resolve_default_branch probe behavior."""

    @patch("branch.branch_exists", return_value=True)
    def test_main_exists(self, mock_exists):
        """Returns 'main' when only main exists."""
        result = resolve_default_branch()
        assert result == "main"
        # Should have checked main first
        mock_exists.assert_any_call("main", cwd=None)

    @patch("branch.branch_exists", side_effect=[False, True])
    def test_master_exists(self, mock_exists):
        """Returns 'master' when only master exists."""
        result = resolve_default_branch()
        assert result == "master"
        assert mock_exists.call_count == 2

    @patch("branch.branch_exists", return_value=True)
    def test_both_exist_returns_first(self, mock_exists):
        """Returns 'main' when both exist (first in probe order)."""
        result = resolve_default_branch()
        assert result == "main"
        # Should only check main since it exists
        assert mock_exists.call_count == 1

    @patch("branch.branch_exists", return_value=False)
    def test_neither_exists_returns_fallback(self, mock_exists):
        """Returns 'main' fallback when neither exists."""
        result = resolve_default_branch()
        assert result == "main"
        assert mock_exists.call_count == 2

    @patch("branch.branch_exists", side_effect=[False, True])
    def test_custom_candidates(self, mock_exists):
        """Returns first existing from custom candidates."""
        result = resolve_default_branch(candidates=["develop", "trunk"])
        assert result == "trunk"
        mock_exists.assert_any_call("develop", cwd=None)
        mock_exists.assert_any_call("trunk", cwd=None)

    @patch("branch.branch_exists", return_value=False)
    def test_custom_fallback(self, mock_exists):
        """Returns custom fallback when no candidates exist."""
        result = resolve_default_branch(fallback="develop")
        assert result == "develop"

    @patch("branch.branch_exists", side_effect=[True])
    def test_custom_candidates_first_exists(self, mock_exists):
        """Returns first candidate when it exists."""
        result = resolve_default_branch(candidates=["develop", "trunk"])
        assert result == "develop"
        assert mock_exists.call_count == 1

    @patch("branch.branch_exists")
    def test_cwd_forwarded(self, mock_exists):
        """cwd parameter is forwarded to branch_exists."""
        mock_exists.return_value = True
        resolve_default_branch(cwd="/some/path")
        mock_exists.assert_called_with("main", cwd="/some/path")


@pytest.mark.slow
class TestSwitchAndSetBranch:
    """Test switch_branch and set_branch_description (lines 68-69, 82-83)."""

    def test_switch_branch(self, tmp_path):
        """switch_branch switches to an existing branch."""
        from branch import switch_branch
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            cwd=str(tmp_path), capture_output=True,
        )
        # Create initial commit on main
        (tmp_path / "a").write_text("a")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Create target branch
        subprocess.run(
            ["git", "branch", "feature"], cwd=str(tmp_path), capture_output=True,
        )
        switch_branch("feature", cwd=str(tmp_path))
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(tmp_path),
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feature"

    def test_set_branch_description(self, tmp_path):
        """set_branch_description sets git config for branch."""
        from branch import set_branch_description
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "a").write_text("a")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        set_branch_description("master", "my desc", cwd=str(tmp_path))
        result = subprocess.run(
            ["git", "config", "branch.master.description"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        assert result.stdout.strip() == "my desc"
