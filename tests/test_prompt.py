"""Tests for prompt.py: future_tasks metadata and all-done detection."""

import io
import json
import subprocess

import pytest
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


@pytest.mark.slow
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

    def test_all_done_render_prompt_returns_none(self, tmp_path, monkeypatch):
        """render_prompt() returns None when all tasks are done."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import render_prompt

        result = render_prompt("apply-one-task", "test-topic")
        assert not result


@pytest.mark.slow
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


        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        # Current task should be step-2
        assert metadata["next_task_id"] == "step-2"
        assert "step-2" in metadata["next_task_text"]
        # future_tasks should contain step-3 and step-4
        assert "- **step-3**: Third step" in metadata["future_tasks"]
        assert "- **step-4**: Fourth step" in metadata["future_tasks"]
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


        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        assert "- **step-2**: Do B" in metadata["future_tasks"]
        assert "- **step-3**: Do C" in metadata["future_tasks"]


@pytest.mark.slow
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


        from prompt import render_prompt

        rendered = render_prompt("apply-one-task", "test-topic")
        assert "## Future Steps" in rendered
        assert "- **step-2**: Second step" in rendered
        assert "- **step-3**: Third step" in rendered

    def test_future_steps_section_absent_when_empty(
        self, tmp_path, monkeypatch
    ):
        """When future_tasks is empty, '## Future Steps' must NOT appear."""
        tasks = [
            _make_task("step-1", name="Only step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import render_prompt

        rendered = render_prompt("apply-one-task", "test-topic")
        assert "## Future Steps" not in rendered


@pytest.mark.slow
class TestTaskIdStderr:
    """Test that apply-one-task emits task_id to stderr via main()."""

    def test_main_emits_task_id_to_stderr(self, tmp_path, monkeypatch, capsys):
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

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

        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-commit", "--topic", "test-topic"]
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "task_id=" not in captured.err


@pytest.mark.slow
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


@pytest.mark.slow
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
        assert "- **step-1**: First step" in result["completed_tasks"]
        assert result["next_task_id"] == "step-2"
        assert "- **step-2**: Second step" in result["next_task_text"]
        assert "Do second thing" in result["next_task_text"]
        assert "- **step-3**: Third step" in result["future_tasks"]
        # Current task should NOT appear in future_tasks
        assert "step-2" not in result["future_tasks"]

    def test_build_task_context_includes_spec_content_concise(self, tmp_path):
        """Verifies spec_content_concise is present and trimmed."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
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
        spec_path.write_text(
            "---\ndescription: My desc.\n---\n\n"
            "<!-- spex:begin:requirement -->\n# Requirement\n\nDo X.\n\n"
            "<!-- spex:begin:user-clarification -->\n# User Clarification\n\nNone.\n\n"
            "<!-- spex:begin:detailed-design -->\n# Detailed Design\n\nDesign Y.\n\n"
            "<!-- spex:begin:test-plan -->\n# Test Plan\n\nTest Z.\n\n"
            "<!-- spex:begin:constraints -->\n# Constraints\n\nBe simple.\n",
            encoding="utf-8",
        )

        from prompt import _build_task_context

        result = _build_task_context(topic_dir)

        assert "spec_content_concise" in result
        concise = result["spec_content_concise"]
        assert "My desc." in concise
        assert "# Requirement" in concise
        assert "# User Clarification" in concise
        assert "# Detailed Design" not in concise
        assert "# Test Plan" not in concise
        assert "# Constraints" not in concise

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
        assert "- **step-1**: First step" in result["completed_tasks"]
        assert "- **step-2**: Second step" in result["completed_tasks"]
        assert result["next_task_id"] == ""
        assert result["next_task_text"] == ""
        assert result["future_tasks"] == ""


