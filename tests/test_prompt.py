"""Tests for prompt.py: future_tasks metadata and all-done detection."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import clear_spex_root_cache


def _init_git_repo(path):
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


def _make_task(task_id, name="Task", details="Details here", completed=False):
    """Create a single todo item dict."""
    return {
        "id": task_id,
        "name": name,
        "details": details,
        "completed_at": "2026-01-01T00:00:00Z" if completed else "",
        "commit_title": f"commit for {task_id}" if completed else "",
    }


def _setup_topic(tmp_path, topic_name, tasks):
    """Set up a git repo with spex root, topic dir, and todo.json."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    spex_root = repo / ".spex"
    specs_dir = spex_root / "specs"
    topic_dir = specs_dir / topic_name
    topic_dir.mkdir(parents=True)

    # Write todo.json
    todo_path = topic_dir / "todo.json"
    todo_path.write_text(json.dumps(tasks), encoding="utf-8")

    # Write meta.json
    meta_path = topic_dir / "meta.json"
    meta_path.write_text(
        json.dumps({"workdir": str(repo)}), encoding="utf-8"
    )

    # Write a minimal spec.md
    spec_path = topic_dir / "spec.md"
    spec_path.write_text("# Test Spec\n\nSome content.", encoding="utf-8")

    return repo, topic_dir


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_spex_root_cache()
    yield
    clear_spex_root_cache()


class TestAllDoneDetection:
    """Test that apply-one-task exits with error when all tasks are done."""

    def test_all_tasks_completed_exits_with_error(self, tmp_path, monkeypatch):
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        with pytest.raises(SystemExit) as exc_info:
            render_prompt("apply-one-task", "test-topic")
        assert exc_info.value.code == 1

    def test_all_tasks_completed_stderr_message(
        self, tmp_path, monkeypatch, capsys
    ):
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        with pytest.raises(SystemExit):
            render_prompt("apply-one-task", "test-topic")

        captured = capsys.readouterr()
        assert "all tasks are completed, nothing to apply" in captured.err


class TestFutureTasks:
    """Test future_tasks metadata collection."""

    def test_multiple_undone_tasks_populates_future_tasks(
        self, tmp_path, monkeypatch
    ):
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
            _make_task("step-3", name="Third step", completed=False),
            _make_task("step-4", name="Fourth step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        # Current task should be step-2
        assert metadata["next_task_id"] == "step-2"
        assert "step-2" in metadata["next_task_text"]
        # future_tasks should contain step-3 and step-4
        assert "- step-3: Third step" in metadata["future_tasks"]
        assert "- step-4: Fourth step" in metadata["future_tasks"]
        # step-2 should NOT be in future_tasks
        assert "step-2" not in metadata["future_tasks"]

    def test_single_undone_task_empty_future_tasks(
        self, tmp_path, monkeypatch
    ):
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        # Current task should be step-2
        assert "step-2" in metadata["next_task_text"]
        # future_tasks should be empty string
        assert metadata["future_tasks"] == ""

    def test_no_todo_file_empty_future_tasks(self, tmp_path, monkeypatch):
        """When there is no todo.json, future_tasks defaults to empty."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        spex_root = repo / ".spex"
        specs_dir = spex_root / "specs"
        topic_dir = specs_dir / "test-topic"
        topic_dir.mkdir(parents=True)

        # Write meta.json but NO todo.json
        meta_path = topic_dir / "meta.json"
        meta_path.write_text(
            json.dumps({"workdir": str(repo)}), encoding="utf-8"
        )
        spec_path = topic_dir / "spec.md"
        spec_path.write_text("# Spec\n", encoding="utf-8")

        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        assert metadata["next_task_id"] == ""
        assert metadata["future_tasks"] == ""

    def test_future_tasks_format(self, tmp_path, monkeypatch):
        """Verify exact format of future_tasks: '- {id}: {name}' per line."""
        tasks = [
            _make_task("step-1", name="Do A", completed=False),
            _make_task("step-2", name="Do B", completed=False),
            _make_task("step-3", name="Do C", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        expected = "- step-2: Do B\n- step-3: Do C"
        assert metadata["future_tasks"] == expected


class TestApplyOneTaskRendering:
    """Test rendered output of apply-one-task template."""

    def test_no_constraints_section(self, tmp_path, monkeypatch):
        """Rendered template must NOT contain a '## Constraints' section."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        rendered = render_prompt("apply-one-task", "test-topic")
        assert "## Constraints" not in rendered

    def test_contains_important_emphasis(self, tmp_path, monkeypatch):
        """Rendered template must contain the single-task emphasis block."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        rendered = render_prompt("apply-one-task", "test-topic")
        assert "Only implement THIS task" in rendered

    def test_future_steps_section_present_when_nonempty(
        self, tmp_path, monkeypatch
    ):
        """When future_tasks is non-empty, '## Future Steps' appears."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
            _make_task("step-2", name="Second step", completed=False),
            _make_task("step-3", name="Third step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        rendered = render_prompt("apply-one-task", "test-topic")
        assert "## Future Steps" in rendered
        assert "- step-2: Second step" in rendered
        assert "- step-3: Third step" in rendered

    def test_future_steps_section_absent_when_empty(
        self, tmp_path, monkeypatch
    ):
        """When future_tasks is empty, '## Future Steps' must NOT appear."""
        tasks = [
            _make_task("step-1", name="Only step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        rendered = render_prompt("apply-one-task", "test-topic")
        assert "## Future Steps" not in rendered


class TestTaskIdStderr:
    """Test that apply-one-task emits task_id to stderr via main()."""

    def test_main_emits_task_id_to_stderr(self, tmp_path, monkeypatch, capsys):
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-one-task", "--topic", "test-topic"]
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "task_id=step-2" in captured.err

    def test_main_no_task_id_for_other_templates(
        self, tmp_path, monkeypatch, capsys
    ):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-commit"]
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "task_id=" not in captured.err
