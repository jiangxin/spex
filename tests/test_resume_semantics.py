"""Resume semantics: commit_title is the only resume source of truth (S5)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from common import clear_spex_root_cache
from config import clear_config_cache

REPO_ROOT = Path(__file__).resolve().parent.parent
APPLY_TASK_PHASES = (
    REPO_ROOT / "skills" / "spex" / "references" / "apply-task-phases.md"
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )


def _make_task(
    task_id: str,
    *,
    name: str = "Task",
    completed: bool = False,
    commit_title: str = "",
):
    return {
        "id": task_id,
        "name": name,
        "details": "Details",
        "completed_at": "2026-01-01T00:00:00Z" if completed else "",
        "commit_title": commit_title,
    }


def _setup_topic(tmp_path: Path, spec_name: str, tasks: list):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    spex_root = repo / ".spex"
    spec_dir = spex_root / "specs" / spec_name
    spec_dir.mkdir(parents=True)

    (spec_dir / "todo.json").write_text(json.dumps(tasks), encoding="utf-8")
    (spec_dir / "meta.json").write_text(
        json.dumps({"workdir": str(repo)}), encoding="utf-8"
    )
    (spec_dir / "spec.md").write_text("# Test Spec\n", encoding="utf-8")
    return repo, spec_dir


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_spex_root_cache()
    clear_config_cache()
    yield
    clear_spex_root_cache()
    clear_config_cache()


def _prompt_apply_one_task_json(monkeypatch, capsys, name: str) -> dict:
    monkeypatch.setattr(
        "sys.argv",
        ["prompt", "apply-one-task", "--name", name, "--json"],
    )
    monkeypatch.setattr("sys.stdin", open("/dev/null"))
    from prompt import main

    main()
    return json.loads(capsys.readouterr().out)


@pytest.mark.slow
class TestResumePhaseFromCommitTitle:
    """Committed-but-incomplete steps must resume at review, not implement."""

    def test_commit_title_set_with_dirty_tree_resumes_review(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Non-empty commit_title + empty completed_at + dirty tree -> review."""
        tasks = [
            _make_task(
                "step-1",
                name="Fix Phase 5 ordering",
                commit_title="abc1234: fix: persist commit_title first",
            ),
        ]
        repo, _spec_dir = _setup_topic(tmp_path, "resume-topic", tasks)
        # Residual dirty outside spex_root (post-commit leftover scenario)
        (repo / "leftover.txt").write_text("uncommitted leftover\n", encoding="utf-8")
        monkeypatch.chdir(repo)

        data = _prompt_apply_one_task_json(monkeypatch, capsys, "resume-topic")
        assert data["task_id"] == "step-1"
        assert data["resume_phase"] == "review"
        assert data["commit_title"] == (
            "abc1234: fix: persist commit_title first"
        )

    def test_empty_commit_title_resumes_implement(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Empty commit_title -> resume_phase implement (unchanged)."""
        tasks = [
            _make_task("step-1", name="Still implementing"),
        ]
        repo, _spec_dir = _setup_topic(tmp_path, "resume-topic", tasks)
        monkeypatch.chdir(repo)

        data = _prompt_apply_one_task_json(monkeypatch, capsys, "resume-topic")
        assert data["task_id"] == "step-1"
        assert data["resume_phase"] == "implement"
        assert data["commit_title"] == ""


class TestPhase5PersistOrderingDocs:
    """Doc assertions for P0-2 / P0-3 Phase 5 ordering."""

    def test_persist_commit_title_before_outcome_committed(self):
        text = APPLY_TASK_PHASES.read_text(encoding="utf-8")
        marker = "## Phase 5: Commit (record commit_title only)"
        start = text.find(marker)
        assert start != -1
        nxt = text.find("\n## ", start + 1)
        phase5 = text[start:] if nxt == -1 else text[start:nxt]

        persist = phase5.find("--commit-title")
        outcome = phase5.lower().find("outcome=committed")
        assert persist != -1, "Phase 5 missing --commit-title persist"
        assert outcome != -1, "Phase 5 missing outcome=committed"
        assert persist < outcome, (
            "Phase 5 must persist --commit-title before outcome=committed"
        )

    def test_residual_dirty_requires_persist_first(self):
        text = APPLY_TASK_PHASES.read_text(encoding="utf-8")
        marker = "## Phase 5: Commit (record commit_title only)"
        start = text.find(marker)
        assert start != -1
        nxt = text.find("\n## ", start + 1)
        phase5 = text[start:] if nxt == -1 else text[start:nxt]

        assert "do not persist `commit_title`" not in phase5
        assert "do **not** skip persisting on residual dirty" in phase5
        persist = phase5.find("--commit-title")
        recompute = phase5.find("Recompute `$dirty`")
        assert persist != -1 and recompute != -1
        assert persist < recompute, (
            "residual-dirty path must persist commit_title before dirty check"
        )
        assert "only allowed **after** persist" in phase5
