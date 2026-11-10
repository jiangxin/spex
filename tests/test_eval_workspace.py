"""Tests for Spex eval case discovery and trial preparation."""

import json
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


@pytest.mark.slow
def test_trials_are_independent_and_install_pinned_skill(manifest, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/bogus/global.git")
    monkeypatch.setenv("SPEX_CONFIG_FILE", "/bogus/global.toml")
    case = workspace.select_cases(manifest.parent.parent)[0]
    first = workspace.prepare_trial(REPO, case, parent=tmp_path)
    second = workspace.prepare_trial(REPO, case, parent=tmp_path)
    assert first.directory != second.directory
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


@pytest.mark.slow
def test_trial_rejects_external_root_and_fixture_symlink(manifest, tmp_path):
    case = workspace.select_cases(manifest.parent.parent)[0]
    trial = workspace.prepare_trial(REPO, case, parent=tmp_path)
    outside = tmp_path / ".spex"
    outside.mkdir()
    with pytest.raises(ValueError, match="Spex roots escape"):
        workspace.verify_spex_roots(trial)
    outside.rmdir()
    shutil.rmtree(trial.directory)
    (case.fixture / ".spex").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsupported fixture path"):
        workspace.prepare_trial(REPO, case, parent=tmp_path)
    assert not list(tmp_path.glob("spex-eval-*"))
