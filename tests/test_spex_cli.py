"""Tests for the spex config command."""

import importlib.util
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

_scripts_dir = Path(__file__).resolve().parent.parent / "skills" / "spex" / "scripts"
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
            "Git", "Paths", "Config", "Config Files", "Spex Roots",
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
        assert name == "Spex Roots"
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
        assert "── Spex Roots " in out

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
                        "── Config Files ", "── Spex Roots "):
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


class TestSubcommandRouting:
    """Test subcommand handler routing functions."""

    def test_run_list(self, capsys, monkeypatch):
        """_run_list imports list module and calls main."""
        called = {"argv": None}

        def fake_main(argv=None):
            called["argv"] = argv

        # Remove cached module to force reimport
        if "list" in sys.modules:
            del sys.modules["list"]
        fake_mod = type(sys)("list")
        fake_mod.main = fake_main
        sys.modules["list"] = fake_mod
        try:
            _spex_mod._run_list(["--json"])
            assert called["argv"] == ["--json"]
        finally:
            del sys.modules["list"]

    def test_run_archive(self, monkeypatch):
        """_run_archive imports archive module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("archive")
        fake_mod.main = fake_main
        sys.modules["archive"] = fake_mod
        try:
            _spex_mod._run_archive(["-n"])
            assert called["argv"] == ["-n"]
        finally:
            del sys.modules["archive"]

    def test_run_show(self, monkeypatch):
        """_run_show imports show module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("show")
        fake_mod.main = fake_main
        sys.modules["show"] = fake_mod
        try:
            _spex_mod._run_show(["-l"])
            assert called["argv"] == ["-l"]
        finally:
            del sys.modules["show"]

    def test_run_open(self, monkeypatch):
        """_run_open imports open module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("open")
        fake_mod.main = fake_main
        sys.modules["open"] = fake_mod
        try:
            _spex_mod._run_open([])
            assert called["argv"] == []
        finally:
            del sys.modules["open"]

    def test_run_prompt(self, monkeypatch):
        """_run_prompt imports prompt module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("prompt")
        fake_mod.main = fake_main
        sys.modules["prompt"] = fake_mod
        try:
            _spex_mod._run_prompt(["apply-commit", "--name", "test"])
            assert called["argv"] == ["apply-commit", "--name", "test"]
        finally:
            del sys.modules["prompt"]

    def test_run_meta_helper(self, monkeypatch):
        """_run_meta_helper imports meta_helper module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("meta_helper")
        fake_mod.main = fake_main
        sys.modules["meta_helper"] = fake_mod
        try:
            _spex_mod._run_meta_helper(["test-spec", "branch"])
            assert called["argv"] == ["test-spec", "branch"]
        finally:
            del sys.modules["meta_helper"]

    def test_run_create_helper(self, monkeypatch):
        """_run_create_helper imports create_helper module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("create_helper")
        fake_mod.main = fake_main
        sys.modules["create_helper"] = fake_mod
        try:
            _spex_mod._run_create_helper(["precheck"])
            assert called["argv"] == ["precheck"]
        finally:
            del sys.modules["create_helper"]

    def test_run_apply_helper(self, monkeypatch):
        """_run_apply_helper imports apply_helper module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("apply_helper")
        fake_mod.main = fake_main
        sys.modules["apply_helper"] = fake_mod
        try:
            _spex_mod._run_apply_helper(["post-action", "--name", "test"])
            assert called["argv"] == ["post-action", "--name", "test"]
        finally:
            del sys.modules["apply_helper"]

    def test_run_todo_helper(self, monkeypatch):
        """_run_todo_helper imports todo_helper module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("todo_helper")
        fake_mod.main = fake_main
        sys.modules["todo_helper"] = fake_mod
        try:
            _spex_mod._run_todo_helper(["validate"])
            assert called["argv"] == ["validate"]
        finally:
            del sys.modules["todo_helper"]

    def test_run_review_helper(self, monkeypatch):
        """_run_review_helper imports review_helper module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("review_helper")
        fake_mod.main = fake_main
        sys.modules["review_helper"] = fake_mod
        try:
            _spex_mod._run_review_helper(["status", "--step", "step-1"])
            assert called["argv"] == ["status", "--step", "step-1"]
        finally:
            del sys.modules["review_helper"]

    def test_run_init(self, monkeypatch):
        """_run_init imports init module and calls main."""
        called = {"argv": None}
        def fake_main(argv=None):
            called["argv"] = argv
        fake_mod = type(sys)("init")
        fake_mod.main = fake_main
        sys.modules["init"] = fake_mod
        try:
            _spex_mod._run_init([])
            assert called["argv"] == []
        finally:
            del sys.modules["init"]


class TestGetVersion:
    """Test _get_version function (lines 347-360)."""

    def test_returns_version_from_skill_md(self):
        """_get_version returns version from SKILL.md front-matter."""
        ver = _spex_mod._get_version()
        assert ver is not None
        assert ver != "unknown"

    def test_returns_unknown_when_missing(self, monkeypatch, tmp_path):
        """_get_version returns 'unknown' when SKILL.md doesn't exist."""
        monkeypatch.setattr(_spex_mod, "_skill_dir", tmp_path)
        assert _spex_mod._get_version() == "unknown"

    def test_returns_unknown_no_front_matter(self, monkeypatch, tmp_path):
        """_get_version returns 'unknown' when no front-matter."""
        (tmp_path / "SKILL.md").write_text("# No front matter\n")
        monkeypatch.setattr(_spex_mod, "_skill_dir", tmp_path)
        assert _spex_mod._get_version() == "unknown"

    def test_returns_unknown_no_version_field(self, monkeypatch, tmp_path):
        """_get_version returns 'unknown' when no version field."""
        (tmp_path / "SKILL.md").write_text("---\ntitle: Test\n---\n")
        monkeypatch.setattr(_spex_mod, "_skill_dir", tmp_path)
        assert _spex_mod._get_version() == "unknown"

    def test_strips_quotes(self, monkeypatch, tmp_path):
        """_get_version strips quotes from version value."""
        (tmp_path / "SKILL.md").write_text('---\nversion: "1.0.0"\n---\n')
        monkeypatch.setattr(_spex_mod, "_skill_dir", tmp_path)
        assert _spex_mod._get_version() == "1.0.0"


