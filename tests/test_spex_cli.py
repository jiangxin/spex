"""Tests for the spex config command."""

import importlib.util
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

import pytest

_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_scripts_dir))

SPEX_SCRIPT = str(_scripts_dir / "spex")

# Load the spex CLI module (no .py extension) via importlib with an
# explicit SourceFileLoader so Python treats the extensionless file as
# regular Python source.
_loader = SourceFileLoader("spex_cli", SPEX_SCRIPT)
_spec = importlib.util.spec_from_file_location(
    "spex_cli", SPEX_SCRIPT, loader=_loader,
)
_spex_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_spex_mod)

from config import SpexContext  # noqa: E402

_build_config_vars = _spex_mod._build_config_vars
_print_config_vars = _spex_mod._print_config_vars
_run_config = _spex_mod._run_config


def _make_context(**overrides):
    """Create a SpexContext with sensible defaults, applying overrides."""
    defaults = {
        "top_workdir": Path("/test/repo"),
        "main_worktree": Path("/test/repo"),
        "spex_root": "/test/repo/.spex",
        "config": {
            "spex_root": ".spex",
            "create_branch": False,
            "main_branch_name": "",
            "submit_method": "merge",
        },
        "spex_tomls": [Path("/test/repo/.spex.toml")],
        "spex_roots": ["/test/repo/.spex"],
    }
    defaults.update(overrides)
    return SpexContext(**defaults)


class TestBuildConfigVars:
    """Tests for _build_config_vars."""

    def test_returns_all_fields(self):
        ctx = _make_context()
        result = _build_config_vars(ctx)

        expected_keys = [
            "top_workdir", "main_worktree", "spex_root",
            "config.spex_root", "config.create_branch",
            "config.main_branch_name", "config.submit_method",
            "spex_tomls", "spex_roots",
        ]
        assert list(result.keys()) == expected_keys

    def test_scalar_values_not_is_list(self):
        ctx = _make_context()
        result = _build_config_vars(ctx)

        for key in ("top_workdir", "main_worktree", "spex_root",
                     "config.spex_root"):
            _, is_list = result[key]
            assert is_list is False, f"{key} should not be a list"

    def test_list_values_are_is_list(self):
        ctx = _make_context()
        result = _build_config_vars(ctx)

        for key in ("spex_tomls", "spex_roots"):
            _, is_list = result[key]
            assert is_list is True, f"{key} should be a list"

    def test_none_top_workdir(self):
        ctx = _make_context(top_workdir=None)
        result = _build_config_vars(ctx)

        val, _ = result["top_workdir"]
        assert val is None


class TestPrintConfigVars:
    """Tests for _print_config_vars."""

    def test_all_vars_scalars_before_lists(self, capsys):
        ctx = _make_context()
        all_vars = _build_config_vars(ctx)
        _print_config_vars(all_vars, None)

        out = capsys.readouterr().out
        lines = out.strip().splitlines()

        # Find first list-format line (starts with "- " or is a header
        # followed by "- ")
        scalar_keys = [
            "top_workdir", "main_worktree", "spex_root",
            "config.spex_root", "config.create_branch",
            "config.main_branch_name", "config.submit_method",
        ]
        list_keys = ["spex_tomls", "spex_roots"]

        # All scalar keys should appear before any list key
        last_scalar_idx = -1
        first_list_idx = len(lines)
        for i, line in enumerate(lines):
            key = line.split()[0] if line.split() else ""
            if key in scalar_keys:
                last_scalar_idx = max(last_scalar_idx, i)
            if key in list_keys:
                first_list_idx = min(first_list_idx, i)

        assert last_scalar_idx < first_list_idx

    def test_none_value_shows_none(self, capsys):
        all_vars = {"myvar": (None, False)}
        _print_config_vars(all_vars, None)

        out = capsys.readouterr().out
        assert "myvar : (none)" in out

    def test_empty_list_shows_empty(self, capsys):
        all_vars = {"mylist": ([], True)}
        _print_config_vars(all_vars, None)

        out = capsys.readouterr().out
        assert "mylist : (empty)" in out

    def test_list_items_use_dash_prefix(self, capsys):
        all_vars = {"paths": (["/a", "/b"], True)}
        _print_config_vars(all_vars, None)

        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert lines[0] == "paths :"
        assert lines[1] == "  - /a"
        assert lines[2] == "  - /b"

    def test_unknown_variable_errors(self, capsys):
        all_vars = {"known": ("val", False)}

        with pytest.raises(SystemExit) as exc_info:
            _print_config_vars(all_vars, ["unknown_var"])

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "unknown variable 'unknown_var'" in err

    def test_requested_vars_filter(self, capsys):
        all_vars = {
            "a": ("val_a", False),
            "b": ("val_b", False),
            "c": ("val_c", False),
        }
        _print_config_vars(all_vars, ["b"])

        out = capsys.readouterr().out
        assert "b : val_b" in out
        assert "a " not in out
        assert "c " not in out


