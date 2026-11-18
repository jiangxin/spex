"""Shared test configuration — ensure scripts/ is importable."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add skills/spex/scripts/ to sys.path so tests can import modules directly.
_scripts_dir = str(Path(__file__).resolve().parent.parent / "skills" / "spex" / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# eval/spex is a loose script directory rather than an installed package, so the
# eval tests share this bootstrap instead of repeating it in every module.
_eval_spex_dir = str(Path(__file__).resolve().parent.parent / "eval" / "spex")
if _eval_spex_dir not in sys.path:
    sys.path.insert(0, _eval_spex_dir)

import manual  # noqa: E402  imported after the eval/spex path is published


def manual_action(sandbox, *arguments):
    """Dispatch one manual batch command against a prepared sandbox."""
    return manual.dispatch(manual.parser().parse_args([
        "--sandbox", str(sandbox), *arguments,
    ]), sandbox)


@pytest.fixture(autouse=True)
def _no_real_cli_install(monkeypatch):
    """Keep tests hermetic: never touch the real ~/.local/bin.

    Tests that exercise the CLI install hook re-patch
    ``init._install_cli`` with the real function explicitly.
    """
    monkeypatch.setattr("init._install_cli", MagicMock())
