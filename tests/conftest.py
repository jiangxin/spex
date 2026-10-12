"""Shared test configuration — ensure scripts/ is importable."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add skills/spex/scripts/ to sys.path so tests can import modules directly.
_scripts_dir = str(Path(__file__).resolve().parent.parent / "skills" / "spex" / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


@pytest.fixture(autouse=True)
def _no_real_cli_install(monkeypatch):
    """Keep tests hermetic: never touch the real ~/.local/bin.

    Tests that exercise the CLI install hook re-patch
    ``init._install_cli`` with the real function explicitly.
    """
    monkeypatch.setattr("init._install_cli", MagicMock())