class TestRunConfig:
    """Tests for _run_config."""

    def test_default_output_shows_all_fields(self, capsys):
        ctx = _make_context()
        with patch("config.get_context", return_value=ctx):
            _run_config([])

        out = capsys.readouterr().out
        for key in ("top_workdir", "main_worktree", "spex_root",
                     "config.spex_root", "config.create_branch",
                     "config.main_branch_name", "config.submit_method",
                     "spex_tomls", "spex_roots"):
            assert key in out, f"{key} not found in output"

    def test_default_output_lists_last(self, capsys):
        ctx = _make_context()
        with patch("config.get_context", return_value=ctx):
            _run_config([])

        out = capsys.readouterr().out
        lines = out.strip().splitlines()

        # Find line indices for spex_root (scalar) and spex_tomls (list)
        spex_root_idx = next(
            i for i, line in enumerate(lines)
            if line.startswith("spex_root")
        )
        spex_tomls_idx = next(
            i for i, line in enumerate(lines)
            if line.startswith("spex_tomls")
        )
        assert spex_root_idx < spex_tomls_idx

    def test_get_subcommand_filters(self, capsys):
        ctx = _make_context()
        with patch("config.get_context", return_value=ctx):
            _run_config(["get", "spex_root"])

        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert len(lines) == 1
        assert lines[0].startswith("spex_root")

    def test_multi_variable_query_in_order(self, capsys):
        ctx = _make_context()
        with patch("config.get_context", return_value=ctx):
            _run_config(["spex_root", "top_workdir"])

        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert len(lines) == 2
        # Canonical order: top_workdir before spex_root
        assert lines[0].startswith("top_workdir")
        assert lines[1].startswith("spex_root")

    def test_list_variable_format(self, capsys):
        ctx = _make_context(
            spex_tomls=[Path("/a/.spex.toml"), Path("/b/.spex.toml")],
        )
        with patch("config.get_context", return_value=ctx):
            _run_config(["spex_tomls"])

        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert lines[0] == "spex_tomls :"
        assert lines[1] == "  - /a/.spex.toml"
        assert lines[2] == "  - /b/.spex.toml"

    def test_empty_list_shows_empty(self, capsys):
        ctx = _make_context(spex_tomls=[])
        with patch("config.get_context", return_value=ctx):
            _run_config(["spex_tomls"])

        out = capsys.readouterr().out
        assert "spex_tomls : (empty)" in out

    def test_none_value_shows_none(self, capsys):
        ctx = _make_context(top_workdir=None)
        with patch("config.get_context", return_value=ctx):
            _run_config(["top_workdir"])

        out = capsys.readouterr().out
        assert "top_workdir : (none)" in out

    def test_unknown_variable_error(self, capsys):
        ctx = _make_context()
        with patch("config.get_context", return_value=ctx):
            with pytest.raises(SystemExit) as exc_info:
                _run_config(["no_such_var"])

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "unknown variable" in err

    def test_hyphen_to_underscore_spex_root(self, capsys):
        ctx = _make_context()
        with patch("config.get_context", return_value=ctx):
            _run_config(["spex-root"])

        out = capsys.readouterr().out
        assert "spex_root" in out
        assert " : " in out

    def test_hyphen_to_underscore_config_key(self, capsys):
        ctx = _make_context()
        with patch("config.get_context", return_value=ctx):
            _run_config(["config.main-branch-name"])

        out = capsys.readouterr().out
        assert "config.main_branch_name" in out
        assert " : " in out


class TestOldGetCommandRemoved:
    """Verify that the old 'spex get' command is no longer available."""

    def test_spex_get_returns_unknown_command(self):
        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "get"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "Unknown command: get" in result.stderr