class TestRunVersion:
    """Test _run_version function (lines 412-419)."""

    def test_no_argv_prints_version(self, capsys, monkeypatch):
        """_run_version with no argv prints 'spex <version>'."""
        monkeypatch.setattr(_spex_mod, "_get_version", lambda: "1.2.3")
        _spex_mod._run_version([])
        assert capsys.readouterr().out.strip() == "spex 1.2.3"

    def test_with_argv_delegates_to_version_main(self, capsys, monkeypatch):
        """_run_version with argv delegates to version.main."""
        _spex_mod._run_version([])
        out = capsys.readouterr().out
        assert out.startswith("spex ")


class TestLlmErrorHandlers:
    """Test LLM-only command error handlers (lines 422-431)."""

    def test_apply_error_message(self, capsys):
        """_make_llm_error_handler('apply') prints correct message."""
        handler = _spex_mod._make_llm_error_handler("apply")
        with pytest.raises(SystemExit) as exc_info:
            handler()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "'spex apply' requires an AI coding agent" in err

    def test_create_error_message(self, capsys):
        """_make_llm_error_handler('create') prints correct message."""
        handler = _spex_mod._make_llm_error_handler("create")
        with pytest.raises(SystemExit) as exc_info:
            handler()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "'spex create' requires an AI coding agent" in err

    def test_modify_error_message(self, capsys):
        """_make_llm_error_handler('modify') prints correct message."""
        handler = _spex_mod._make_llm_error_handler("modify")
        with pytest.raises(SystemExit) as exc_info:
            handler()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "'spex modify' requires an AI coding agent" in err