class TestTrimSpecContent:
    """Test _trim_spec_content helper function."""

    def test_include_strategy_with_markers(self):
        """Include: when requirement/user-clarification found, keep only those."""
        from prompt import _trim_spec_content

        spec = (
            "---\n"
            "description: |\n"
            "  My project description.\n"
            "---\n\n"
            "<!-- spex:begin:requirement -->\n"
            "# Requirement\n\n"
            "Build the login API.\n\n"
            "<!-- spex:begin:user-clarification -->\n"
            "# User Clarification\n\n"
            "Use JWT tokens.\n\n"
            "<!-- spex:begin:detailed-design -->\n"
            "# Detailed Design\n\n"
            "Create /login endpoint.\n\n"
            "<!-- spex:begin:test-plan -->\n"
            "# Test Plan\n\n"
            "Test with pytest.\n\n"
            "<!-- spex:begin:constraints -->\n"
            "# Constraints\n\n"
            "Keep it simple.\n"
        )
        result = _trim_spec_content(spec)
        assert "My project description." in result
        assert "# Requirement" in result
        assert "Build the login API." in result
        assert "# User Clarification" in result
        assert "Use JWT tokens." in result
        assert "# Detailed Design" not in result
        assert "Create /login endpoint." not in result
        assert "# Test Plan" not in result
        assert "# Constraints" not in result

    def test_exclude_strategy_with_markers(self):
        """Exclude: when no requirement/user-clarification, drop excluded sections."""
        from prompt import _trim_spec_content

        spec = (
            "---\n"
            "description: My desc.\n"
            "---\n\n"
            "<!-- spex:begin:overview -->\n"
            "# Overview\n\n"
            "General overview.\n\n"
            "<!-- spex:begin:detailed-design -->\n"
            "# Detailed Design\n\n"
            "Design details.\n\n"
            "<!-- spex:begin:test-plan -->\n"
            "# Test Plan\n\n"
            "Test stuff.\n\n"
            "<!-- spex:begin:constraints -->\n"
            "# Constraints\n\n"
            "Be simple.\n"
        )
        result = _trim_spec_content(spec)
        assert "My desc." in result
        assert "# Overview" in result
        assert "General overview." in result
        assert "# Detailed Design" not in result
        assert "# Test Plan" not in result
        assert "# Constraints" not in result

    def test_include_strategy_without_markers(self):
        """Include fallback: heading-based, keep Requirement/User Clarification."""
        from prompt import _trim_spec_content

        spec = (
            "---\n"
            "description: Short desc.\n"
            "---\n\n"
            "# Requirement\n\n"
            "Do the thing.\n\n"
            "# User Clarification\n\n"
            "None needed.\n\n"
            "# Detailed Design\n\n"
            "Design here.\n\n"
            "# Test Plan\n\n"
            "Test stuff.\n\n"
            "# Constraints\n\n"
            "Be simple.\n"
        )
        result = _trim_spec_content(spec)
        assert "Short desc." in result
        assert "# Requirement" in result
        assert "Do the thing." in result
        assert "# User Clarification" in result
        assert "# Detailed Design" not in result
        assert "# Test Plan" not in result
        assert "# Constraints" not in result

    def test_exclude_strategy_without_markers(self):
        """Exclude fallback: heading-based, no Requirement/User Clarification."""
        from prompt import _trim_spec_content

        spec = (
            "---\n"
            "description: Fallback desc.\n"
            "---\n\n"
            "# Overview\n\n"
            "Some overview.\n\n"
            "# Detailed Design\n\n"
            "Design.\n\n"
            "# Test Plan\n\n"
            "Tests.\n\n"
            "# Constraints\n\n"
            "Simple.\n"
        )
        result = _trim_spec_content(spec)
        assert "Fallback desc." in result
        assert "# Overview" in result
        assert "Some overview." in result
        assert "# Detailed Design" not in result
        assert "# Test Plan" not in result
        assert "# Constraints" not in result

    def test_empty_input(self):
        """Empty input returns empty string."""
        from prompt import _trim_spec_content

        assert _trim_spec_content("") == ""

    def test_only_front_matter(self):
        """Spec with only front-matter returns description."""
        from prompt import _trim_spec_content

        spec = "---\ndescription: Just a description.\n---\n"
        result = _trim_spec_content(spec)
        assert "Just a description." in result


