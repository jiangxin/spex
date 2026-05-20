import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _shared.common import get_spec_dir


def _init_git_repo(path):
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)


def test_default_uses_cwd(monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    result = get_spec_dir()
    assert result == str(tmp_path / ".my-app.specs")


def test_custom_workdir(tmp_path):
    repo = tmp_path / "project-x"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_spec_dir(str(repo))
    assert result == str(tmp_path / ".project-x.specs")


def test_subdirectory_resolves_to_repo_root(tmp_path):
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_git_repo(repo)
    subdir = repo / "src" / "lib"
    subdir.mkdir(parents=True)

    result = get_spec_dir(str(subdir))
    assert result == str(tmp_path / ".my-app.specs")


def test_not_a_git_repo(tmp_path):
    workdir = tmp_path / "no-repo"
    workdir.mkdir()

    with pytest.raises(RuntimeError, match="Not inside a git repository"):
        get_spec_dir(str(workdir))


def test_naming_convention(tmp_path):
    repo = tmp_path / "hello-world"
    repo.mkdir()
    _init_git_repo(repo)

    result = get_spec_dir(str(repo))
    spec_path = Path(result)

    assert spec_path.parent == tmp_path
    assert spec_path.name.startswith(".")
    assert spec_path.name.endswith(".specs")
    assert "hello-world" in spec_path.name
