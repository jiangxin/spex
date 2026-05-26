"""Tests for prompt.py: future_tasks metadata and all-done detection."""

import io
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
    """Test that apply-one-task exits cleanly when all tasks are done."""

    def test_exit_code_all_done(self, tmp_path, monkeypatch, capsys):
        """Non-JSON mode, all tasks done -> exit(0), empty stdout."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-one-task", "--topic", "test-topic"]
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_exit_code_error(self, tmp_path, monkeypatch, capsys):
        """Error scenario (missing template) -> exit(1)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv", ["prompt", "nonexistent-template"]
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert captured.err != ""

    def test_all_done_render_prompt_exits_zero(self, tmp_path, monkeypatch):
        """render_prompt() itself exits(0) when all tasks are done."""
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
        assert exc_info.value.code == 0


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
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", details="Do something"),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-commit", "--topic", "test-topic"]
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "task_id=" not in captured.err


class TestJsonMode:
    """Test --json flag for apply-one-task."""

    def test_prompt_json_mode(self, tmp_path, monkeypatch, capsys):
        """--json outputs JSON with task_id and prompt keys."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "apply-one-task", "--topic", "test-topic", "--json"],
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        captured = capsys.readouterr()
        # stderr must NOT contain task_id= in JSON mode
        assert "task_id=" not in captured.err
        # stdout must be valid JSON with expected keys
        data = json.loads(captured.out)
        assert data["task_id"] == "step-2"
        assert "step-2" in data["prompt"]
        assert "all_done" not in data

    def test_prompt_json_all_done(self, tmp_path, monkeypatch, capsys):
        """--json all-done outputs JSON with all_done=true and exits 0."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "apply-one-task", "--topic", "test-topic", "--json"],
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["task_id"] == ""
        assert data["prompt"] == ""
        assert data["all_done"] is True
        # stderr must NOT contain error message in JSON mode
        assert "all tasks are completed" not in captured.err


class TestStdinExtraVars:
    """Test --stdin flag and JSON stdin behavior."""

    def test_stdin_flag_reads_raw_text_as_prompt_context(
        self, tmp_path, monkeypatch, capsys
    ):
        """--stdin reads raw text from stdin and sets prompt_context."""
        tasks = [
            _make_task("step-1", name="First step", details="Do first"),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "apply-commit", "--topic", "test-topic", "--stdin"],
        )
        monkeypatch.setattr("sys.stdin", io.StringIO("Fix the login bug"))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "<current-task>" in captured.out
        assert "First step" in captured.out

    def test_without_stdin_flag_json_provides_extra_vars(
        self, tmp_path, monkeypatch, capsys
    ):
        """Without --stdin, valid JSON from stdin is parsed as extra_vars."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        json_input = json.dumps({
            "spec_content": "My spec",
            "next_task_text": "Build feature X",
        })
        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-commit"]
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json_input))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "<specification>" in captured.out
        assert "My spec" in captured.out
        assert "<current-task>" in captured.out
        assert "Build feature X" in captured.out


class TestBuildTaskContext:
    """Test _build_task_context helper function."""

    def test_build_task_context(self, tmp_path):
        """Verifies correct return with sample topic data."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", details="Do second thing"),
            _make_task("step-3", name="Third step"),
        ]
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        spex_root = repo / ".spex"
        specs_dir = spex_root / "specs"
        topic_dir = specs_dir / "test-topic"
        topic_dir.mkdir(parents=True)

        todo_path = topic_dir / "todo.json"
        todo_path.write_text(json.dumps(tasks), encoding="utf-8")

        spec_path = topic_dir / "spec.md"
        spec_path.write_text("# My Spec\n\nSpec body.", encoding="utf-8")

        from prompt import _build_task_context

        result = _build_task_context(topic_dir)

        assert result["spec_content"] == "# My Spec\n\nSpec body."
        assert "step-1: First step" in result["completed_tasks"]
        assert result["next_task_id"] == "step-2"
        assert "**Task**: step-2 - Second step" in result["next_task_text"]
        assert "Do second thing" in result["next_task_text"]
        assert "<details>" in result["next_task_text"]
        assert "- step-3: Third step" in result["future_tasks"]
        # Current task should NOT appear in future_tasks
        assert "step-2" not in result["future_tasks"]

    def test_build_task_context_all_done(self, tmp_path):
        """Verifies behavior when all tasks are completed."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        spex_root = repo / ".spex"
        specs_dir = spex_root / "specs"
        topic_dir = specs_dir / "test-topic"
        topic_dir.mkdir(parents=True)

        todo_path = topic_dir / "todo.json"
        todo_path.write_text(json.dumps(tasks), encoding="utf-8")

        spec_path = topic_dir / "spec.md"
        spec_path.write_text("# Done Spec\n", encoding="utf-8")

        from prompt import _build_task_context

        result = _build_task_context(topic_dir)

        assert result["spec_content"] == "# Done Spec\n"
        assert "step-1: First step" in result["completed_tasks"]
        assert "step-2: Second step" in result["completed_tasks"]
        assert result["next_task_id"] == ""
        assert result["next_task_text"] == ""
        assert result["future_tasks"] == ""


class TestApplyCommitWithTopic:
    """Test apply-commit loads spec and task context from topic."""

    def test_topic_provides_spec_and_current_task(self, tmp_path, monkeypatch):
        """apply-commit with --topic loads spec, completed, current, future tasks."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task(
                "step-2", name="Add login API", details="Implement /login endpoint"
            ),
            _make_task("step-3", name="Add tests"),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        rendered = render_prompt("apply-commit", "test-topic")
        assert "<specification>" in rendered
        assert "# Test Spec" in rendered
        assert "<completed-steps>" in rendered
        assert "step-1: First step" in rendered
        assert "<current-task>" in rendered
        assert "Add login API" in rendered
        assert "Implement /login endpoint" in rendered
        assert "step-3: Add tests" in rendered

    def test_topic_all_done_empty_next_task(self, tmp_path, monkeypatch):
        """apply-commit with --topic but all tasks done exits(0)."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        with pytest.raises(SystemExit) as exc_info:
            render_prompt("apply-commit", "test-topic")
        assert exc_info.value.code == 0

    def test_no_topic_fails_validation(self, tmp_path, monkeypatch):
        """apply-commit without --topic fails because required vars are missing."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        with pytest.raises(SystemExit):
            render_prompt("apply-commit")


