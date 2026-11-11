"""Tests for Spex eval case discovery and trial preparation."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval" / "spex"))
try:
    import workspace
finally:
    sys.path.pop(0)


@pytest.fixture
def manifest(tmp_path):
    suite = tmp_path / "suites" / "python-cli"
    fixture = suite / "fixtures" / "empty-cli"
    fixture.mkdir(parents=True)
    (fixture / "cli.py").write_text("print('original')\n", encoding="utf-8")
    path = suite / "cases.json"
    path.write_text(json.dumps([{
        "id": "create",
        "fixture": "empty-cli",
        "tags": ["smoke"],
        "turns": [{"input": "/spex create Add an option", "checks": ["no-code-change"]}],
    }]), encoding="utf-8")
    return path


def test_case_selection_and_manifest_validation(manifest):
    suites = manifest.parent.parent
    assert [case.id for case in workspace.select_cases(suites, tag="smoke")] == ["create"]
    assert workspace.select_cases(suites, suite="docs") == []
    assert workspace.select_cases(suites, case_id="apply") == []
    definition = json.loads(manifest.read_text(encoding="utf-8"))[0]
    manifest.write_text(json.dumps([definition, definition]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate case"):
        workspace.select_cases(suites)
    definition["fixture"] = "../other"
    manifest.write_text(json.dumps([definition]), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid case or fixture"):
        workspace.select_cases(suites)


def test_allocate_sandbox_uses_timestamp_and_isolates_git(tmp_path):
    first = workspace.allocate_sandbox(tmp_path / "runs")
    second = workspace.allocate_sandbox(tmp_path / "runs")
    assert workspace.SANDBOX_NAME.fullmatch(first.name)
    assert first != second
    assert (first / "_handoff").is_dir()
    assert (first / ".spex.toml").is_file()
    assert (first / ".spex" / "specs").is_dir()
    assert 'spex_root = ".spex"' in (first / ".spex.toml").read_text(encoding="utf-8")
    workspace.verify_sandbox(first, REPO)
    top = workspace.git(first, "rev-parse", "--show-toplevel").rstrip(b"\n")
    assert Path(os.fsdecode(top)).resolve() == first
    source_top = workspace.git(REPO, "rev-parse", "--show-toplevel").rstrip(b"\n")
    assert Path(os.fsdecode(source_top)).resolve() != first


def test_trial_env_prefers_runner_python_on_path(tmp_path):
    workspace_root = tmp_path / "ws"
    (workspace_root / "repo").mkdir(parents=True)
    trial = workspace.Trial(workspace_root, "deadbeef")
    first = Path(trial.env["PATH"].split(os.pathsep)[0])
    # Keep the venv bin dir even when sys.executable is a symlink into
    # Frameworks/Homebrew; resolving would hide the runner environment.
    assert first == Path(sys.executable).parent
    assert first.is_dir()


@pytest.mark.slow
def test_prepare_under_repo_runs_ignores_host_spex_roots(tmp_path, manifest):
    """Sandbox under a tree with parent .spex dirs must still prepare."""
    host = tmp_path / "host"
    (host / ".spex").mkdir(parents=True)
    runs = host / "project" / "eval" / "spex" / "runs"
    sandbox = workspace.allocate_sandbox(runs)
    case = workspace.select_cases(manifest.parent.parent)[0]
    trial = workspace.prepare_trial(
        REPO, case, parent=workspace.case_dir(sandbox, "python-cli", "create"),
    )
    assert trial.directory.is_relative_to(sandbox)
    workspace.verify_spex_roots(trial)


def test_allocate_sandbox_adds_numeric_suffix_on_name_clash(tmp_path, monkeypatch):
    monkeypatch.setattr(
        workspace, "sandbox_timestamp", lambda now=None: "2026-11-10-15-11-12",
    )
    root = tmp_path / "runs"
    one = workspace.allocate_sandbox(root)
    assert one.name == "2026-11-10-15-11-12"
    two = workspace.allocate_sandbox(root)
    assert two.name == "2026-11-10-15-11-12-2"


def test_case_dir_rejects_invalid_identifiers(tmp_path):
    sandbox = tmp_path / "2026-11-10-15-11-12"
    sandbox.mkdir()
    with pytest.raises(ValueError, match="Invalid suite or case"):
        workspace.case_dir(sandbox, "Bad", "create")
    path = workspace.case_dir(sandbox, "python-cli", "create", repeat=2)
    assert path == sandbox / "python-cli" / "create" / "2"


def test_runs_directory_remains_gitignored():
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/eval/spex/runs/" in lines


@pytest.mark.slow
def test_trials_are_independent_and_install_pinned_skill(manifest, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/bogus/global.git")
    monkeypatch.setenv("SPEX_CONFIG_FILE", "/bogus/global.toml")
    case = workspace.select_cases(manifest.parent.parent)[0]
    first = workspace.prepare_trial(REPO, case, parent=tmp_path / "case-a")
    second = workspace.prepare_trial(REPO, case, parent=tmp_path / "case-b")
    assert first.directory != second.directory
    assert first.directory == (tmp_path / "case-a" / "workspace").resolve()
    assert second.directory == (tmp_path / "case-b" / "workspace").resolve()
    (first.repo / ".spex").mkdir(exist_ok=True)
    (first.repo / ".spex" / "trial-only").touch()
    assert not (second.repo / ".spex" / "trial-only").exists()
    assert Path(first.env["TMPDIR"]).parent == first.repo
    assert Path(first.env["TMPDIR"]).is_dir()
    assert Path(first.env["TMPPREFIX"]).parent == Path(first.env["TMPDIR"])
    assert workspace.git(first.repo, "branch", "trial-only", env=first.env) == b""
    assert b"trial-only" not in workspace.git(second.repo, "branch", env=second.env)
    (first.repo / "cli.py").write_text("print('changed')\n", encoding="utf-8")
    assert (second.repo / "cli.py").read_text(encoding="utf-8") == "print('original')\n"
    assert (case.fixture / "cli.py").read_text(encoding="utf-8") == "print('original')\n"
    assert first.ref == second.ref
    assert workspace.git(first.repo, "rev-parse", "HEAD", env=first.env) == workspace.git(
        second.repo, "rev-parse", "HEAD", env=second.env
    )
    expected = workspace.git(REPO, "show", f"{first.ref}:skills/spex/SKILL.md")
    assert (first.skill / "SKILL.md").read_bytes() == expected
    assert workspace.git(second.repo, "remote", env=second.env) == b""
    assert workspace.git(second.repo, "status", "--porcelain", env=second.env) == b""

    git_dir = second.repo / ".git"
    shutil.rmtree(git_dir)
    git_dir.symlink_to(first.repo / ".git", target_is_directory=True)
    with pytest.raises(ValueError, match="standalone Git repository"):
        workspace.verify_trial_workspace(second)


@pytest.mark.slow
def test_trial_rejects_external_root_and_fixture_symlink(manifest, tmp_path):
    case = workspace.select_cases(manifest.parent.parent)[0]
    trial = workspace.prepare_trial(REPO, case, parent=tmp_path / "case-a")
    (trial.repo / ".spex.toml").write_text(
        '[spex]\nspex_root = "../.."\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Spex roots escape"):
        workspace.verify_spex_roots(trial)
    shutil.rmtree(trial.directory)
    (case.fixture / ".spex").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsupported fixture path"):
        workspace.prepare_trial(REPO, case, parent=tmp_path / "case-b")
    assert not (tmp_path / "case-b" / "workspace").exists()
