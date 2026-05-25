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
    get_template,
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
        """When no custom template exists, return built-in content via builtin."""
        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))
        from common import clear_specs_root_cache, get_spec_template
        clear_specs_root_cache()

        result = get_spec_template()
        # Should return template content (not a path)
        assert "# Requirement" in result
        # Front-matter should be stripped
        assert "---" not in result
        # Builtin copy should be synced
        builtin_path = tmp_path / "templates" / "builtin" / "spec.md"
        assert builtin_path.exists()

    def test_custom_template_priority(self, monkeypatch, tmp_path):
        """Custom template takes priority over built-in."""
        # Create builtin dir so sync works
        builtin_dir = tmp_path / "templates" / "builtin"
        builtin_dir.mkdir(parents=True)

        # Create custom template
        template_dir = tmp_path / "templates"
        custom_template = template_dir / "spec.md"
        custom_template.write_text("# Custom Template\n\nMy custom content")

        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))
        from common import clear_specs_root_cache, get_spec_template
        clear_specs_root_cache()

        result = get_spec_template()
        assert "# Custom Template" in result
        assert "My custom content" in result

    def test_custom_template_strips_front_matter(self, monkeypatch, tmp_path):
        """Custom template with front-matter has it stripped."""
        template_dir = tmp_path / "templates"
        template_dir.mkdir(parents=True)
        custom_template = template_dir / "spec.md"
        custom_template.write_text(
            '---\nversion: "2.0.0"\n---\n\n# Custom V2'
        )

        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))
        from common import clear_specs_root_cache, get_spec_template
        clear_specs_root_cache()

        result = get_spec_template()
        assert "---" not in result
        assert "# Custom V2" in result

    def test_sync_updates_when_version_differs(self, monkeypatch, tmp_path):
        """Builtin copy is updated when version differs from source."""
        # Create an outdated builtin copy
        builtin_dir = tmp_path / "templates" / "builtin"
        builtin_dir.mkdir(parents=True)
        old_builtin = builtin_dir / "spec.md"
        old_builtin.write_text('---\nversion: "0.0.1"\n---\n\n# Old')

        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))
        from common import clear_specs_root_cache, get_spec_template
        clear_specs_root_cache()

        result = get_spec_template()
        # Should have synced the new version
        assert "# Requirement" in result
        # Verify the builtin file was updated
        updated_content = old_builtin.read_text()
        assert '"1.0.0"' in updated_content

    def test_get_template_generic(self, monkeypatch, tmp_path):
        """get_template works with any template name."""
        from common import (
            BUILTIN_TEMPLATE_DIR,
            TEMPLATE_DIR,
            _get_skill_path,
            clear_specs_root_cache,
        )
        clear_specs_root_cache()

        # Create a test template in the skill's templates dir
        skill_path = _get_skill_path()
        test_template = skill_path / TEMPLATE_DIR / "test-tpl.md"
        test_template.write_text('---\nversion: "1.0.0"\n---\n\n# Test TPL')

        monkeypatch.setenv("SPECS_ROOT", str(tmp_path))
        clear_specs_root_cache()

        try:
            result = get_template("test-tpl.md")
            assert "# Test TPL" in result
            assert "---" not in result
            # Builtin copy synced
            synced = tmp_path / TEMPLATE_DIR / BUILTIN_TEMPLATE_DIR / "test-tpl.md"
            assert synced.exists()
        finally:
            # Clean up test template
            test_template.unlink()
