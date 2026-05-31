import subprocess
from unittest.mock import patch

from config import SpexContext
from create_helper import cli_create_validate, validate_create_branch


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
