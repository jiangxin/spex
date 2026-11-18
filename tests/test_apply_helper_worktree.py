"""Tests for apply_helper worktree mode (meta.use_git_worktree)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from apply_helper import (
    resolve_apply_git_cwd,
    validate_apply_branch,
)
from branch import get_current_branch
from common import SpecMeta, load_meta
from worktree import (
    is_registered_worktree,
    list_worktrees,
    remove_worktree,
    resolve_spex_worktree_path,
)


def _git_init_with_commit(repo: Path, branch: str = "main") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", branch],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True,
    )
    (repo / "README").write_text("hello\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README"], cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, check=True, capture_output=True,
    )


def _write_spec(
    spec_dir: Path,
    *,
    use_git_worktree: bool,
    main_worktree: Path,
    name: str | None = None,
    branch: str = "main",
    spex_branch: str = "",
) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name or spec_dir.name,
        "main_worktree": str(main_worktree),
        "branch": branch,
        "use_git_worktree": use_git_worktree,
    }
    if spex_branch:
        meta["spex_branch"] = spex_branch
    (spec_dir / "meta.json").write_text(
        json.dumps(meta), encoding="utf-8",
    )
    (spec_dir / "todo.json").write_text(
        json.dumps([{"id": "t1", "name": "work"}]),
        encoding="utf-8",
    )


class TestResolveApplyGitCwd:
    def test_prefers_spex_worktree(self):
        meta = SpecMeta(spex_worktree="/wt/path")
        assert resolve_apply_git_cwd(meta, "/fallback") == "/wt/path"

    def test_falls_back_when_empty(self):
        meta = SpecMeta(spex_worktree="")
        assert resolve_apply_git_cwd(meta, "/fallback") == "/fallback"

    def test_none_meta(self):
        assert resolve_apply_git_cwd(None, "/fallback") == "/fallback"


@pytest.mark.slow
def test_general_external_handoff_completes_without_commit(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _git_init_with_commit(repo)
    root = tmp_path / "spex"
    config = tmp_path / "spex.toml"
    config.write_text(f'[spex]\nspex_root = "{root}"\nstep_review = true\n', encoding="utf-8")
    monkeypatch.setenv("SPEX_CONFIG_FILE", str(config))
    spec = root / "specs" / "external-report"
    spec.mkdir(parents=True)
    (spec / "meta.json").write_text(json.dumps({
        "workdir": str(repo), "task_mode": "general", "spex_branch": "main",
    }))
    (spec / "spec.md").write_text("# Report\n")
    steps = [{
        "id": 1, "name": "Write report", "details": "Report outside Git",
        "completed_at": "", "commit_title": "", "skip_commit": "auto",
    }]
    todo = spec / "todo.json"
    todo.write_text(json.dumps(steps))
    script = Path(__file__).resolve().parents[1] / "skills" / "spex" / "scripts" / "spex"

    def cli(*args, stdin=""):
        return subprocess.run(
            [sys.executable, str(script), *args], cwd=repo,
            input=stdin, text=True, capture_output=True,
        )

    def head():
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    base = head()
    task = cli("prompt", "apply-one-task", spec.name, "--json")
    assert task.returncode == 0, task.stderr
    route = json.loads(task.stdout)
    assert route["task_mode"] == "general"
    assert "<delivery-step>" in route["prompt"]
    report = tmp_path / "report.md"
    report.write_text("Verified total: 60\n")
    evidence = [{
        "kind": "inspection", "criterion": "Report states total",
        "location": str(report), "observation": report.read_text().strip(),
    }]
    handoff = ("apply-helper", "verify-handoff", "--name", spec.name, "--id", "1")
    before = todo.read_bytes()
    assert cli(*handoff, "--head", "unrelated", stdin=json.dumps(evidence)).returncode != 0
    assert cli(*handoff, "--head", base, stdin="[]").returncode != 0
    unrelated = repo / "unrelated"
    unrelated.touch()
    blocked = cli(*handoff, "--head", base, stdin=json.dumps(evidence))
    assert blocked.returncode != 0
    assert "outside spex_root" in blocked.stderr
    assert todo.read_bytes() == before
    assert head() == base
    unrelated.unlink()

    verified = cli(*handoff, "--head", base, stdin=json.dumps(evidence))
    assert verified.returncode == 0, verified.stderr
    completion = cli(
        "todo-helper", "complete", spec.name, "--id", "1", "--acceptance-evidence-stdin",
        stdin=json.dumps(json.loads(verified.stdout)["acceptance_evidence"]),
    )
    assert completion.returncode == 0, completion.stderr
    done = json.loads(todo.read_text())[0]
    assert done["completed_at"]
    assert done["commit_title"] == ""
    assert done["acceptance_evidence"] == evidence
    assert head() == base


@pytest.mark.slow
@pytest.mark.parametrize("review_enabled", [False, True])
def test_general_committed_handoff_resumes_only_the_recorded_head(
    tmp_path, monkeypatch, review_enabled,
):
    repo = tmp_path / "repo"
    _git_init_with_commit(repo)
    root = tmp_path / "spex"
    config = tmp_path / "spex.toml"
    monkeypatch.setenv("SPEX_CONFIG_FILE", str(config))
    spec = root / "specs" / "versioned-guide"
    spec.mkdir(parents=True)
    meta = spec / "meta.json"
    metadata = {"workdir": str(repo), "task_mode": "general", "spex_branch": "main"}
    meta.write_text(json.dumps(metadata))
    (spec / "spec.md").write_text("# Guide\n")
    todo = spec / "todo.json"
    step = {
        "id": 1, "name": "Write guide", "details": "Document the repository workflow",
        "completed_at": "", "commit_title": "",
    }
    todo.write_text(json.dumps([step]))
    script = Path(__file__).resolve().parents[1] / "skills" / "spex" / "scripts" / "spex"

    def cli(*args, stdin=""):
        return subprocess.run([sys.executable, str(script), *args], cwd=repo,
                              input=stdin, text=True, capture_output=True)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    config.write_text(
        f'[spex]\nspex_root = "{root}"\nstep_review = {str(review_enabled).lower()}\n',
    )
    rendered = cli("prompt", "apply-commit", spec.name)
    assert rendered.returncode == 0, rendered.stderr
    assert "current task's versioned" in rendered.stdout
    (repo / "GUIDE.md").write_text("Workflow guide\n")
    git("add", "GUIDE.md")
    git("commit", "-m", "docs: add user guide")
    head = git("rev-parse", "HEAD")
    step["commit_title"] = git("log", "-1", "--pretty=%h: %s")
    todo.write_text(json.dumps([step]))
    before = todo.read_bytes()
    assert json.loads(cli("prompt", "apply-one-task", spec.name, "--json").stdout)[
        "resume_phase"] == "review"

    evidence = [{
        "kind": "inspection", "criterion": "Guide added",
        "location": "GUIDE.md", "observation": "Workflow guide is present",
    }]
    handoff = ("apply-helper", "verify-handoff", "--name", spec.name, "--id", "1", "--head")
    review = cli("prompt", "apply-review", spec.name, "--commit", head, "--json")
    assert review.returncode == 0, review.stderr
    if review_enabled:
        assert "factual accuracy" in json.loads(review.stdout)["prompt"]
        step_args = (spec.name, "--step", "1")
        finding = ("--id", "r1-f1", "--severity", "major", "--category", "other",
                   "--title", "Document the verification command", "--details", "Add a command.")
        appended = cli("review-helper", "append", *step_args, "--commit", head, *finding)
        assert appended.returncode == 0, appended.stderr
        assert cli(*handoff, head, stdin=json.dumps(evidence)).returncode != 0
        pending = cli("review-helper", "set-pending", *step_args, "--ids", "r1-f1",
                      "--base-commit", head)
        assert pending.returncode == 0, pending.stderr
        fix = cli("prompt", "apply-fix", spec.name, "--commit", head, "--json")
        assert fix.returncode == 0, fix.stderr
        assert "check_evidence.acceptance_evidence" in json.loads(fix.stdout)["prompt"]
        status = ("review-helper", "status", *step_args, "--json")
        assert "pending_amend" not in json.loads(cli(*status).stdout)
        review_file = spec / "review-step-1.json"
        pending_bytes = review_file.read_bytes()
        git("commit", "--allow-empty", "-m", "ordinary child")
        child = git("rev-parse", "HEAD")
        assert "pending_amend" not in json.loads(cli(*status).stdout)
        rejected = cli("review-helper", "complete-batch", *step_args, "--ids", "r1-f1",
                       "--base-commit", head, "--new-commit", child, "--evidence-from-stdin",
                       stdin=json.dumps({"commit_sha": child, "acceptance_evidence": evidence}))
        assert rejected.returncode != 0
        assert "not an amendment" in rejected.stderr
        assert review_file.read_bytes() == pending_bytes
        git("reset", "--hard", head)

        (repo / "GUIDE.md").write_text("Workflow guide\nVerify with: git status\n")
        git("add", "GUIDE.md")
        git("commit", "--amend", "--no-edit")
        amended = git("rev-parse", "HEAD")
        assert json.loads(cli(*status).stdout)["pending_amend"] == {
            "base_sha": head, "head_sha": amended, "finding_ids": ["r1-f1"],
        }
        assert review_file.read_bytes() == pending_bytes
        batch = ("review-helper", "complete-batch", *step_args, "--ids", "r1-f1",
                 "--base-commit", head, "--new-commit", amended, "--evidence-from-stdin")
        for stale in (
            {"commit_sha": amended}, {"commit_sha": head, "acceptance_evidence": evidence},
        ):
            assert cli(*batch, stdin=json.dumps(stale)).returncode != 0
        evidence[0]["observation"] = "Workflow guide includes its verification command"
        fixed = cli(*batch, stdin=json.dumps({
            "commit_sha": amended, "acceptance_evidence": evidence,
        }))
        assert fixed.returncode == 0, fixed.stderr
        assert git("rev-parse", "HEAD") == amended
        assert "pending_amend" not in json.loads(cli(*status).stdout)
        assert cli(*handoff, amended, stdin=json.dumps(evidence)).returncode != 0
        delta = cli("prompt", "apply-review", spec.name, "--commit", amended,
                    "--mode", "delta", "--json")
        assert delta.returncode == 0, delta.stderr
        assert json.loads(delta.stdout)["check_evidence_reusable"]
        head = amended
    else:
        assert json.loads(review.stdout)["skipped"]
    assert cli(*handoff, head, stdin="[]").returncode != 0
    git("commit", "--allow-empty", "-m", "unrelated")
    if review_enabled:
        stale_review = cli("prompt", "apply-review", spec.name, "--commit", head,
                           "--mode", "full", "--json")
        assert stale_review.returncode == 0, stale_review.stderr
        assert not json.loads(stale_review.stdout)["check_evidence_reusable"]
    blocked = cli(*handoff, git("rev-parse", "HEAD"), stdin=json.dumps(evidence))
    assert blocked.returncode != 0
    assert "recorded commit" in blocked.stderr
    assert todo.read_bytes() == before

    git("reset", "--hard", head)
    count = git("rev-list", "--count", "HEAD")
    verified = cli(*handoff, head, stdin=json.dumps(evidence))
    assert verified.returncode == 0, verified.stderr
    final_title = json.loads(verified.stdout)["commit_title"]
    completed = cli("todo-helper", "complete", spec.name, "--id", "1",
                    "--commit-title", final_title, "--acceptance-evidence-stdin",
                    stdin=json.dumps(evidence))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(todo.read_text())[0]
    assert result["completed_at"]
    assert result["commit_title"] == git("log", "-1", "--pretty=%h: %s")
    assert result["acceptance_evidence"] == evidence
    assert git("rev-list", "--count", "HEAD") == count

    metadata["task_mode"] = "software"
    meta.write_text(json.dumps(metadata))
    step["commit_title"] = ""
    todo.write_text(json.dumps([step]))
    software = cli("prompt", "apply-commit", spec.name)
    assert software.returncode == 0, software.stderr
    assert "current task's versioned" not in software.stdout


@pytest.mark.slow
class TestValidateApplyWorktree:
    def test_meta_true_creates_worktree_and_records_path(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "2026-09-10-19-36-topic"
        spec_dir = tmp_path / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=True,
            main_worktree=main,
            branch=main_branch,
        )

        with patch("worktree.list_worktrees", wraps=list_worktrees) as listing:
            validate_apply_branch(
                {"branch_management": True},
                spec_dir,
                cwd=main,
            )
        listing.assert_called_once_with(cwd=main)

        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.use_git_worktree is True
        assert meta.spex_branch.startswith("spex/")
        assert meta.spex_worktree
        expected = resolve_spex_worktree_path(main, spec_name)
        assert Path(meta.spex_worktree).resolve() == expected.resolve()
        assert is_registered_worktree(meta.spex_worktree, cwd=main)
        assert get_current_branch(meta.spex_worktree) == meta.spex_branch
        # Main worktree must stay on the base branch (no in-place switch).
        assert get_current_branch(main) == main_branch

        remove_worktree(meta.spex_worktree, force=True, cwd=main)

    def test_meta_false_does_not_create_or_record_worktree(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "2026-09-10-19-36-inplace"
        spec_dir = tmp_path / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=False,
            main_worktree=main,
            branch=main_branch,
        )

        validate_apply_branch(
            {"branch_management": True},
            spec_dir,
            cwd=main,
        )

        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.use_git_worktree is False
        assert meta.spex_branch.startswith("spex/")
        assert meta.spex_worktree == ""
        expected = resolve_spex_worktree_path(main, spec_name)
        assert not expected.exists()
        assert get_current_branch(main) == meta.spex_branch

    def test_meta_true_reuses_existing_worktree(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "reuse-spec"
        spec_dir = tmp_path / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=True,
            main_worktree=main,
            branch=main_branch,
        )

        validate_apply_branch(
            {"branch_management": True}, spec_dir, cwd=main,
        )
        meta1 = load_meta(spec_dir)
        assert meta1 is not None
        path1 = meta1.spex_worktree
        branch1 = meta1.spex_branch

        # The metadata points to an unregistered path while the branch
        # is still occupied by the original linked worktree.
        raw = json.loads((spec_dir / "meta.json").read_text(encoding="utf-8"))
        raw["spex_worktree"] = str(tmp_path / "stale")
        (spec_dir / "meta.json").write_text(json.dumps(raw), encoding="utf-8")
        with patch("worktree.list_worktrees", wraps=list_worktrees) as listing:
            validate_apply_branch(
                {"branch_management": True}, spec_dir, cwd=main,
            )
        listing.assert_called_once_with(cwd=main)
        meta2 = load_meta(spec_dir)
        assert meta2 is not None
        assert meta2.spex_worktree == path1
        assert meta2.spex_branch == branch1
        assert is_registered_worktree(path1, cwd=main)

        remove_worktree(path1, force=True, cwd=main)

    def test_refreshes_listing_after_removal_and_failed_add(
        self, tmp_path, monkeypatch,
    ):
        from worktree import add_worktree

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        main = tmp_path / "repo"
        _git_init_with_commit(main)
        name = "2026-09-10-19-36-topic"
        spec_dir = tmp_path / "specs" / name
        _write_spec(spec_dir, use_git_worktree=True, main_worktree=main)
        target = resolve_spex_worktree_path(main, name)
        occupied = tmp_path / "occupied"
        add_worktree(target, "spex/topic", cwd=main)
        second = f"spex/{name}"

        def fail_after_occupying_next_candidate(path, branch, *, base=None, cwd=None):
            assert path == target and branch == "spex/topic"
            add_worktree(occupied, second, cwd=cwd)
            raise subprocess.CalledProcessError(1, ["git", "worktree", "add"])

        with (
            patch("worktree.list_worktrees", wraps=list_worktrees) as listing,
            patch("worktree.add_worktree", side_effect=fail_after_occupying_next_candidate),
        ):
            validate_apply_branch({"branch_management": True}, spec_dir, cwd=main)
        assert listing.call_count == 4
        assert not target.exists()
        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.spex_branch == second
        assert Path(meta.spex_worktree) == occupied.resolve()

    def test_cleanup_rechecks_registration_and_preserves_locked_worktree(
        self, tmp_path, caplog,
    ):
        from apply_helper import _prepare_worktree_path
        from worktree import add_worktree

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        target = tmp_path / "newly-registered"
        original_entries = list_worktrees(cwd=main)
        add_worktree(target, "spex/concurrent", cwd=main)
        # Git requires two force flags to remove a locked worktree.
        subprocess.run(
            ["git", "worktree", "lock", str(target)],
            cwd=main, check=True, capture_output=True,
        )

        with pytest.raises(SystemExit) as failure:
            _prepare_worktree_path(target, main, original_entries)

        assert failure.value.code == 1
        assert "failed to remove worktree" in caplog.text
        assert (target / "README").is_file()
        assert is_registered_worktree(target, cwd=main)

    def test_old_meta_missing_use_git_worktree_is_inplace(
        self, tmp_path, monkeypatch,
    ):
        """Absent use_git_worktree key → False → no spex_worktree."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "legacy-spec"
        spec_dir = tmp_path / "specs" / spec_name
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({
                "name": spec_name,
                "main_worktree": str(main),
                "branch": main_branch,
            }),
            encoding="utf-8",
        )
        (spec_dir / "todo.json").write_text(
            json.dumps([{"id": "t1", "name": "work"}]),
            encoding="utf-8",
        )

        validate_apply_branch(
            {"branch_management": True}, spec_dir, cwd=main,
        )
        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.use_git_worktree is False
        assert meta.spex_worktree == ""
        assert not resolve_spex_worktree_path(main, spec_name).exists()


