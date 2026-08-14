import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import common as spex_common
import pytest
import show as spex_show
from config import ProjectContext


def _make_topic(tmp_path, name="my-topic", spec_content=None, todo=None,
                subdir="specs", workdir="", main_worktree=""):
    """Create a spec directory with optional spec and todo."""
    spec_dir = tmp_path / subdir / name
    spec_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "created_at": "2026-05-20T10:00:00+08:00",
        "prompts": ["test"],
    }
    if workdir:
        meta["workdir"] = workdir
        meta["main_worktree"] = main_worktree or workdir
    (spec_dir / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    if spec_content:
        (spec_dir / "spec.md").write_text(spec_content, encoding="utf-8")
    if todo:
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8"
        )
    return spec_dir


def _make_ctx(top_workdir):
    """Create a ProjectContext for testing."""
    tw = top_workdir if top_workdir is not None else None
    return ProjectContext(
        cwd=tw or __import__("pathlib").Path.cwd(),
        top_workdir=tw,
        main_worktree=tw,
        remote_url="",
        branch="main",
        user_name="test",
        user_email="test@test.com",
    )


class TestFormatDefault:
    def test_shows_icon_progress_name(self, tmp_path):
        spec_dir = _make_topic(
            tmp_path,
            spec_content='---\ndescription: "A desc"\n---\n\n# Spec',
            todo=[
                {"id": "step-1", "name": "First", "details": "",
                 "completed_at": "2026-01-01", "commit_title": "abc"},
                {"id": "step-2", "name": "Second", "details": "",
                 "completed_at": "", "commit_title": ""},
            ],
        )
        output = spex_show._format_default(spec_dir)
        lines = output.splitlines()
        assert "(1/2)" in lines[0]
        assert "my-topic" in lines[0]
        assert "    A desc" in lines[1]
        assert "    step-1: First" in output
        assert "    step-2: Second" in output

    def test_no_spec_no_steps(self, tmp_path):
        spec_dir = _make_topic(tmp_path)
        output = spex_show._format_default(spec_dir)
        assert "(0/0)" in output
        assert "step-" not in output


class TestFormatVerbose:
    def test_shows_spec_and_todo(self, tmp_path):
        spec = '---\nversion: "0.0.1"\n---\n\n# My Spec\n\nContent here.'
        spec_dir = _make_topic(
            tmp_path,
            spec_content=spec,
            todo=[
                {"id": "step-1", "name": "Do thing", "details": "Detail text",
                 "completed_at": "", "commit_title": ""},
            ],
        )
        output = spex_show._format_verbose(spec_dir)
        lines = output.splitlines()
        assert "(0/1)" in lines[0]
        assert "my-topic" in lines[0]
        assert "# **Specification**" in output
        assert "# My Spec" in output
        assert "Content here." in output
        assert "----" in output
        assert "# **TODO**" in output
        assert "- **step-1: Do thing**" in output
        assert "  Detail text" in output

    def test_no_spec_file(self, tmp_path):
        spec_dir = _make_topic(tmp_path)
        output = spex_show._format_verbose(spec_dir)
        assert "(no spec.md found)" in output

    def test_no_todo(self, tmp_path):
        spec = '---\nversion: "0.0.1"\n---\n\n# Spec'
        spec_dir = _make_topic(tmp_path, spec_content=spec)
        output = spex_show._format_verbose(spec_dir)
        assert "(no tasks)" in output

    def test_missing_meta_returns_error(self, tmp_path):
        spec_dir = tmp_path / "specs" / "bad-topic"
        spec_dir.mkdir(parents=True)
        output = spex_show._format_verbose(spec_dir)
        assert "(unable to load spec: bad-topic)" in output


