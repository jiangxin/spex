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

from config import ProjectContext  # noqa: E402

_build_config_sections = _spex_mod._build_config_sections
_print_config_sections = _spex_mod._print_config_sections
_run_config = _spex_mod._run_config
_section_header = _spex_mod._section_header
_format_value = _spex_mod._format_value


def _make_context(**overrides):
    """Create a ProjectContext with sensible defaults, applying overrides."""
    defaults = {
        "cwd": Path("/test/repo"),
        "top_workdir": Path("/test/repo"),
        "main_worktree": Path("/test/repo"),
        "remote_url": "https://github.com/test/repo.git",
        "branch": "main",
        "user_name": "Test User",
        "user_email": "test@example.com",
        "spex_root": "/test/repo/.spex",
        "config": {
            "spex_root": ".spex",
            "branch_management": True,
            "main_branch_name": "",
            "submit_method": "merge",
        },
        "spex_tomls": [Path("/test/repo/.spex.toml")],
        "spex_roots": ["/test/repo/.spex"],
    }
    defaults.update(overrides)
    return ProjectContext(**defaults)


class TestSectionHeader:
    """Tests for _section_header."""

    def test_default_width(self):
        header = _section_header("Git")
        assert header.startswith("── Git ")
        assert len(header) == 50

    def test_long_name(self):
        header = _section_header("Config Files")
        assert header.startswith("── Config Files ")
        assert len(header) == 50

    def test_minimum_padding(self):
        header = _section_header("A" * 50, width=50)
        assert header.endswith("───")


class TestFormatValue:
    """Tests for _format_value."""

    def test_none(self):
        assert _format_value(None) == ""

    def test_empty_string(self):
        assert _format_value("") == ""

    def test_bool_true(self):
        assert _format_value(True) == "true"

    def test_bool_false(self):
        assert _format_value(False) == "false"

    def test_string(self):
        assert _format_value("hello") == "hello"

    def test_path(self):
        assert _format_value(Path("/a/b")) == "/a/b"


class TestBuildConfigSections:
    """Tests for _build_config_sections."""

    def test_returns_five_sections(self):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        assert len(sections) == 5
        names = [name for name, _, _ in sections]
        assert names == [
            "Git", "Paths", "Config", "Config Files", "Spec Roots",
        ]

    def test_git_section_keys(self):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        name, kind, entries = sections[0]
        assert name == "Git"
        assert kind == "kv"
        keys = [k for k, _ in entries]
        assert keys == ["branch", "remote_url", "user_name", "user_email"]

    def test_git_section_values(self):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        _, _, entries = sections[0]
        vals = dict(entries)
        assert vals["branch"] == "main"
        assert vals["remote_url"] == "https://github.com/test/repo.git"
        assert vals["user_name"] == "Test User"
        assert vals["user_email"] == "test@example.com"

    def test_paths_section(self):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        name, kind, entries = sections[1]
        assert name == "Paths"
        assert kind == "kv"
        keys = [k for k, _ in entries]
        assert keys == ["cwd", "top_workdir", "main_worktree", "spex_root"]

    def test_config_section_no_prefix(self):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        name, kind, entries = sections[2]
        assert name == "Config"
        assert kind == "kv"
        keys = [k for k, _ in entries]
        assert keys == [
            "spex_root", "branch_management",
            "main_branch_name", "submit_method",
        ]

    def test_config_section_values(self):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        _, _, entries = sections[2]
        vals = dict(entries)
        assert vals["spex_root"] == ".spex"
        assert vals["branch_management"] is True
        assert vals["main_branch_name"] == ""
        assert vals["submit_method"] == "merge"

    def test_list_sections(self):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        # Config Files
        name, kind, entries = sections[3]
        assert name == "Config Files"
        assert kind == "list"
        assert entries == [Path("/test/repo/.spex.toml")]
        # Spec Roots
        name, kind, entries = sections[4]
        assert name == "Spec Roots"
        assert kind == "list"
        assert entries == ["/test/repo/.spex"]

    def test_none_top_workdir(self):
        ctx = _make_context(top_workdir=None)
        sections = _build_config_sections(ctx)
        _, _, entries = sections[1]
        vals = dict(entries)
        assert vals["top_workdir"] is None


