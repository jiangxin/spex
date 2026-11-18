"""Check modify post-action against the spec's bound repository."""

import json
import subprocess
from unittest.mock import Mock

import create_helper
import pytest
from branch import get_branch_description

BRANCH = "spex/example"
KEY = f"branch.{BRANCH}.description"
DESCRIPTION_LINE = "Describe a revised spec with enough words to wrap onto multiple lines."
NEW_DESCRIPTION = create_helper.wrap_text(DESCRIPTION_LINE)


def _git(repo, *args):
    return subprocess.run(["git", *args], check=True, cwd=repo, capture_output=True, text=True)


def _repo(directory):
    directory.mkdir()
    _git(directory, "init", "-b", "main")
    _git(directory, "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "--allow-empty", "-m", "initial")
    _git(directory, "branch", BRANCH)
    return directory


@pytest.fixture
def run_modify(tmp_path, monkeypatch):
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "spec.md").write_text(f"---\ndescription: {DESCRIPTION_LINE}\n---\n")
    (spec / "todo.json").write_text(json.dumps([{
        "id": 1, "name": "Step", "details": "Work", "completed_at": "", "commit_title": "",
    }]))
    meta_path = spec / "meta.json"
    hook = Mock()
    monkeypatch.setattr(create_helper, "resolve_spec_dir", lambda _name: spec)
    monkeypatch.setattr("hooks.run_post_action", hook)

    def run():
        create_helper.cli_post_action(["--name", "example", "--event-type", "modify"])

    return run, meta_path, hook


def _write_meta(path, repo, **overrides):
    meta = {"main_worktree": str(repo), "spex_branch": BRANCH,
            "description": "Original", "version": 2, **overrides}
    path.write_text(json.dumps(meta))


@pytest.mark.slow
def test_updates_bound_repo_and_repairs_drift(tmp_path, run_modify, monkeypatch):
    run, meta_path, _hook = run_modify
    repo = _repo(tmp_path / "bound")
    caller = _repo(tmp_path / "caller")
    _write_meta(meta_path, repo)
    _git(caller, "config", "--local", KEY, "Caller")
    monkeypatch.chdir(caller)
    run()
    assert json.loads(meta_path.read_text())["description"] == NEW_DESCRIPTION
    assert get_branch_description(BRANCH, repo) == NEW_DESCRIPTION
    assert get_branch_description(BRANCH, caller) == "Caller"

    _git(repo, "config", "--local", KEY, "Drift")
    before = meta_path.read_bytes()
    run()
    assert get_branch_description(BRANCH, repo) == NEW_DESCRIPTION
    assert meta_path.read_bytes() == before
    run()
    assert meta_path.read_bytes() == before


@pytest.mark.slow
@pytest.mark.parametrize("previous", [None, "Original Git value"])
def test_ignores_caller_git_repository_environment(tmp_path, run_modify, monkeypatch, previous):
    run, meta_path, hook = run_modify
    bound = _repo(tmp_path / "bound")
    caller = _repo(tmp_path / "caller")
    _write_meta(meta_path, bound)
    _git(caller, "config", "--local", KEY, "Caller")
    if previous is not None:
        _git(bound, "config", "--local", KEY, previous)
    before = meta_path.read_bytes()
    monkeypatch.chdir(caller)
    with monkeypatch.context() as overrides:
        overrides.setenv("GIT_DIR", str(caller / ".git"))
        overrides.setenv("GIT_WORK_TREE", str(bound))
        assert _git(bound, "rev-parse", "--show-toplevel").stdout.strip() == str(bound)
        with monkeypatch.context() as failure:
            failure.setattr(
                create_helper, "atomic_write_json", Mock(side_effect=OSError("write failed")),
            )
            with pytest.raises(SystemExit, match="write failed"):
                run()
        assert meta_path.read_bytes() == before
        hook.assert_not_called()
    assert get_branch_description(BRANCH, bound) == previous
    assert get_branch_description(BRANCH, caller) == "Caller"

    with monkeypatch.context() as overrides:
        overrides.setenv("GIT_DIR", str(caller / ".git"))
        overrides.setenv("GIT_WORK_TREE", str(bound))
        run()
    assert get_branch_description(BRANCH, bound) == NEW_DESCRIPTION
    assert get_branch_description(BRANCH, caller) == "Caller"
    assert json.loads(meta_path.read_text())["description"] == NEW_DESCRIPTION


