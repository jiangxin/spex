import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import (
    clear_specs_root_cache,
    get_archives_dir,
    get_specs_dir,
    get_specs_root,
    local_iso_timestamp,
)


def _init_git_repo(path):
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_specs_root_cache()
    yield


def test_default_uses_cwd(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    result = get_specs_root()
    assert result == str(repo / ".specs")


def test_custom_workdir(tmp_path):
    repo = tmp_path / "project-x"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_specs_root(str(repo))
    assert result == str(repo / ".specs")


def test_subdirectory_resolves_to_repo_root(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    subdir = repo / "src" / "lib"
    subdir.mkdir(parents=True)

    result = get_specs_root(str(subdir))
    assert result == str(repo / ".specs")


def test_not_a_git_repo(tmp_path):
    workdir = tmp_path / "no-repo"
    workdir.mkdir()

    with pytest.raises(RuntimeError, match="Not inside a git repository"):
        get_specs_root(str(workdir))


def test_naming_convention(tmp_path):
    repo = tmp_path / "hello-world"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_specs_root(str(repo))
    spec_path = Path(result)

    assert spec_path.parent == repo
    assert spec_path.name == ".specs"


def test_specs_dir(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_specs_dir(str(repo))
    assert result == str(repo / ".specs" / "specs")


def test_archives_dir(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_archives_dir(str(repo))
    assert result == str(repo / ".specs" / "archives")


def test_local_iso_timestamp_format():
    ts = local_iso_timestamp()
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"
    assert re.match(pattern, ts), f"Unexpected format: {ts}"


def test_env_var_takes_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("SPECS_ROOT", str(tmp_path / "custom-specs"))

    result = get_specs_root()
    assert result == str(tmp_path / "custom-specs")


def test_git_config_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("SPECS_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    custom_path = str(tmp_path / "custom-from-git-config")
    subprocess.run(
        ["git", "-C", str(repo), "config", "specs.rootdir", custom_path],
        capture_output=True,
        check=True,
    )

    result = get_specs_root(str(repo))
    assert result == str(Path(custom_path).resolve())


def test_default_fallback_when_no_config(monkeypatch, tmp_path):
    monkeypatch.delenv("SPECS_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_specs_root(str(repo))
    assert result == str(repo / ".specs")


def test_default_creates_specs_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("SPECS_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    specs_dir = repo / ".specs"
    assert not specs_dir.exists()

    get_specs_root(str(repo))
    assert specs_dir.is_dir()


def test_default_creates_gitignore(monkeypatch, tmp_path):
    monkeypatch.delenv("SPECS_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    gitignore = repo / ".gitignore"
    assert not gitignore.exists()

    get_specs_root(str(repo))
    assert gitignore.exists()
    assert ".specs/" in gitignore.read_text().splitlines()


def test_default_appends_to_gitignore(monkeypatch, tmp_path):
    monkeypatch.delenv("SPECS_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    gitignore = repo / ".gitignore"
    gitignore.write_text("node_modules/\n")

    get_specs_root(str(repo))
    lines = gitignore.read_text().splitlines()
    assert "node_modules/" in lines
    assert ".specs/" in lines


def test_default_no_duplicate_gitignore(monkeypatch, tmp_path):
    monkeypatch.delenv("SPECS_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    gitignore = repo / ".gitignore"
    gitignore.write_text(".specs/\n")

    get_specs_root(str(repo))
    lines = gitignore.read_text().splitlines()
    assert lines.count(".specs/") == 1


def test_env_var_no_auto_create(monkeypatch, tmp_path):
    custom_specs = tmp_path / "custom-specs"
    monkeypatch.setenv("SPECS_ROOT", str(custom_specs))

    result = get_specs_root()
    assert result == str(custom_specs)
    assert not custom_specs.exists()


def test_git_config_no_auto_create(monkeypatch, tmp_path):
    monkeypatch.delenv("SPECS_ROOT", raising=False)
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)

    custom_path = tmp_path / "custom-from-config"
    subprocess.run(
        ["git", "-C", str(repo), "config", "specs.rootdir", str(custom_path)],
        capture_output=True,
        check=True,
    )

    result = get_specs_root(str(repo))
    assert result == str(custom_path.resolve())
    assert not custom_path.exists()
    assert not (repo / ".gitignore").exists()


class TestGetSpecTemplate:
    def test_fallback_to_builtin_template(self, monkeypatch, tmp_path):
        """When no custom template exists, return built-in template path."""
        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))
        from common import clear_specs_root_cache, get_spec_template
        clear_specs_root_cache()

        result = get_spec_template()
        # Should return built-in template path
        assert result.endswith("templates/spec.md")
        from pathlib import Path
        assert Path(result).exists()

    def test_custom_template_priority(self, monkeypatch, tmp_path):
        """Custom template takes priority over built-in."""
        # Create custom template
        template_dir = tmp_path / "templates"
        template_dir.mkdir(parents=True)
        custom_template = template_dir / "spec.md"
        custom_template.write_text("# Custom Template")

        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))
        from common import clear_specs_root_cache, get_spec_template
        clear_specs_root_cache()

        result = get_spec_template()
        assert result == str(custom_template)