class TestLogPromptToMeta:
    """Test _log_prompt_to_meta helper function."""

    def test_log_prompt_creates_prompts_array(self, tmp_path):
        """When meta.json has no prompts key, creates a new list."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        spex_root = repo / ".spex"
        specs_dir = spex_root / "specs"
        topic_dir = specs_dir / "test-topic"
        topic_dir.mkdir(parents=True)

        meta_path = topic_dir / "meta.json"
        meta_path.write_text(
            json.dumps({"workdir": str(repo)}), encoding="utf-8"
        )

        from prompt import _log_prompt_to_meta

        _log_prompt_to_meta(topic_dir, "Make the API faster")

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "prompts" in data
        assert len(data["prompts"]) == 1
        assert data["prompts"][0]["text"] == "Make the API faster"
        assert "timestamp" in data["prompts"][0]

    def test_log_prompt_appends_to_existing(self, tmp_path):
        """Appends to existing prompts array."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        spex_root = repo / ".spex"
        specs_dir = spex_root / "specs"
        topic_dir = specs_dir / "test-topic"
        topic_dir.mkdir(parents=True)

        meta_path = topic_dir / "meta.json"
        meta_path.write_text(
            json.dumps({
                "workdir": str(repo),
                "prompts": [{"text": "First prompt", "timestamp": "2026-01-01"}],
            }),
            encoding="utf-8",
        )

        from prompt import _log_prompt_to_meta

        _log_prompt_to_meta(topic_dir, "Second prompt")

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 2
        assert data["prompts"][1]["text"] == "Second prompt"

    def test_log_prompt_no_meta(self, tmp_path):
        """When meta.json does not exist, creates it with prompts."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        spex_root = repo / ".spex"
        specs_dir = spex_root / "specs"
        topic_dir = specs_dir / "test-topic"
        topic_dir.mkdir(parents=True)

        from prompt import _log_prompt_to_meta

        _log_prompt_to_meta(topic_dir, "Create meta from scratch")

        meta_path = topic_dir / "meta.json"
        assert meta_path.exists()
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 1
        assert data["prompts"][0]["text"] == "Create meta from scratch"


class TestModifySpecTemplate:
    """Test modify-spec template and prompt logging behavior."""

    def test_modify_spec_renders_with_prompt_context(self, tmp_path, monkeypatch):
        """modify-spec template renders spec_content and prompt_context."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step"),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        rendered = render_prompt(
            "modify-spec", "test-topic",
            extra_vars={"prompt_context": "Add caching to the API"},
        )
        assert "<prompt-context>" in rendered
        assert "Add caching to the API" in rendered
        assert "<specification>" in rendered
        assert "# Test Spec" in rendered
        assert "step-1: First step" in rendered

    def test_modify_spec_missing_prompt_context_fails(self, tmp_path, monkeypatch):
        """modify-spec without prompt_context fails validation."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        with pytest.raises(SystemExit):
            render_prompt("modify-spec", "test-topic")

    def test_main_logs_prompt_to_meta_for_modify_spec(
        self, tmp_path, monkeypatch, capsys
    ):
        """main() calls _log_prompt_to_meta when using modify-spec with --stdin."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step"),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-spec", "--topic", "test-topic", "--stdin"],
        )
        monkeypatch.setattr("sys.stdin", io.StringIO("Refactor the auth module"))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "<prompt-context>" in captured.out
        assert "Refactor the auth module" in captured.out

        # Verify meta.json was updated
        meta_path = topic_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "prompts" in data
        assert len(data["prompts"]) == 1
        assert data["prompts"][0]["text"] == "Refactor the auth module"

    def test_main_no_prompt_context_does_not_log(self, tmp_path, monkeypatch, capsys):
        """main() does not call _log_prompt_to_meta when prompt_context is absent."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        meta_path = topic_dir / "meta.json"
        # Pre-write meta with no prompts
        meta_path.write_text(
            json.dumps({"workdir": str(repo)}), encoding="utf-8"
        )
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        # Provide extra_vars via JSON stdin (no prompt_context key)
        json_input = json.dumps({"spec_content": "Custom spec"})
        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-spec", "--topic", "test-topic"],
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json_input))

        from prompt import main

        with pytest.raises(SystemExit):
            # Fails because prompt_context is required but not provided
            main()

        # meta.json should NOT have prompts array
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "prompts" not in data


class TestModifyTodoTemplate:
    """Test modify-todo template rendering and side-effects."""

    def test_modify_todo_renders_spec_and_completed_tasks(
        self, tmp_path, monkeypatch
    ):
        """modify-todo renders spec_content and completed_tasks."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
            _make_task("step-3", name="Third step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        rendered = render_prompt("modify-todo", "test-topic")
        assert "<specification>" in rendered
        assert "# Test Spec" in rendered
        assert "<completed-steps>" in rendered
        assert "step-1: First step" in rendered

    def test_modify_todo_no_completed_tasks(self, tmp_path, monkeypatch):
        """modify-todo without completed tasks omits completed-steps section."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))

        from prompt import render_prompt

        rendered = render_prompt("modify-todo", "test-topic")
        assert "<specification>" in rendered
        assert "<completed-steps>" not in rendered

    def test_modify_todo_cleans_undone_todos_before_render(
        self, tmp_path, monkeypatch, capsys
    ):
        """main() removes undone tasks before rendering for modify-todo."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
            _make_task("step-3", name="Third step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = topic_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-todo", "--topic", "test-topic"],
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        # Verify todo.json only contains completed tasks
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "step-1"

    def test_modify_todo_updates_xml_before_render(
        self, tmp_path, monkeypatch, capsys
    ):
        """main() writes todo.xml with only completed tasks."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
            _make_task("step-3", name="Third step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-todo", "--topic", "test-topic"],
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        xml_path = topic_dir / "todo.xml"
        assert xml_path.exists()
        xml_content = xml_path.read_text(encoding="utf-8")
        assert "<steps>" in xml_content
        assert "step-1" in xml_content
        assert "step-2" in xml_content
        assert "step-3" not in xml_content

    def test_modify_todo_no_xml_when_no_completed(
        self, tmp_path, monkeypatch, capsys
    ):
        """main() does NOT write todo.xml when no completed tasks exist."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("SPEX_ROOT", str(repo / ".spex"))
        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-todo", "--topic", "test-topic"],
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        xml_path = topic_dir / "todo.xml"
        assert not xml_path.exists()