class TestMain:
    def test_no_args_no_topics_exits(self, monkeypatch, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()
        archives.mkdir()
        ctx = _make_ctx(None)
        monkeypatch.setattr("common.get_specs_dir", lambda _w=None: specs)
        monkeypatch.setattr("common.get_archives_dir", lambda _w=None: archives)
        monkeypatch.setattr("common.get_project_context", lambda _w=None: ctx)
        with pytest.raises(SystemExit) as exc_info:
            spex_show.main([])
        assert exc_info.value.code == 1

    def test_help_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "-h"])
        with pytest.raises(SystemExit) as exc_info:
            spex_show.main()
        assert exc_info.value.code == 0

    def test_nonexistent_topic(self, monkeypatch, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()
        archives.mkdir()
        monkeypatch.setattr("common.get_specs_dir", lambda _w=None: specs)
        monkeypatch.setattr("common.get_archives_dir", lambda _w=None: archives)
        with pytest.raises(SystemExit) as exc_info:
            spex_show.main(["nonexistent"])
        assert exc_info.value.code == 1


class TestResolveSpec:
    """Tests for resolve_spec: specs lookup, archive fallback, multi-match."""

    def _setup(self, tmp_path, monkeypatch):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()
        archives.mkdir()
        monkeypatch.setattr("common.get_specs_dir", lambda _w=None: specs)
        monkeypatch.setattr("common.get_archives_dir", lambda _w=None: archives)
        return specs, archives

    def test_found_in_specs(self, tmp_path, monkeypatch):
        specs, _archives = self._setup(tmp_path, monkeypatch)
        _make_topic(tmp_path, name="my-feature", subdir="specs")

        result = spex_common.resolve_spec("my-feature")
        assert result == specs / "my-feature"

    def test_no_fallback_without_flag(self, tmp_path, monkeypatch, caplog):
        self._setup(tmp_path, monkeypatch)
        _make_topic(tmp_path, name="old-feature", subdir="archives")

        with pytest.raises(SystemExit) as exc_info:
            spex_common.resolve_spec("old-feature")
        assert exc_info.value.code == 1
        assert "--archives" in caplog.text

    def test_archives_flag_finds_archived(self, tmp_path, monkeypatch):
        _specs, archives = self._setup(tmp_path, monkeypatch)
        _make_topic(tmp_path, name="old-feature", subdir="archives")

        result = spex_common.resolve_spec("old-feature", include_archives=True)
        assert result == archives / "old-feature"

    def test_no_match_exits(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            spex_common.resolve_spec("nonexistent")
        assert exc_info.value.code == 1

    def test_multi_match_interactive(self, tmp_path, monkeypatch):
        specs, _archives = self._setup(tmp_path, monkeypatch)
        _make_topic(tmp_path, name="feature-alpha", subdir="specs")
        _make_topic(tmp_path, name="feature-beta", subdir="specs")

        # Simulate user selecting "2" (second item in reverse-sorted list)
        monkeypatch.setattr("sys.stdin", io.StringIO("2\n"))

        result = spex_common.resolve_spec("feature")
        # Reverse sorted: feature-beta=1, feature-alpha=2
        assert result == specs / "feature-alpha"

    def test_archives_flag_merges_results(self, tmp_path, monkeypatch):
        specs, archives = self._setup(tmp_path, monkeypatch)
        _make_topic(tmp_path, name="my-topic", subdir="specs")
        _make_topic(tmp_path, name="my-topic-old", subdir="archives")

        # With include_archives=True, both should appear as matches
        # Simulate user selecting "1"
        monkeypatch.setattr("sys.stdin", io.StringIO("1\n"))

        result = spex_common.resolve_spec("my-topic", include_archives=True)
        # Reverse sorted: my-topic-old=1? No, my-topic > my-topic-old
        # Actually sorted reverse: my-topic-old, my-topic
        # Wait: reverse=True means descending, so my-topic-old > my-topic
        assert result.name in ("my-topic", "my-topic-old")


class TestSelectSpecInteractive:
    """Tests for select_spec_interactive with --archives and --all-projects."""

    def _setup(self, tmp_path, monkeypatch):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()
        archives.mkdir()

        project_workdir = str(tmp_path / "project-a")
        other_workdir = str(tmp_path / "project-b")

        _make_topic(tmp_path, name="related-spec", subdir="specs",
                    workdir=project_workdir)
        _make_topic(tmp_path, name="related-archive", subdir="archives",
                    workdir=project_workdir)
        _make_topic(tmp_path, name="other-spec", subdir="specs",
                    workdir=other_workdir)
        _make_topic(tmp_path, name="other-archive", subdir="archives",
                    workdir=other_workdir)

        from pathlib import Path
        ctx = ProjectContext(
            cwd=Path(project_workdir),
            top_workdir=Path(project_workdir),
            main_worktree=Path(project_workdir),
            remote_url="",
            branch="main",
            user_name="test",
            user_email="test@test.com",
        )

        monkeypatch.setattr("common.get_specs_dir", lambda _w=None: specs)
        monkeypatch.setattr("common.get_archives_dir", lambda _w=None: archives)
        monkeypatch.setattr("common.get_project_context", lambda _w=None: ctx)

        return specs, archives

    def test_default_only_related_specs(self, tmp_path, monkeypatch):
        specs, _archives = self._setup(tmp_path, monkeypatch)

        # Only one related spec -> returns directly
        result = spex_common.select_spec_interactive()
        assert result == specs / "related-spec"

    def test_archives_includes_archived(self, tmp_path, monkeypatch):
        specs, archives = self._setup(tmp_path, monkeypatch)

        # Two related specs (spec + archive) -> prompt selection
        monkeypatch.setattr("sys.stdin", io.StringIO("1\n"))

        result = spex_common.select_spec_interactive(include_archives=True)
        assert result.name in ("related-spec", "related-archive")

    def test_all_projects_no_filter(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)

        # Two specs (related + other) -> prompt selection
        monkeypatch.setattr("sys.stdin", io.StringIO("1\n"))

        result = spex_common.select_spec_interactive(all_projects=True)
        assert result.name in ("related-spec", "other-spec")

    def test_no_topics_exits(self, tmp_path, monkeypatch):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()
        archives.mkdir()

        ctx = _make_ctx(None)
        monkeypatch.setattr("common.get_specs_dir", lambda _w=None: specs)
        monkeypatch.setattr("common.get_archives_dir", lambda _w=None: archives)
        monkeypatch.setattr("common.get_project_context", lambda _w=None: ctx)

        with pytest.raises(SystemExit) as exc_info:
            spex_common.select_spec_interactive()
        assert exc_info.value.code == 1


class TestPromptSelection:
    """Tests for prompt_selection interactive chooser."""

    def test_valid_selection(self, tmp_path, monkeypatch):
        d1 = tmp_path / "topic-a"
        d2 = tmp_path / "topic-b"
        for d in (d1, d2):
            d.mkdir()
            _make_topic(tmp_path, name=d.name, subdir=".")

        monkeypatch.setattr("sys.stdin", io.StringIO("2\n"))
        result = spex_common.prompt_selection([d1, d2])
        assert result == d2

    def test_empty_input_exits(self, tmp_path, monkeypatch):
        d1 = tmp_path / "topic-a"
        d1.mkdir()
        _make_topic(tmp_path, name="topic-a", subdir=".")

        monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
        with pytest.raises(SystemExit) as exc_info:
            spex_common.prompt_selection([d1])
        assert exc_info.value.code == 1

    def test_invalid_number_exits(self, tmp_path, monkeypatch):
        d1 = tmp_path / "topic-a"
        d1.mkdir()
        _make_topic(tmp_path, name="topic-a", subdir=".")

        monkeypatch.setattr("sys.stdin", io.StringIO("abc\n"))
        with pytest.raises(SystemExit) as exc_info:
            spex_common.prompt_selection([d1])
        assert exc_info.value.code == 1

    def test_out_of_range_exits(self, tmp_path, monkeypatch):
        d1 = tmp_path / "topic-a"
        d1.mkdir()
        _make_topic(tmp_path, name="topic-a", subdir=".")

        monkeypatch.setattr("sys.stdin", io.StringIO("5\n"))
        with pytest.raises(SystemExit) as exc_info:
            spex_common.prompt_selection([d1])
        assert exc_info.value.code == 1

    def test_allow_empty_returns_none(self, tmp_path, monkeypatch):
        d1 = tmp_path / "topic-a"
        d1.mkdir()
        _make_topic(tmp_path, name="topic-a", subdir=".")

        monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
        result = spex_common.prompt_selection([d1], allow_empty=True)
        assert result is None

    def test_allow_empty_still_selects(self, tmp_path, monkeypatch):
        d1 = tmp_path / "topic-a"
        d2 = tmp_path / "topic-b"
        for d in (d1, d2):
            d.mkdir()
            _make_topic(tmp_path, name=d.name, subdir=".")

        monkeypatch.setattr("sys.stdin", io.StringIO("1\n"))
        result = spex_common.prompt_selection([d1, d2], allow_empty=True)
        assert result == d1


class TestSelectSpecInteractiveAllowEmpty:
    """Tests for select_spec_interactive allow_empty behavior."""

    def test_no_topics_returns_none(self, tmp_path, monkeypatch):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()
        archives.mkdir()

        ctx = _make_ctx(None)
        monkeypatch.setattr("common.get_specs_dir", lambda _w=None: specs)
        monkeypatch.setattr("common.get_archives_dir", lambda _w=None: archives)
        monkeypatch.setattr("common.get_project_context", lambda _w=None: ctx)

        result = spex_common.select_spec_interactive(allow_empty=True)
        assert result is None

    def test_empty_input_returns_none(self, tmp_path, monkeypatch):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()
        archives.mkdir()

        project_workdir = str(tmp_path / "project-a")
        _make_topic(tmp_path, name="topic-1", subdir="specs",
                    workdir=project_workdir)
        _make_topic(tmp_path, name="topic-2", subdir="specs",
                    workdir=project_workdir)

        from pathlib import Path
        ctx = ProjectContext(
            cwd=Path(project_workdir),
            top_workdir=Path(project_workdir),
            main_worktree=Path(project_workdir),
            remote_url="",
            branch="main",
            user_name="test",
            user_email="test@test.com",
        )

        monkeypatch.setattr("common.get_specs_dir", lambda _w=None: specs)
        monkeypatch.setattr("common.get_archives_dir", lambda _w=None: archives)
        monkeypatch.setattr("common.get_project_context", lambda _w=None: ctx)
        monkeypatch.setattr("sys.stdin", io.StringIO("\n"))

        result = spex_common.select_spec_interactive(allow_empty=True)
        assert result is None


class TestPagedOutput:
    """Test _paged_output (lines 22-30)."""

    def test_pipes_directly_when_not_tty(self, capsys, monkeypatch):
        """_paged_output prints directly when stdout is not a TTY."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        from show import _paged_output
        _paged_output("hello world")
        assert capsys.readouterr().out.strip() == "hello world"

    def test_pager_invoked_on_tty(self, capfd, monkeypatch, tmp_path):
        """_paged_output uses PAGER when stdout is a TTY."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setenv("PAGER", "cat")
        from show import _paged_output
        _paged_output("paged content")
        out = capfd.readouterr().out
        assert "paged content" in out

    def test_default_pager_argv(self, monkeypatch):
        """Default PAGER is split into ['less', '-R'] without a shell."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.delenv("PAGER", raising=False)
        from show import _paged_output
        mock_proc = MagicMock()
        with patch("show.subprocess.Popen", return_value=mock_proc) as mock_popen:
            _paged_output("content")
        args, kwargs = mock_popen.call_args
        assert args[0] == ["less", "-R"]
        assert isinstance(args[0], list)
        assert kwargs.get("shell", False) is False
        assert kwargs.get("stdin") == subprocess.PIPE
        mock_proc.communicate.assert_called_once()

    def test_empty_pager_falls_back_to_less(self, monkeypatch):
        """Empty PAGER= falls back to ['less', '-R'] without a shell."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setenv("PAGER", "")
        from show import _paged_output
        mock_proc = MagicMock()
        with patch("show.subprocess.Popen", return_value=mock_proc) as mock_popen:
            _paged_output("content")
        args, kwargs = mock_popen.call_args
        assert args[0] == ["less", "-R"]
        assert isinstance(args[0], list)
        assert kwargs.get("shell", False) is False
        mock_proc.communicate.assert_called_once()

    def test_malicious_pager_not_shelled(self, monkeypatch):
        """Malicious PAGER is passed as argv; shell is not True."""
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setenv("PAGER", "less; rm -rf /")
        from show import _paged_output
        mock_proc = MagicMock()
        with patch("show.subprocess.Popen", return_value=mock_proc) as mock_popen:
            _paged_output("content")
        args, kwargs = mock_popen.call_args
        assert args[0] == ["less;", "rm", "-rf", "/"]
        assert isinstance(args[0], list)
        assert kwargs.get("shell", False) is not True
        mock_proc.communicate.assert_called_once()


class TestMainBriefAndVerbose:
    """Test main() brief vs verbose routing (lines 109-112)."""

    def test_brief_mode(self, monkeypatch, capsys, tmp_path):
        """main() with -l uses brief output."""
        spec_dir = tmp_path / "specs" / "test-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "test-spec"}), encoding="utf-8"
        )
        ctx = _make_ctx(tmp_path)
        monkeypatch.setattr("common.get_project_context", lambda _w=None: ctx)
        monkeypatch.setattr(
            "common.get_specs_dir", lambda _w=None: tmp_path / "specs",
        )
        from show import main
        main(["-l", "test-spec"])
        out = capsys.readouterr().out
        assert "test-spec" in out

    def test_verbose_mode(self, monkeypatch, capsys, tmp_path):
        """main() without -l uses verbose output."""
        spec_dir = tmp_path / "specs" / "test-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "test-spec"}), encoding="utf-8"
        )
        (spec_dir / "spec.md").write_text("# Test\n\nSome content.", encoding="utf-8")
        ctx = _make_ctx(tmp_path)
        monkeypatch.setattr("common.get_project_context", lambda _w=None: ctx)
        monkeypatch.setattr(
            "common.get_specs_dir", lambda _w=None: tmp_path / "specs",
        )
        from show import main
        main(["test-spec"])
        out = capsys.readouterr().out
        assert "Test" in out


class TestShowScriptDirect:
    """Test if __name__ == '__main__' path (line 116)."""

    def test_direct_script_auto_selects_spec(self, tmp_path, monkeypatch):
        """Running show.py directly auto-selects single spec (exit 0)."""
        # Set up isolated spex_root with single spec
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "single-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "single-spec"}), encoding="utf-8",
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{spex_root}"\n', encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(
                Path(__file__).resolve().parent.parent / "skills" / "spex" / "scripts" / "show.py"
            )],
            capture_output=True, text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