@pytest.mark.slow
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


        from prompt import render_prompt

        rendered = render_prompt("apply-commit", "test-topic")
        assert "<specification>" in rendered
        assert "# Test Spec" in rendered
        assert "<completed-steps>" in rendered
        assert "**step-1**: First step" in rendered
        assert "<current-task>" in rendered
        assert "Add login API" in rendered
        assert "Implement /login endpoint" in rendered
        assert "**step-3**: Add tests" in rendered

    def test_topic_all_done_empty_next_task(self, tmp_path, monkeypatch):
        """apply-commit with --topic but all tasks done returns None."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import render_prompt

        result = render_prompt("apply-commit", "test-topic")
        assert not result

    def test_no_topic_fails_validation(self, tmp_path, monkeypatch):
        """apply-commit without --topic returns None (no topic to render)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)

        from prompt import render_prompt

        result = render_prompt("apply-commit")
        assert not result


@pytest.mark.slow
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


@pytest.mark.slow
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


        from prompt import render_prompt

        rendered = render_prompt(
            "modify-spec", "test-topic",
            extra_vars={"prompt_context": "Add caching to the API"},
        )
        assert "<prompt-context>" in rendered
        assert "Add caching to the API" in rendered
        assert "<specification>" in rendered
        assert "# Test Spec" in rendered
        assert "**step-1**: First step" in rendered

    def test_modify_spec_missing_prompt_context_fails(self, tmp_path, monkeypatch):
        """modify-spec without prompt_context fails validation."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


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


@pytest.mark.slow
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


        from prompt import render_prompt

        rendered = render_prompt("modify-todo", "test-topic")
        assert "<specification>" in rendered
        assert "# Test Spec" in rendered
        assert "<completed-steps>" in rendered
        assert "**step-1**: First step" in rendered

    def test_modify_todo_no_completed_tasks(self, tmp_path, monkeypatch):
        """modify-todo without completed tasks omits completed-steps section."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


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

    def test_modify_todo_cleans_undone_before_render(
        self, tmp_path, monkeypatch, capsys
    ):
        """main() removes undone tasks from todo.json before rendering."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
            _make_task("step-3", name="Third step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = topic_dir / "todo.json"
        monkeypatch.chdir(repo)

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

    def test_modify_todo_cleans_all_undone(self, tmp_path, monkeypatch, capsys):
        """main() handles case where all tasks are undone (empty result)."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = topic_dir / "todo.json"
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-todo", "--topic", "test-topic"],
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        main()

        # Verify todo.json is empty list
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert data == []


@pytest.mark.slow
class TestCliApplyOneTask:
    """Test cli_apply_one_task handler directly."""

    def test_json_mode_output(self, tmp_path, monkeypatch, capsys):
        """cli_apply_one_task --json outputs JSON with task_id and prompt."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import cli_apply_one_task

        cli_apply_one_task(["--topic", "test-topic", "--json"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["task_id"] == "step-2"
        assert "step-2" in data["prompt"]
        assert "task_id=" not in captured.err

    def test_non_json_emits_task_id_stderr(self, tmp_path, monkeypatch, capsys):
        """cli_apply_one_task without --json emits task_id to stderr."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import cli_apply_one_task

        cli_apply_one_task(["--topic", "test-topic"])

        captured = capsys.readouterr()
        assert "task_id=step-1" in captured.err
        assert captured.out.strip()  # should have rendered output

    def test_all_done_json(self, tmp_path, monkeypatch, capsys):
        """cli_apply_one_task --json all-done outputs all_done=true."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import cli_apply_one_task

        with pytest.raises(SystemExit) as exc_info:
            cli_apply_one_task(["--topic", "test-topic", "--json"])
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["all_done"] is True

    def test_all_done_non_json(self, tmp_path, monkeypatch, capsys):
        """cli_apply_one_task without --json exits 0 with empty output."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import cli_apply_one_task

        with pytest.raises(SystemExit) as exc_info:
            cli_apply_one_task(["--topic", "test-topic"])
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert captured.out == ""


