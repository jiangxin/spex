"""Regression tests for subcommand --help output."""

import subprocess
import sys
from pathlib import Path

import pytest

SPEX_SCRIPT = str(
    Path(__file__).resolve().parent.parent / "skills" / "spex" / "scripts" / "spex"
)

COMMANDS = [
    "list",
    "archive",
    "todo-helper",
    "review-helper",
    "apply-helper",
]


@pytest.mark.parametrize("cmd", COMMANDS)
def test_subcommand_help_exits_zero_with_usage_prefix(cmd):
    """Every listed subcommand prints `usage: spex <cmd>` on --help."""
    result = subprocess.run(
        [sys.executable, SPEX_SCRIPT, cmd, "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{cmd} --help exited non-zero"
    assert f"usage: spex {cmd}" in result.stdout, (
        f"{cmd} --help missing 'usage: spex {cmd}' prefix:\n{result.stdout}"
    )
