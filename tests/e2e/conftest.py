"""Shared e2e test infrastructure — sandbox environment and helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SPEX_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "scripts" / "spex")

SPEX_TOML_NO_BRANCH_MGMT = """\
[spex]
spex_root = "spex_root"
branch_management = false
"""

SPEX_TOML_WITH_BRANCH_MGMT = """\
[spex]
spex_root = "spex_root"
branch_management = true
"""


@dataclass
class Sandbox:
    home: Path
    repo: Path
    env: dict
    projects: Path = field(default_factory=Path)
    workers: Path = field(default_factory=Path)
    worktree: Path = field(default_factory=Path)
    spex_root: Path = field(default_factory=Path)


def _init_git_repo(repo: Path, branch: str = "main") -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(
        ["git", "-c", f"init.defaultBranch={branch}", "init"],
        cwd=str(repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(repo), capture_output=True, check=True,
    )
    (repo / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."], cwd=str(repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init", "--no-gpg-sign"],
        cwd=str(repo), capture_output=True, check=True,
    )


def _make_sandbox(tmp_path: Path, toml_content: str) -> Sandbox:
    """Create a sandbox with the given .spex.toml content."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".spex.toml").write_text(toml_content, encoding="utf-8")

    projects = tmp_path / "projects"
    projects.mkdir()
    workers = tmp_path / "workers"
    workers.mkdir()

    repo = projects / "myproject"
    repo.mkdir()
    _init_git_repo(repo)

    spex_root = home / "spex_root"

    config_file = str(home / ".spex.toml")
    env = {
        **os.environ,
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "SPEX_CONFIG_FILE": config_file,
    }

    return Sandbox(
        home=home,
        repo=repo,
        env=env,
        projects=projects,
        workers=workers,
        worktree=workers,
        spex_root=spex_root,
    )


@pytest.fixture
def sandbox(tmp_path) -> Sandbox:
    """Create an isolated e2e test environment (branch_management=false)."""
    return _make_sandbox(tmp_path, SPEX_TOML_NO_BRANCH_MGMT)


@pytest.fixture
def sandbox_with_branch_mgmt(tmp_path) -> Sandbox:
    """Create a sandbox with branch_management=true."""
    return _make_sandbox(tmp_path, SPEX_TOML_WITH_BRANCH_MGMT)


@pytest.fixture
def sandbox_with_worktree(tmp_path) -> Sandbox:
    """Create a sandbox with a git worktree layout.

    Layout:
        projects/myproject/     — main worktree (git init)
        workers/myproject-feat/ — linked worktree (git worktree add)
    """
    sb = _make_sandbox(tmp_path, SPEX_TOML_NO_BRANCH_MGMT)

    worktree_path = sb.workers / "myproject-feat"
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", "feat"],
        cwd=str(sb.repo), capture_output=True, check=True,
    )
    sb.worktree = worktree_path
    return sb


def run_spex(
    *args: str,
    sandbox: Sandbox,
    stdin: str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run the spex CLI in the sandbox environment."""
    return subprocess.run(
        [sys.executable, SPEX_SCRIPT, *args],
        cwd=str(cwd or sandbox.repo),
        env=sandbox.env,
        input=stdin,
        capture_output=True,
        text=True,
    )


def create_sample_topic(
    sandbox: Sandbox,
    name: str,
    *,
    description: str = "",
    done: bool = False,
    cwd: Path | None = None,
) -> dict:
    """Create a spec via spex CLI and optionally mark all tasks done.

    Returns the parsed JSON output from create-topic (spec_name, spec_path).
    """
    cmd_args = ["create-topic", "--json", name]
    if description:
        cmd_args.extend(["--description", description])

    result = run_spex(*cmd_args, sandbox=sandbox, cwd=cwd)
    assert result.returncode == 0, f"create-topic failed: {result.stderr}"

    data = json.loads(result.stdout)
    spec_path = Path(data["topic_path"])

    (spec_path / "spec.md").write_text(
        f"# {name}\n\nTest spec.\n", encoding="utf-8",
    )

    todo = make_todo_json([
        {"id": "step-1", "name": "First step"},
        {"id": "step-2", "name": "Second step"},
    ])
    if done:
        for item in todo:
            item["completed_at"] = "2026-05-30T00:00:00"
            item["commit_title"] = f"abc1234: {item['name']}"

    (spec_path / "todo.json").write_text(
        json.dumps(todo, indent=2), encoding="utf-8",
    )

    return data


def make_todo_json(steps: list[dict]) -> list[dict]:
    """Generate a standard todo.json list from step definitions.

    Each step dict should have 'id' and 'name' keys.
    Optional: 'details', 'completed_at', 'commit_title'.
    """
    result = []
    for step in steps:
        result.append({
            "id": step["id"],
            "name": step["name"],
            "details": step.get("details", f"Details for {step['name']}"),
            "completed_at": step.get("completed_at", ""),
            "commit_title": step.get("commit_title", ""),
        })
    return result