@pytest.mark.slow
def test_missing_branch_and_invalid_bound_path(tmp_path, run_modify, monkeypatch):
    run, meta_path, hook = run_modify
    caller = _repo(tmp_path / "caller")
    nested = caller / "nested"
    nested.mkdir()
    _git(caller, "config", "--local", KEY, "Caller")
    monkeypatch.chdir(caller)
    bound = tmp_path / "bound"
    _write_meta(meta_path, bound, workdir=str(nested))
    before = meta_path.read_bytes()
    with pytest.raises(SystemExit, match="Spec repository is unavailable"):
        run()
    assert meta_path.read_bytes() == before
    assert get_branch_description(BRANCH, caller) == "Caller"
    hook.assert_not_called()

    _repo(bound)
    _git(bound, "branch", "-d", BRANCH)
    _git(bound, "branch", f"{BRANCH}/other")
    run()
    assert json.loads(meta_path.read_text())["description"] == NEW_DESCRIPTION
    assert get_branch_description(BRANCH, bound) is None
    assert get_branch_description(BRANCH, caller) == "Caller"


def test_no_branch_binding_updates_metadata(tmp_path, run_modify):
    run, meta_path, _hook = run_modify
    _write_meta(meta_path, tmp_path / "missing", spex_branch="")
    run()
    assert json.loads(meta_path.read_text())["description"] == NEW_DESCRIPTION


def test_invalid_meta_does_not_replace_repository_binding(run_modify):
    run, meta_path, hook = run_modify
    meta_path.write_text('{"main_worktree":')
    with pytest.raises(SystemExit, match="Could not read spec metadata"):
        run()
    assert meta_path.read_text() == '{"main_worktree":'
    hook.assert_not_called()


@pytest.mark.slow
@pytest.mark.parametrize("previous", [None, "Original\r\nGit"])
def test_restores_git_after_metadata_failure(tmp_path, run_modify, monkeypatch, previous):
    run, meta_path, hook = run_modify
    repo = _repo(tmp_path / "bound")
    _write_meta(meta_path, repo)
    if previous is not None:
        _git(repo, "config", "--local", KEY, previous)
    before = meta_path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(create_helper, "atomic_write_json", Mock(side_effect=OSError("write failed")))
        with pytest.raises(SystemExit, match="write failed"):
            run()
    assert meta_path.read_bytes() == before
    assert get_branch_description(BRANCH, repo) == previous
    hook.assert_not_called()
    run()
    assert json.loads(meta_path.read_text())["version"] == 2
    assert get_branch_description(BRANCH, repo) == NEW_DESCRIPTION


@pytest.mark.slow
@pytest.mark.parametrize("failure", ["config-lock", "broken-ref"])
def test_git_error_keeps_metadata(tmp_path, run_modify, failure):
    run, meta_path, hook = run_modify
    repo = _repo(tmp_path / "bound")
    _write_meta(meta_path, repo)
    _git(repo, "config", "--local", KEY, "Original Git value")
    if failure == "config-lock":
        (repo / ".git" / "config.lock").touch()
    else:
        (repo / ".git" / "refs" / "heads" / BRANCH).write_text("invalid\n")
    before = meta_path.read_bytes()
    with pytest.raises(SystemExit, match=f"Could not synchronize.*{repo}"):
        run()
    assert meta_path.read_bytes() == before
    assert get_branch_description(BRANCH, repo) == "Original Git value"
    hook.assert_not_called()