class TestMainEntrypoint:
    """Test main() entry point (lines 513-542)."""

    def test_no_args_prints_help(self, capsys):
        """main() with no args prints help to stderr and exits 0."""
        with pytest.raises(SystemExit) as exc_info:
            _spex_mod.main([])
        assert exc_info.value.code == 0
        err = capsys.readouterr().err
        assert "spex <command>" in err

    def test_unknown_command_exits_1(self, capsys):
        """main() with unknown command exits 1."""
        with pytest.raises(SystemExit) as exc_info:
            _spex_mod.main(["unknown-cmd"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Unknown command: unknown-cmd" in err

    def test_underscore_to_hyphen_normalization(self, monkeypatch):
        """main() normalizes underscores to hyphens in subcommand."""
        called = {"called": False}
        def fake_main(argv=None):
            called["called"] = True
        fake_mod = type(sys)("list")
        fake_mod.main = fake_main
        sys.modules["list"] = fake_mod
        try:
            _spex_mod.main(["list"])  # 'list' not 'todo_helper'
            assert called["called"]
        finally:
            del sys.modules["list"]

    def test_debug_flag(self, monkeypatch, caplog):
        """main() with --debug enables verbose logging."""
        logged = []
        def fake_setup(verbose=False):
            logged.append(verbose)
        monkeypatch.setattr("common.setup_logging", fake_setup)
        _spex_mod.main(["--debug", "version"])
        assert logged == [True]

    def test_short_debug_flag(self, monkeypatch):
        """main() with -d enables verbose logging."""
        called = {"v": False}
        def fake_setup(verbose=False):
            called["v"] = verbose
        monkeypatch.setattr("common.setup_logging", fake_setup)
        _spex_mod.main(["-d", "version"])
        assert called["v"] is True


class TestConfigColorPaths:
    """Test color formatting in _print_config_sections (lines 210, 217, 232, 242)."""

    def test_kv_color_when_tty(self, capsys, monkeypatch):
        """KV entries use cyan color when stdout is a TTY."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        sections = [("Git", "kv", [("branch", "main")])]
        _print_config_sections(sections)
        out = capsys.readouterr().out
        assert "\033[2;36m" in out
        assert "\033[0m" in out

    def test_list_header_color_when_tty(self, capsys, monkeypatch):
        """List section headers use bold when stdout is a TTY."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        sections = [("Config Files", "list", ["/a/.spex.toml"])]
        _print_config_sections(sections)
        out = capsys.readouterr().out
        assert "\033[1m" in out
        assert "\033[0m" in out

    def test_requested_kv_color_when_tty(self, capsys, monkeypatch):
        """Requested KV entries use color when stdout is a TTY."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        sections = [("Git", "kv", [("branch", "main")])]
        _print_config_sections(sections, ["branch"])
        out = capsys.readouterr().out
        assert "\033[2;36m" in out

    def test_requested_list_color_when_tty(self, capsys, monkeypatch):
        """Requested list section headers use color when stdout is a TTY."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        sections = [("Config Files", "list", ["/a/.spex.toml"])]
        _print_config_sections(sections, ["spex_tomls"])
        out = capsys.readouterr().out
        assert "\033[1m" in out


class TestRunConfigWithNoneArgv:
    """Test _run_config with argv=None (line 255)."""

    def test_none_argv_defaults_to_empty_list(self, capsys, monkeypatch):
        """_run_config with None argv defaults to empty list (shows all)."""
        ctx = _make_context()
        with patch("config.get_project_context", return_value=ctx):
            _run_config(None)
        out = capsys.readouterr().out
        assert "── Git " in out


class TestDirectScriptExecution:
    """Test if __name__ == '__main__' path (line 546)."""

    def test_direct_script_no_args(self):
        """Running spex directly with no args exits 0."""
        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_direct_script_version_flag(self):
        """Running spex directly with --version shows version."""
        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "spex" in result.stdout

    def test_direct_script_unknown_command(self):
        """Running spex directly with unknown cmd exits 1."""
        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "nonexistent"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "Unknown command: nonexistent" in result.stderr

    def test_direct_script_version_command(self):
        """Running spex directly with 'version' shows version."""
        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert result.stdout.startswith("spex ")


class TestRunHook:
    """Test _run_hook function (lines 385-409)."""

    def test_hook_missing_event_type(self, capsys, caplog):
        """_run_hook exits 1 when --event-type is missing."""
        with caplog.at_level(0):
            with pytest.raises(SystemExit) as exc_info:
                _spex_mod._run_hook(["my-hook"])
        assert exc_info.value.code == 1
        assert "--event-type is required" in caplog.text

    def test_hook_builds_event_data(self, monkeypatch, caplog):
        """_run_hook calls run_hook with event data."""
        built = {}
        run_called = {}
        def fake_build(event_type, payload, workdir):
            built["data"] = {"type": event_type, "payload": payload}
            return built["data"]
        def fake_run(hook_name, event_data, workdir):
            run_called["name"] = hook_name
            run_called["data"] = event_data
        monkeypatch.setattr("hooks._build_event_data", fake_build)
        monkeypatch.setattr("hooks.run_hook", fake_run)
        _spex_mod._run_hook([
            "my-hook", "--event-type", "spec.created",
            "--name", "test-spec",
            "--json-payload", '{"key": "val"}',
        ])
        assert run_called["name"] == "my-hook"
        assert run_called["data"]["type"] == "spec.created"
        assert run_called["data"]["payload"]["spec_name"] == "test-spec"
        assert run_called["data"]["payload"]["key"] == "val"

    def test_hook_without_name_in_payload(self, monkeypatch):
        """_run_hook works without --name (no spec_name added)."""
        def fake_build(event_type, payload, workdir):
            return {"type": event_type, "payload": payload}
        run_called = {}
        def fake_run(hook_name, event_data, workdir):
            run_called["data"] = event_data
        monkeypatch.setattr("hooks._build_event_data", fake_build)
        monkeypatch.setattr("hooks.run_hook", fake_run)
        _spex_mod._run_hook([
            "my-hook", "--event-type", "test",
            "--json-payload", '{"x": 1}',
        ])
        assert "spec_name" not in run_called["data"]["payload"]


class TestMergeRouting:
    """Test _run_merge and _run_submit functions."""

    def test_merge_with_name(self, monkeypatch):
        """_run_merge passes name and command to merge.cli_submit."""
        called = {}
        fake_mod = type(sys)("merge")
        def fake_cli_submit(args, **kwargs):
            called["args"] = args
            called["kwargs"] = kwargs
        fake_mod.cli_submit = fake_cli_submit
        sys.modules["merge"] = fake_mod
        try:
            _spex_mod._run_merge(["test-spec"])
            assert "test-spec" in called["args"]
            assert called["kwargs"].get("command") == "merge"
        finally:
            del sys.modules["merge"]

    def test_merge_with_dry_run(self, monkeypatch):
        """_run_merge passes --dry-run to merge.cli_submit."""
        called = {}
        fake_mod = type(sys)("merge")
        def fake_cli_submit(args, **kwargs):
            called["args"] = args
            called["kwargs"] = kwargs
        fake_mod.cli_submit = fake_cli_submit
        sys.modules["merge"] = fake_mod
        try:
            _spex_mod._run_merge(["test-spec", "--dry-run"])
            assert "--dry-run" in called["args"]
        finally:
            del sys.modules["merge"]

    def test_merge_with_no_archive(self, monkeypatch):
        """_run_merge passes --no-archive to merge.cli_submit."""
        called = {}
        fake_mod = type(sys)("merge")
        def fake_cli_submit(args, **kwargs):
            called["args"] = args
            called["kwargs"] = kwargs
        fake_mod.cli_submit = fake_cli_submit
        sys.modules["merge"] = fake_mod
        try:
            _spex_mod._run_merge(["test-spec", "--no-archive"])
            assert "--no-archive" in called["args"]
        finally:
            del sys.modules["merge"]

    def test_merge_with_no_args(self, monkeypatch):
        """_run_merge with no name passes empty args."""
        called = {}
        fake_mod = type(sys)("merge")
        def fake_cli_submit(args, **kwargs):
            called["args"] = args
        fake_mod.cli_submit = fake_cli_submit
        sys.modules["merge"] = fake_mod
        try:
            _spex_mod._run_merge([])
            assert called["args"] == []
        finally:
            del sys.modules["merge"]

    def test_submit_uses_submit_command(self, monkeypatch):
        """_run_submit passes command='submit' to merge.cli_submit."""
        called = {}
        fake_mod = type(sys)("merge")
        def fake_cli_submit(args, **kwargs):
            called["args"] = args
            called["kwargs"] = kwargs
        fake_mod.cli_submit = fake_cli_submit
        sys.modules["merge"] = fake_mod
        try:
            _spex_mod._run_submit(["test-spec"])
            assert "test-spec" in called["args"]
            assert called["kwargs"].get("command") == "submit"
        finally:
            del sys.modules["merge"]


class TestDebugTracingIntegration:
    """Integration tests for debug tracing wired into CLI main()."""

    def _setup_repo(self, tmp_path, *, debug: Optional[bool] = None):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        lines = ['[spex]', 'spex_root = ".spex"']
        # Always set debug explicitly so a developer ~/.spex.toml with
        # debug=true cannot leak into subprocess integration tests.
        if debug is True:
            lines.append("debug = true")
        else:
            lines.append("debug = false")
        (tmp_path / ".spex.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (tmp_path / ".spex").mkdir()

    def test_debug_config_writes_spex_root_log(self, tmp_path):
        """debug=true appends a trace block to <spex_root>/debug.log."""
        self._setup_repo(tmp_path, debug=True)
        log_path = tmp_path / ".spex" / "debug.log"

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "version"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0
        assert log_path.is_file()
        content = log_path.read_text(encoding="utf-8")
        assert "===== BEGIN " in content
        assert "argv: spex version" in content
        assert "===== END exit=0 duration_ms=" in content

    def test_debug_cli_flag_writes_spex_root_log(self, tmp_path):
        """-d/--debug appends a trace block to <spex_root>/debug.log."""
        self._setup_repo(tmp_path)
        log_path = tmp_path / ".spex" / "debug.log"

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "-d", "version"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0
        assert log_path.is_file()
        content = log_path.read_text(encoding="utf-8")
        assert "===== BEGIN " in content
        assert "argv: spex -d version" in content
        assert "===== END exit=0 duration_ms=" in content

    def test_debug_off_by_default_writes_nothing(self, tmp_path):
        """Without debug flag or config, no debug.log is created."""
        self._setup_repo(tmp_path)

        result = subprocess.run(
            [sys.executable, SPEX_SCRIPT, "version"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0
        assert not (tmp_path / ".spex" / "debug.log").exists()


class TestAllCommandsRegistered:
    """Verify all commands are registered and routable."""

    def test_llm_commands_use_error_handler(self, capsys):
        """LLM commands route to error handler, not real implementation."""
        for cmd in ["apply", "create", "modify", "new"]:
            with pytest.raises(SystemExit) as exc_info:
                _spex_mod.main([cmd])
            assert exc_info.value.code == 1
            err = capsys.readouterr().err
            assert f"'spex {cmd}' requires an AI coding agent" in err

    def test_internal_commands_exist(self):
        """Internal commands are registered in _INTERNAL_COMMANDS."""
        names = {n for n, _ in _spex_mod._INTERNAL_COMMANDS}
        assert "version" in names
        assert "prompt" in names
        assert "meta-helper" in names
        assert "todo-helper" in names
        assert "review-helper" in names
        assert "run-hook" in names