@pytest.mark.slow
class TestPrecheckWorktreeOutput:
    def test_precheck_prints_coding_path(self, tmp_path, monkeypatch, capsys):
        from apply_helper import cli_precheck
        from config import ProjectContext

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "precheck-wt"
        spec_dir = tmp_path / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=True,
            main_worktree=main,
            branch=main_branch,
        )

        ctx = ProjectContext(
            cwd=main,
            top_workdir=main,
            main_worktree=main,
            remote_url="",
            branch=main_branch,
            user_name="",
            user_email="",
            spex_tomls=[],
            config={"branch_management": True},
            spex_root=str(tmp_path / ".spex"),
            spex_roots=[str(tmp_path / ".spex")],
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.resolve_spec_dir", return_value=spec_dir), \
             patch("hooks.run_pre_action"):
            cli_precheck(["--name", spec_name])

        out = capsys.readouterr().out.strip()
        payload = json.loads(out)
        meta = load_meta(spec_dir)
        assert meta is not None
        assert payload["spex_worktree"] == meta.spex_worktree
        assert payload["coding_path"] == meta.spex_worktree
        assert payload["spex_branch"] == meta.spex_branch

        remove_worktree(meta.spex_worktree, force=True, cwd=main)


@pytest.mark.slow
class TestDirtyNameWorktreeCwd:
    def test_dirty_name_reports_worktree_dirtiness(
        self, tmp_path, monkeypatch, capsys,
    ):
        """dirty --name must use meta.spex_worktree as git cwd."""
        from apply_helper import cli_dirty
        from config import ProjectContext

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "dirty-wt-spec"
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=True,
            main_worktree=main,
            branch=main_branch,
        )

        validate_apply_branch(
            {"branch_management": True},
            spec_dir,
            cwd=main,
        )
        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.spex_worktree

        # Dirty the worktree only; leave main clean.
        dirty_file = Path(meta.spex_worktree) / "wt-dirty.txt"
        dirty_file.write_text("dirty\n", encoding="utf-8")

        ctx = ProjectContext(
            cwd=main,
            top_workdir=main,
            main_worktree=main,
            remote_url="",
            branch=main_branch,
            user_name="",
            user_email="",
            spex_tomls=[],
            config={"branch_management": True},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.resolve_spec_dir", return_value=spec_dir):
            cli_dirty(["--name", spec_name, "--json"])

        out = json.loads(capsys.readouterr().out.strip())
        assert out["dirty"] is True
        wt_resolved = str(Path(meta.spex_worktree).resolve())
        assert all(
            str(Path(p).resolve()).startswith(wt_resolved)
            for p in out["paths"]
        ), out["paths"]

        # Main worktree must still be clean.
        main_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=main,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert main_status.strip() == ""

        remove_worktree(meta.spex_worktree, force=True, cwd=main)
