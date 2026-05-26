import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import (
    check_help_flag,
    clear_spex_root_cache,
    get_archives_dir,
    get_spec_description,
    get_specs_dir,
    get_spex_root,
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
    monkeypatch.chdir(repo)

    result = get_spex_root()
    assert result == str(repo / ".spex")


def test_custom_workdir(tmp_path):
    repo = tmp_path / "project-x"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_spex_root(str(repo))
    assert result == str(repo / ".spex")


def test_subdirectory_resolves_to_repo_root(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    subdir = repo / "src" / "lib"
    subdir.mkdir(parents=True)

    result = get_spex_root(str(subdir))
    assert result == str(repo / ".spex")


def test_not_a_git_repo(tmp_path):
    workdir = tmp_path / "no-repo"
    workdir.mkdir()

    with pytest.raises(RuntimeError, match="Cannot determine spex_root"):
        get_spex_root(str(workdir))


def test_require_git_raises_outside_repo(monkeypatch, tmp_path):
    workdir = tmp_path / "no-repo"
    workdir.mkdir()
    monkeypatch.setenv("SPEX_ROOT", str(tmp_path / "my-specs"))

    with pytest.raises(RuntimeError, match="Not inside a git repository"):
        get_spex_root(str(workdir), require_git=True)


def test_require_git_ok_inside_repo(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.setenv("SPEX_ROOT", str(tmp_path / "my-specs"))

    result = get_spex_root(str(repo), require_git=True)
    assert result == str((tmp_path / "my-specs").resolve())


def test_naming_convention(tmp_path):
    repo = tmp_path / "hello-world"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_spex_root(str(repo))
    spec_path = Path(result)

    assert spec_path.parent == repo
    assert spec_path.name == ".spex"


def test_specs_dir(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_specs_dir(str(repo))
    assert result == str(repo / ".spex" / "specs")


def test_archives_dir(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_archives_dir(str(repo))
    assert result == str(repo / ".spex" / "archives")


def test_local_iso_timestamp_format():
    ts = local_iso_timestamp()
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"
    assert re.match(pattern, ts), f"Unexpected format: {ts}"


def test_env_var_takes_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("SPEX_ROOT", str(tmp_path / "custom-specs"))

    result = get_spex_root()
    assert result == str(tmp_path / "custom-specs")


def test_env_var_relative_path_in_repo(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

    result = get_spex_root(str(repo))
    assert result == str(repo / ".spex")


def test_env_var_relative_path_no_repo(monkeypatch, tmp_path):
    workdir = tmp_path / "no-repo"
    workdir.mkdir()
    monkeypatch.setenv("SPEX_ROOT", "my-specs")
    monkeypatch.chdir(workdir)

    result = get_spex_root(str(workdir))
    assert result == str(workdir / "my-specs")


def test_env_var_tilde_path(monkeypatch, tmp_path):
    monkeypatch.setenv("SPEX_ROOT", "~/my-specs")
    monkeypatch.setenv("HOME", str(tmp_path))

    result = get_spex_root()
    assert result == str(tmp_path / "my-specs")


def test_toml_relative_path_in_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".spex.toml").write_text(
        'spex_root = "shared/specs"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo))
    assert result == str(repo / "shared" / "specs")


def test_repo_toml_takes_priority(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "from-repo-yaml"
    # Write repo-level .spex.toml
    (repo / ".spex.toml").write_text(
        f'spex_root = "{custom_path}"\n', encoding="utf-8"
    )
    # Write home-level (should be lower priority)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".spex.toml").write_text(
        'spex_root = "/should/not/use"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo))
    assert result == str(custom_path.resolve())


def test_default_fallback_when_no_config(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_spex_root(str(repo))
    assert result == str(repo / ".spex")


def test_default_creates_specs_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    specs_dir = repo / ".spex"
    assert not specs_dir.exists()

    get_spex_root(str(repo))
    assert specs_dir.is_dir()


def test_default_creates_internal_gitignore(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    get_spex_root(str(repo))

    spex_dir = repo / ".spex"
    gitignore = spex_dir / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert "/specs/" in content
    assert "/archives/" in content


def test_env_var_auto_initializes(monkeypatch, tmp_path):
    custom_specs = tmp_path / "custom-specs"
    monkeypatch.setenv("SPEX_ROOT", str(custom_specs))

    result = get_spex_root()
    assert result == str(custom_specs)
    assert (custom_specs / "specs").is_dir()
    assert (custom_specs / "archives").is_dir()


def test_xdg_config_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "from-xdg"
    # No repo-level .spex.toml
    xdg_dir = tmp_path / ".config" / "spex"
    xdg_dir.mkdir(parents=True)
    (xdg_dir / "config.toml").write_text(
        f'spex_root = "{custom_path}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = get_spex_root(str(repo))
    assert result == str(custom_path.resolve())


def test_home_toml_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "from-home"
    # No repo-level, no XDG
    (tmp_path / ".spex.toml").write_text(
        f'spex_root = "{custom_path}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = get_spex_root(str(repo))
    assert result == str(custom_path.resolve())


def test_toml_auto_initializes(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = tmp_path / "custom-spex"
    (repo / ".spex.toml").write_text(
        f'spex_root = "{custom_path}"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo))
    assert result == str(custom_path.resolve())
    assert (custom_path / "specs").is_dir()
    assert (custom_path / "archives").is_dir()


def test_toml_missing_key_skipped(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    # .spex.toml exists but has no spex_root key
    (repo / ".spex.toml").write_text(
        'other_key = "some_value"\n', encoding="utf-8"
    )

    result = get_spex_root(str(repo))
    assert result == str(repo / ".spex")


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
        from common import (
            EXAMPLES_TEMPLATE_DIR,
            TEMPLATE_DIR,
            _get_skill_path,
            clear_spex_root_cache,
        )
        clear_spex_root_cache()

        # Create a test template in the skill's templates dir
        skill_path = _get_skill_path()
        test_template = skill_path / TEMPLATE_DIR / "test-tpl.md"
        test_template.write_text('---\nversion: "1.0.0"\n---\n\n# Test TPL')

        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        clear_spex_root_cache()

        try:
            result = get_template("test-tpl.md")
            assert "# Test TPL" in result
            assert "---" in result  # front-matter preserved
            # Examples copy synced
            synced = tmp_path / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR / "test-tpl.md"
            assert synced.exists()
        finally:
            # Clean up test template
            test_template.unlink()


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