@pytest.mark.slow
class TestCliApplyCommit:
    """Test cli_apply_commit handler directly."""

    def test_renders_commit_prompt(self, tmp_path, monkeypatch, capsys):
        """cli_apply_commit renders commit instructions."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Add feature", details="Implement X"),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import cli_apply_commit

        cli_apply_commit(["--topic", "test-topic"])

        captured = capsys.readouterr()
        assert "<current-task>" in captured.out
        assert "Add feature" in captured.out

    def test_all_done_exits_zero(self, tmp_path, monkeypatch, capsys):
        """cli_apply_commit exits 0 with empty output when all done."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import cli_apply_commit

        with pytest.raises(SystemExit) as exc_info:
            cli_apply_commit(["--topic", "test-topic"])
        assert exc_info.value.code == 0


@pytest.mark.slow
class TestCliModifySpec:
    """Test cli_modify_spec handler directly."""

    def test_stdin_logs_to_meta(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec with --stdin logs prompt_context to meta.json."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Add caching support"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--topic", "test-topic", "--stdin"])

        captured = capsys.readouterr()
        assert "Add caching support" in captured.out

        # Verify meta.json was updated
        meta_path = topic_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["prompts"][0]["text"] == "Add caching support"

    def test_json_mode_output(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec --json outputs JSON with prompt key."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Refactor module"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--topic", "test-topic", "--stdin", "--json"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "prompt" in data
        assert "Refactor module" in data["prompt"]

    def test_remove_undone_filters_todo_json(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec --remove-undone removes undone tasks from todo.json."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
            _make_task("step-3", name="Third step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = topic_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Update the spec"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--topic", "test-topic", "--stdin", "--remove-undone"])

        # Verify todo.json only contains completed tasks
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "step-1"

    def test_remove_undone_metadata_reflects_filtered_state(
        self, tmp_path, monkeypatch, capsys
    ):
        """cli_modify_spec --remove-undone rebuilds metadata after filtering."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
            _make_task("step-3", name="Third step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Revise the plan"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--topic", "test-topic", "--stdin", "--remove-undone", "--json"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        rendered = data["prompt"]
        # After filtering, step-2 and step-3 should NOT appear as future tasks
        assert "step-2" not in rendered or "Second step" not in rendered
        assert "step-3" not in rendered or "Third step" not in rendered

    def test_remove_undone_all_undone(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec --remove-undone handles all tasks being undone."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = topic_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Start fresh"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--topic", "test-topic", "--stdin", "--remove-undone"])

        # Verify todo.json is empty list
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert data == []

    def test_without_remove_undone_preserves_todo(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec without --remove-undone does not modify todo.json."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = topic_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Just modify spec"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--topic", "test-topic", "--stdin"])

        # Verify todo.json is unchanged
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[1]["id"] == "step-2"


@pytest.mark.slow
class TestCliModifyTodo:
    """Test cli_modify_todo handler directly."""

    def test_cleans_undone_todos(self, tmp_path, monkeypatch, capsys):
        """cli_modify_todo removes undone tasks from todo.json."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = topic_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import cli_modify_todo

        cli_modify_todo(["--topic", "test-topic"])

        # Verify todo.json only contains completed tasks
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "step-1"

    def test_json_mode_output(self, tmp_path, monkeypatch, capsys):
        """cli_modify_todo --json outputs JSON with prompt key."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import cli_modify_todo

        cli_modify_todo(["--topic", "test-topic", "--json"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "prompt" in data


@pytest.mark.slow
class TestMainRouting:
    """Test main() subcommand routing."""

    def test_routes_to_apply_one_task(self, tmp_path, monkeypatch, capsys):
        """main() routes apply-one-task to cli_apply_one_task."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, topic_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import main

        main(["apply-one-task", "--topic", "test-topic", "--json"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["task_id"] == "step-1"

    def test_fallback_to_cli_render(self, tmp_path, monkeypatch, capsys):
        """main() falls back to cli_render for unknown template names."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        with pytest.raises(SystemExit) as exc_info:
            main(["nonexistent-template"])
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_help_flag(self, capsys):
        """main() --help prints usage and exits 0."""
        from prompt import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "apply-one-task" in captured.out
        assert "modify-spec" in captured.out

    def test_no_args_prints_usage_to_stderr(self, capsys):
        """main() with no args prints usage to stderr and exits 1."""
        from prompt import main

        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Usage:" in captured.err
