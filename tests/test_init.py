import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import EXAMPLES_TEMPLATE_DIR, TEMPLATE_DIR, clear_spex_root_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_spex_root_cache()
    yield


@pytest.fixture()
def mock_workdir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    return repo


class TestIsInitialized:
    def test_not_initialized(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path / "spex"))
        clear_spex_root_cache()
        from init import is_initialized

        assert is_initialized() is False

    def test_initialized(self, tmp_path, monkeypatch):
        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        (spex_root / "archives").mkdir(parents=True)
        (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).mkdir(parents=True)
        monkeypatch.setenv("SPEX_ROOT", str(spex_root))
        clear_spex_root_cache()
        from init import is_initialized

        assert is_initialized() is True

    def test_missing_specs_dir(self, tmp_path, monkeypatch):
        spex_root = tmp_path / "spex"
        (spex_root / "archives").mkdir(parents=True)
        (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).mkdir(parents=True)
        monkeypatch.setenv("SPEX_ROOT", str(spex_root))
        clear_spex_root_cache()
        from init import is_initialized

        assert is_initialized() is False


class TestSyncTemplates:
    def test_copies_markdown_files(self, tmp_path):
        from init import _sync_templates

        spex_root = tmp_path / "spex"
        spex_root.mkdir()
        _sync_templates(str(spex_root))

        examples_dir = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples_dir.is_dir()
        assert (examples_dir / "spec-template.md").exists()
        assert (examples_dir / "apply-one-task.md").exists()
        assert (examples_dir / "apply-commit.md").exists()


class TestEnsureGitignore:
    def test_adds_gitignore_entry(self, mock_workdir):
        from init import _ensure_gitignore

        spex_root = mock_workdir / ".spex"
        spex_root.mkdir()
        _ensure_gitignore(str(mock_workdir), str(spex_root))

        gitignore = mock_workdir / ".gitignore"
        assert gitignore.exists()
        assert ".spex/" in gitignore.read_text()

    def test_skips_when_already_ignored(self, mock_workdir):
        from init import _ensure_gitignore

        gitignore = mock_workdir / ".gitignore"
        gitignore.write_text(".spex/\n")

        spex_root = mock_workdir / ".spex"
        spex_root.mkdir()
        _ensure_gitignore(str(mock_workdir), str(spex_root))

        assert gitignore.read_text().count(".spex/") == 1

    def test_skips_when_spex_root_outside_workdir(self, mock_workdir, tmp_path):
        from init import _ensure_gitignore

        spex_root = tmp_path / "external-spex"
        spex_root.mkdir()
        _ensure_gitignore(str(mock_workdir), str(spex_root))

        gitignore = mock_workdir / ".gitignore"
        assert not gitignore.exists()


class TestRunInit:
    def test_creates_templates(self, tmp_path, monkeypatch, mock_workdir):
        from init import run_init

        spex_root = mock_workdir / ".spex"
        monkeypatch.setenv("SPEX_ROOT", str(spex_root))
        clear_spex_root_cache()

        with patch("init._install_deps"), patch("init._install_cli"):
            run_init(workdir=str(mock_workdir))

        examples = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples.is_dir()
        assert (examples / "spec-template.md").exists()

    def test_idempotent(self, tmp_path, monkeypatch, mock_workdir):
        from init import run_init

        spex_root = mock_workdir / ".spex"
        monkeypatch.setenv("SPEX_ROOT", str(spex_root))
        clear_spex_root_cache()

        with patch("init._install_deps"), patch("init._install_cli"):
            run_init(workdir=str(mock_workdir))
            run_init(workdir=str(mock_workdir))

        examples = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples.is_dir()


class TestMainCheckFlag:
    def test_check_not_initialized(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path / "missing"))
        clear_spex_root_cache()
        monkeypatch.setattr(sys, "argv", ["spex", "init", "--check"])

        from init import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_check_initialized(self, tmp_path, monkeypatch):
        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        (spex_root / "archives").mkdir(parents=True)
        (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).mkdir(parents=True)
        monkeypatch.setenv("SPEX_ROOT", str(spex_root))
        clear_spex_root_cache()
        monkeypatch.setattr(sys, "argv", ["spex", "init", "--check"])

        from init import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