class TestPrintConfigSections:
    """Tests for _print_config_sections."""

    def test_section_headers_present(self, capsys):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        assert "── Git " in out
        assert "── Paths " in out
        assert "── Config " in out
        assert "── Config Files " in out
        assert "── Spec Roots " in out

    def test_kv_format_uses_equals(self, capsys):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        assert "  branch " in out
        assert " = main" in out

    def test_empty_value_no_placeholder(self, capsys):
        ctx = _make_context(remote_url="")
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        lines = out.splitlines()
        remote_line = [x for x in lines if "remote_url" in x][0]
        assert remote_line.rstrip().endswith("=")

    def test_none_value_empty_after_equals(self, capsys):
        ctx = _make_context(top_workdir=None)
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        lines = out.splitlines()
        tw_line = [x for x in lines if "top_workdir" in x][0]
        assert tw_line.rstrip().endswith("=")

    def test_bool_lowercase(self, capsys):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        assert "= true" in out

    def test_list_section_items(self, capsys):
        ctx = _make_context(
            spex_tomls=[Path("/a/.spex.toml"), Path("/b/.spex.toml")],
        )
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        assert "  /a/.spex.toml" in out
        assert "  /b/.spex.toml" in out

    def test_empty_list_section(self, capsys):
        ctx = _make_context(spex_tomls=[])
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        assert "── Config Files " in out

    def test_no_color_when_not_tty(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        assert "\033[" not in out

    def test_sections_separated_by_blank_line(self, capsys):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        _print_config_sections(sections)
        out = capsys.readouterr().out
        # Between Git and Paths sections there should be a blank line
        assert "── Git " in out
        assert "── Paths " in out
        git_idx = out.index("── Git ")
        paths_idx = out.index("── Paths ")
        between = out[git_idx:paths_idx]
        assert "\n\n" in between

    def test_unknown_variable_errors(self, capsys):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        with pytest.raises(SystemExit) as exc_info:
            _print_config_sections(sections, ["unknown_var"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "unknown variable 'unknown_var'" in err

    def test_requested_kv_filter(self, capsys):
        ctx = _make_context()
        sections = _build_config_sections(ctx)
        _print_config_sections(sections, ["branch"])
        out = capsys.readouterr().out
        assert "branch" in out
        assert " = main" in out
        # Should not contain section headers
        assert "── " not in out


class TestRunConfig:
    """Tests for _run_config."""

    def test_default_output_shows_all_sections(self, capsys):
        ctx = _make_context()
        with patch("config.get_project_context", return_value=ctx):
            _run_config([])
        out = capsys.readouterr().out
        for header in ("── Git ", "── Paths ", "── Config ",
                        "── Config Files ", "── Spec Roots "):
            assert header in out, f"{header} not found in output"

    def test_default_output_shows_all_keys(self, capsys):
        ctx = _make_context()
        with patch("config.get_project_context", return_value=ctx):
            _run_config([])
        out = capsys.readouterr().out
        for key in ("branch", "remote_url", "user_name", "user_email",
                     "cwd", "top_workdir", "main_worktree", "spex_root",
                     "branch_management", "submit_method"):
            assert key in out, f"{key} not found in output"

    def test_get_subcommand_filters(self, capsys):
        ctx = _make_context()
        with patch("config.get_project_context", return_value=ctx):
            _run_config(["get", "branch"])
        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert len(lines) == 1
        assert "branch" in lines[0]
        assert " = main" in lines[0]

    def test_multi_variable_query(self, capsys):
        ctx = _make_context()
        with patch("config.get_project_context", return_value=ctx):
            _run_config(["branch", "cwd"])
        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert len(lines) == 2
        assert "branch" in out
        assert "cwd" in out

    def test_list_variable_format(self, capsys):
        ctx = _make_context(
            spex_tomls=[Path("/a/.spex.toml"), Path("/b/.spex.toml")],
        )
        with patch("config.get_project_context", return_value=ctx):
            _run_config(["spex_tomls"])
        out = capsys.readouterr().out
        assert "── Config Files " in out
        assert "  /a/.spex.toml" in out
        assert "  /b/.spex.toml" in out

    def test_empty_list(self, capsys):
        ctx = _make_context(spex_tomls=[])
        with patch("config.get_project_context", return_value=ctx):
            _run_config(["spex_tomls"])
        out = capsys.readouterr().out
        assert "── Config Files " in out

    def test_none_value(self, capsys):
        ctx = _make_context(top_workdir=None)
        with patch("config.get_project_context", return_value=ctx):
            _run_config(["top_workdir"])
        out = capsys.readouterr().out
        assert "top_workdir" in out
        assert out.strip().endswith("=")

    def test_unknown_variable_error(self, capsys):
        ctx = _make_context()
        with patch("config.get_project_context", return_value=ctx):
            with pytest.raises(SystemExit) as exc_info:
                _run_config(["no_such_var"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "unknown variable" in err

    def test_hyphen_to_underscore_spex_root(self, capsys):
        ctx = _make_context()
        with patch("config.get_project_context", return_value=ctx):
            _run_config(["spex-root"])
        out = capsys.readouterr().out
        assert "spex_root" in out
        assert " = " in out

    def test_hyphen_to_underscore_config_key(self, capsys):
        ctx = _make_context()
        with patch("config.get_project_context", return_value=ctx):
            _run_config(["config.main-branch-name"])
        out = capsys.readouterr().out
        assert "main_branch_name" in out
        assert " = " in out


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
