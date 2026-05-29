import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import (
    _resolve_template_roots,
    check_help_flag,
    clear_spex_root_cache,
    format_topic,
    get_archives_dir,
    get_spec_description,
    get_specs_dir,
    get_spex_root,
    get_spex_roots,
    get_spex_tomls,
    get_template,
    local_iso_timestamp,
    parse_front_matter_description,
    resolve_topic_dir,
)


def _init_git_repo(path):
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_spex_root_cache()
    yield


def test_default_uses_cwd(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")
    monkeypatch.chdir(repo)

    result = get_spex_root()
    assert result == str(repo / ".spex")


def test_custom_workdir(tmp_path):
    repo = tmp_path / "project-x"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

    result = get_spex_root(str(repo))
    assert result == str(repo / ".spex")


def test_subdirectory_resolves_to_repo_root(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")
    subdir = repo / "src" / "lib"
    subdir.mkdir(parents=True)

    result = get_spex_root(str(subdir))
    assert result == str(repo / ".spex")


def test_not_a_git_repo(monkeypatch, tmp_path):
    workdir = tmp_path / "no-repo"
    workdir.mkdir()
    (workdir / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")
    monkeypatch.chdir(workdir)

    result = get_spex_root(str(workdir))
    assert result == str((workdir / ".spex").resolve())


def test_require_git_raises_outside_repo(monkeypatch, tmp_path):
    workdir = tmp_path / "no-repo"
    workdir.mkdir()
    (workdir / ".spex.toml").write_text(
        '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="Not inside a git repository"):
        get_spex_root(str(workdir), require_git=True)


def test_require_git_ok_inside_repo(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "my-specs"
    (repo / ".spex.toml").write_text(
        f'[spex]\nspex_root = "{custom_path}"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo), require_git=True)
    assert result == str(custom_path.resolve())


def test_naming_convention(tmp_path):
    repo = tmp_path / "hello-world"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

    result = get_spex_root(str(repo))
    spec_path = Path(result)

    assert spec_path.parent == repo
    assert spec_path.name == ".spex"


def test_specs_dir(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

    result = get_specs_dir(str(repo))
    assert result == str(repo / ".spex" / "specs")


def test_archives_dir(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

    result = get_archives_dir(str(repo))
    assert result == str(repo / ".spex" / "archives")


def test_local_iso_timestamp_format():
    ts = local_iso_timestamp()
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"
    assert re.match(pattern, ts), f"Unexpected format: {ts}"


def test_toml_relative_path_in_repo(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text(
        '[spex]\nspex_root = "shared/specs"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo))
    assert result == str(repo / "shared" / "specs")


def test_repo_toml_takes_priority(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "from-repo-yaml"
    # Write repo-level .spex.toml
    (repo / ".spex.toml").write_text(
        f'[spex]\nspex_root = "{custom_path}"\n', encoding="utf-8"
    )
    # Write home-level ~/.spex.toml (should be lower priority)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".spex.toml").write_text(
        '[spex]\nspex_root = "/should/not/use"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo))
    assert result == str(custom_path.resolve())


def test_default_fallback_when_no_config(monkeypatch, tmp_path):
    fakehome = tmp_path / "fakehome"
    fakehome.mkdir()
    monkeypatch.setattr("config.Path.home", lambda: fakehome)
    monkeypatch.setattr("common.Path.home", lambda: fakehome)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_spex_root(str(repo))
    assert result == str((fakehome / ".spex").resolve())
    assert (fakehome / ".spex.toml").exists()


def test_default_creates_specs_dir(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

    specs_dir = repo / ".spex"
    assert not specs_dir.exists()

    get_spex_root(str(repo))
    assert specs_dir.is_dir()


def test_default_creates_internal_gitignore(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

    get_spex_root(str(repo))

    spex_dir = repo / ".spex"
    gitignore = spex_dir / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert "/specs/" in content
    assert "/archives/" in content


def test_xdg_config_fallback(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "from-user"
    # No repo-level .spex.toml; use ~/.spex.toml as fallback
    (tmp_path / ".spex.toml").write_text(
        f'[spex]\nspex_root = "{custom_path}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = get_spex_root(str(repo))
    assert result == str(custom_path.resolve())


def test_home_toml_fallback(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "from-home"
    # No repo-level config; use ~/.spex.toml as fallback
    (tmp_path / ".spex.toml").write_text(
        f'[spex]\nspex_root = "{custom_path}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = get_spex_root(str(repo))
    assert result == str(custom_path.resolve())


def test_toml_auto_initializes(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "custom-spex"
    (repo / ".spex.toml").write_text(
        f'[spex]\nspex_root = "{custom_path}"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo))
    assert result == str(custom_path.resolve())
    assert (custom_path / "specs").is_dir()
    assert (custom_path / "archives").is_dir()


def test_toml_missing_key_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text(
        'other_key = "some_value"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo))
    assert result == str((tmp_path / "fakehome" / ".spex").resolve())


def test_auto_init_creates_home_toml(monkeypatch, tmp_path):
    """get_spex_root creates ~/.spex.toml when no config exists."""
    fakehome = tmp_path / "fakehome"
    fakehome.mkdir()
    monkeypatch.setattr("config.Path.home", lambda: fakehome)
    monkeypatch.setattr("common.Path.home", lambda: fakehome)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    toml_path = fakehome / ".spex.toml"
    assert not toml_path.exists()

    get_spex_root(str(repo))

    assert toml_path.exists()
    assert "spex_root" in toml_path.read_text()


def test_auto_init_skips_toml_when_exists(monkeypatch, tmp_path):
    """get_spex_root does not overwrite existing .spex.toml."""
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

    get_spex_root(str(repo))

    assert (repo / ".spex.toml").read_text() == '[spex]\nspex_root = ".spex"\n'


class TestCheckHelpFlag:
    def test_h_flag_prints_usage_and_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["script", "-h"])
        with pytest.raises(SystemExit) as exc_info:
            check_help_flag("Usage: script [options]\n")
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert captured.out == "Usage: script [options]\n"

    def test_help_flag_prints_usage_and_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["script", "--help"])
        with pytest.raises(SystemExit) as exc_info:
            check_help_flag("Usage: script [options]\n")
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert captured.out == "Usage: script [options]\n"

    def test_no_help_flag_does_nothing(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["script", "--verbose", "file.txt"])
        # Should return normally without raising
        check_help_flag("Usage: script [options]\n")
        captured = capsys.readouterr()
        assert captured.out == ""


class TestResolveTopicDir:
    def test_exact_match(self, tmp_path):
        specs = tmp_path / "specs"
        specs.mkdir()
        topic = specs / "2026-01-01-my-topic"
        topic.mkdir()
        result = resolve_topic_dir("2026-01-01-my-topic", specs_dir=specs)
        assert result == topic

    def test_fuzzy_match(self, tmp_path):
        specs = tmp_path / "specs"
        specs.mkdir()
        topic = specs / "2026-01-01-10-00-my-topic"
        topic.mkdir()
        result = resolve_topic_dir("my-topic", specs_dir=specs)
        assert result == topic

    def test_ambiguous_match(self, tmp_path):
        specs = tmp_path / "specs"
        specs.mkdir()
        (specs / "2026-01-01-my-topic-a").mkdir()
        (specs / "2026-01-02-my-topic-b").mkdir()
        with pytest.raises(SystemExit) as exc_info:
            resolve_topic_dir("my-topic", specs_dir=specs)
        assert exc_info.value.code == 1

    def test_not_found(self, tmp_path):
        specs = tmp_path / "specs"
        specs.mkdir()
        with pytest.raises(SystemExit) as exc_info:
            resolve_topic_dir("nonexistent", specs_dir=specs)
        assert exc_info.value.code == 1


class TestGetTemplate:
    def test_get_template_generic(self, monkeypatch, tmp_path):
        """get_template works with any template name."""
        from unittest.mock import patch

        from common import (
            EXAMPLES_TEMPLATE_DIR,
            TEMPLATE_DIR,
            _get_skill_path,
            clear_spex_root_cache,
        )
        from config import SpexContext

        clear_spex_root_cache()

        skill_path = _get_skill_path()
        test_template = skill_path / TEMPLATE_DIR / "test-tpl.md"
        test_template.write_text('---\nversion: "1.0.0"\n---\n\n# Test TPL')

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        try:
            with patch("common.get_context", return_value=ctx):
                result = get_template("test-tpl.md")
            assert "# Test TPL" in result
            assert "---" in result
            synced = tmp_path / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR / "test-tpl.md"
            assert synced.exists()
        finally:
            test_template.unlink()

    def test_resolve_template_roots_order(self, monkeypatch, tmp_path):
        """_resolve_template_roots returns spex_roots/templates + skill/templates."""
        from unittest.mock import patch

        from common import TEMPLATE_DIR, _get_skill_path
        from config import SpexContext

        clear_spex_root_cache()

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            roots = _resolve_template_roots()

        assert len(roots) == 2
        assert roots[0] == Path(str(tmp_path)) / TEMPLATE_DIR
        assert roots[-1] == _get_skill_path() / TEMPLATE_DIR

    def test_get_template_spex_root_wins(self, monkeypatch, tmp_path):
        """spex_root template takes priority over skill_path."""
        from unittest.mock import patch

        from common import TEMPLATE_DIR, _get_skill_path
        from config import SpexContext

        clear_spex_root_cache()

        # Place different content at two levels
        (tmp_path / TEMPLATE_DIR).mkdir(parents=True, exist_ok=True)
        (tmp_path / TEMPLATE_DIR / "prio-tpl.md").write_text("spex_root content")

        skill_path = _get_skill_path()
        (skill_path / TEMPLATE_DIR / "prio-tpl.md").write_text("skill content")

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            result = get_template("prio-tpl.md")
        assert result == "spex_root content"

        # Clean up
        (tmp_path / TEMPLATE_DIR / "prio-tpl.md").unlink()
        (skill_path / TEMPLATE_DIR / "prio-tpl.md").unlink()

    def test_get_template_skill_fallback(self, tmp_path):
        """Skill template used when spex_root templates/ has no match."""
        from unittest.mock import patch

        from common import TEMPLATE_DIR, _get_skill_path
        from config import SpexContext

        clear_spex_root_cache()

        skill_path = _get_skill_path()
        test_src = skill_path / TEMPLATE_DIR / "fallback-tpl.md"
        test_src.write_text("skill fallback content")

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        try:
            with patch("common.get_context", return_value=ctx):
                result = get_template("fallback-tpl.md")
            assert result == "skill fallback content"
        finally:
            test_src.unlink()

    def test_get_template_raises_when_missing(self, tmp_path):
        """FileNotFoundError raised when template not found in any root."""
        from unittest.mock import patch

        from common import TEMPLATE_DIR, _get_skill_path
        from config import SpexContext

        clear_spex_root_cache()

        skill_path = _get_skill_path()
        unlikely = "__nonexistent-template-xyz__"

        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
            top_workdir=tmp_path,
            main_worktree=tmp_path,
        )
        with patch("common.get_context", return_value=ctx):
            with pytest.raises(FileNotFoundError, match=unlikely):
                get_template(f"{unlikely}.md")

        if (skill_path / TEMPLATE_DIR / f"{unlikely}.md").exists():
            (skill_path / TEMPLATE_DIR / f"{unlikely}.md").unlink()


class TestParseFrontMatterDescription:
    def test_single_line(self):
        content = '---\nversion: "0.0.1"\ndescription: A simple description\n---\n\n# Body'
        assert parse_front_matter_description(content) == "A simple description"

    def test_quoted_description(self):
        content = '---\ndescription: "Quoted description text"\n---\n\n# Body'
        assert parse_front_matter_description(content) == "Quoted description text"

    def test_single_quoted(self):
        content = "---\ndescription: 'Single quoted'\n---\n\n# Body"
        assert parse_front_matter_description(content) == "Single quoted"

    def test_block_scalar_pipe(self):
        content = (
            '---\nversion: "0.0.1"\ndescription: |\n'
            "  Line one of description\n"
            "  Line two of description\n"
            "---\n\n# Body"
        )
        result = parse_front_matter_description(content)
        assert result == "Line one of description Line two of description"

    def test_block_scalar_gt(self):
        content = (
            "---\ndescription: >\n"
            "  Folded line one\n"
            "  Folded line two\n"
            "---\n\n# Body"
        )
        result = parse_front_matter_description(content)
        assert result == "Folded line one Folded line two"

    def test_no_description_field(self):
        content = '---\nversion: "0.0.1"\n---\n\n# Body'
        assert parse_front_matter_description(content) == ""

    def test_no_front_matter(self):
        content = "# Just a heading\n\nSome text."
        assert parse_front_matter_description(content) == ""

    def test_block_scalar_stops_at_next_key(self):
        content = (
            "---\ndescription: |\n"
            "  Multi-line desc\n"
            "version: 1.0\n"
            "---\n\n# Body"
        )
        result = parse_front_matter_description(content)
        assert result == "Multi-line desc"


class TestGetSpecDescription:
    def test_reads_spec_md(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text(
            '---\ndescription: "From spec file"\n---\n\n# Spec',
            encoding="utf-8",
        )
        assert get_spec_description(tmp_path) == "From spec file"

    def test_missing_spec_returns_empty(self, tmp_path):
        assert get_spec_description(tmp_path) == ""

    def test_no_description_returns_empty(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text('---\nversion: "0.0.1"\n---\n\n# Spec', encoding="utf-8")
        assert get_spec_description(tmp_path) == ""


class TestFormatTopic:
    def test_verbose_0_header_only(self, tmp_path):
        topic_dir = tmp_path / "my-feature"
        topic_dir.mkdir()
        out = format_topic(topic_dir, verbose=0)
        assert out.startswith("🔧 [0/0] my-feature")
        assert len(out.splitlines()) == 1

    def test_verbose_1_with_description(self, tmp_path):
        topic_dir = tmp_path / "my-feature"
        topic_dir.mkdir()
        (topic_dir / "spec.md").write_text(
            '---\ndescription: "Build the API"\n---\n', encoding="utf-8",
        )
        out = format_topic(topic_dir, verbose=1)
        lines = out.splitlines()
        assert "Build the API" in lines[1]

    def test_verbose_2_with_todo(self, tmp_path):
        topic_dir = tmp_path / "my-feature"
        topic_dir.mkdir()
        (topic_dir / "spec.md").write_text(
            '---\ndescription: "Build the API"\n---\n', encoding="utf-8",
        )
        todo_path = topic_dir / "todo.json"
        todo_path.write_text(
            '[{"id": "1", "name": "Design"}, {"id": "2", "name": "Code"}]',
            encoding="utf-8",
        )
        out = format_topic(topic_dir, verbose=2)
        lines = out.splitlines()
        assert "Build the API" in lines[1]
        assert "1: Design" in out
        assert "2: Code" in out

    def test_completed_shows_checkmark(self, tmp_path):
        topic_dir = tmp_path / "done"
        topic_dir.mkdir()
        todo_path = topic_dir / "todo.json"
        todo_path.write_text(
            '[{"id": "1", "name": "Step", "completed_at": "2026-01-01"}]',
            encoding="utf-8",
        )
        out = format_topic(topic_dir, verbose=0)
        assert out.startswith("✅ [1/1] done")


class TestGetSpexRoots:
    def test_returns_list(self, monkeypatch, tmp_path):
        """get_spex_roots returns a list of strings."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        (repo / ".spex").mkdir()
        (repo / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        clear_spex_root_cache()

        result = get_spex_roots(str(repo))

        assert isinstance(result, list)
        assert len(result) >= 1
        assert str((repo / ".spex").resolve()) in result

    def test_home_default_always_present(self, monkeypatch, tmp_path):
        """get_spex_roots always includes ~/.spex as fallback."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        clear_spex_root_cache()

        result = get_spex_roots(str(repo))

        home_default = str((tmp_path / "fakehome" / ".spex").resolve())
        assert home_default in result

    def test_multiple_roots_when_nested(self, monkeypatch, tmp_path):
        """get_spex_roots returns multiple roots for nested directories."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        # Create parent with .spex
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / ".spex").mkdir()
        # Create child with .spex
        child = parent / "child"
        child.mkdir()
        (child / ".spex").mkdir()
        _init_git_repo(child)
        clear_spex_root_cache()

        result = get_spex_roots(str(child))

        assert str((child / ".spex").resolve()) in result
        assert str((parent / ".spex").resolve()) in result
        home_default = str((tmp_path / "fakehome" / ".spex").resolve())
        assert home_default in result


class TestGetSpexTomls:
    def test_returns_list_of_strings(self, monkeypatch, tmp_path):
        """get_spex_tomls returns a list of string paths."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        (repo / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        clear_spex_root_cache()

        result = get_spex_tomls(str(repo))

        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(p, str) for p in result)
        assert str(repo / ".spex.toml") in result

    def test_empty_when_no_tomls(self, monkeypatch, tmp_path):
        """get_spex_tomls returns empty list when no .spex.toml exists."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        clear_spex_root_cache()

        result = get_spex_tomls(str(repo))

        assert result == []
