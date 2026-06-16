"""Tests for prompt.py: future_tasks metadata and all-done detection."""

import io
import json
import logging
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


def _setup_topic(tmp_path, spec_name, tasks):
    """Set up a git repo with spex root, spec dir, and todo.json."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    spex_root = repo / ".spex"
    specs_dir = spex_root / "specs"
    spec_dir = specs_dir / spec_name
    spec_dir.mkdir(parents=True)

    # Write todo.json
    todo_path = spec_dir / "todo.json"
    todo_path.write_text(json.dumps(tasks), encoding="utf-8")

    # Write meta.json
    meta_path = spec_dir / "meta.json"
    meta_path.write_text(
        json.dumps({"workdir": str(repo)}), encoding="utf-8"
    )

    # Write a minimal spec.md
    spec_path = spec_dir / "spec.md"
    spec_path.write_text("# Test Spec\n\nSome content.", encoding="utf-8")

    return repo, spec_dir


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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-one-task", "--name", "test-topic"]
        )
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_exit_code_error(self, tmp_path, monkeypatch, caplog):
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

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert caplog.text != ""

    def test_all_done_render_prompt_returns_none(self, tmp_path, monkeypatch):
        """render_prompt() returns None when all tasks are done."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        # Current task should be step-2
        assert metadata["current_task_id"] == "step-2"
        assert "step-2" in metadata["current_task_description"]
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        # Current task should be step-2
        assert "step-2" in metadata["current_task_description"]
        # future_tasks should be empty string
        assert metadata["future_tasks"] == ""

    def test_no_todo_file_empty_future_tasks(self, tmp_path, monkeypatch):
        """When there is no todo.json, future_tasks defaults to empty."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        spex_root = repo / ".spex"
        specs_dir = spex_root / "specs"
        spec_dir = specs_dir / "test-topic"
        spec_dir.mkdir(parents=True)

        # Write meta.json but NO todo.json
        meta_path = spec_dir / "meta.json"
        meta_path.write_text(
            json.dumps({"workdir": str(repo)}), encoding="utf-8"
        )
        spec_path = spec_dir / "spec.md"
        spec_path.write_text("# Spec\n", encoding="utf-8")

        monkeypatch.chdir(repo)


        from prompt import _build_metadata

        metadata = _build_metadata("apply-one-task", "test-topic")

        assert metadata["current_task_id"] == ""
        assert metadata["future_tasks"] == ""

    def test_future_tasks_format(self, tmp_path, monkeypatch):
        """Verify exact format of future_tasks: '- {id}: {name}' per line."""
        tasks = [
            _make_task("step-1", name="Do A", completed=False),
            _make_task("step-2", name="Do B", completed=False),
            _make_task("step-3", name="Do C", completed=False),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import render_prompt

        rendered = render_prompt("apply-one-task", "test-topic")
        assert "## Constraints" not in rendered

    def test_contains_important_emphasis(self, tmp_path, monkeypatch):
        """Rendered template must contain the single-task emphasis block."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-one-task", "--name", "test-topic"]
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-commit", "--name", "test-topic"]
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "apply-one-task", "--name", "test-topic", "--json"],
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "apply-one-task", "--name", "test-topic", "--json"],
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "apply-commit", "--name", "test-topic", "--stdin"],
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
            "spec_content_concise": "My spec",
            "current_task_description": "Build feature X",
        })
        monkeypatch.setattr(
            "sys.argv", ["prompt", "apply-commit"]
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json_input))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "<requirement>" in captured.out
        assert "My spec" in captured.out
        assert "<current-task>" in captured.out
        assert "Build feature X" in captured.out


class TestBuildTaskContext:
    """Test _build_task_context helper function."""

    def test_build_task_context(self, tmp_path):
        """Verifies correct return with sample spec data."""
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
        spec_dir = specs_dir / "test-topic"
        spec_dir.mkdir(parents=True)

        todo_path = spec_dir / "todo.json"
        todo_path.write_text(json.dumps(tasks), encoding="utf-8")

        spec_path = spec_dir / "spec.md"
        spec_path.write_text("# My Spec\n\nSpec body.", encoding="utf-8")

        from prompt import _build_task_context

        result = _build_task_context(spec_dir)

        assert result["spec_content"] == "# My Spec\n\nSpec body."
        assert "- **step-1**: First step" in result["completed_tasks"]
        assert result["current_task_id"] == "step-2"
        assert "- **step-2**: Second step" in result["current_task_description"]
        assert "Do second thing" in result["current_task_description"]
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
        spec_dir = specs_dir / "test-topic"
        spec_dir.mkdir(parents=True)

        todo_path = spec_dir / "todo.json"
        todo_path.write_text(json.dumps(tasks), encoding="utf-8")

        spec_path = spec_dir / "spec.md"
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

        result = _build_task_context(spec_dir)

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
        spec_dir = specs_dir / "test-topic"
        spec_dir.mkdir(parents=True)

        todo_path = spec_dir / "todo.json"
        todo_path.write_text(json.dumps(tasks), encoding="utf-8")

        spec_path = spec_dir / "spec.md"
        spec_path.write_text("# Done Spec\n", encoding="utf-8")

        from prompt import _build_task_context

        result = _build_task_context(spec_dir)

        assert result["spec_content"] == "# Done Spec\n"
        assert "- **step-1**: First step" in result["completed_tasks"]
        assert "- **step-2**: Second step" in result["completed_tasks"]
        assert result["current_task_id"] == ""
        assert result["current_task_description"] == ""
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
    """Test apply-commit loads spec and task context from a spec."""

    def test_spec_provides_content_and_current_task(self, tmp_path, monkeypatch):
        """apply-commit with --name loads spec content, completed, current, future tasks."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task(
                "step-2", name="Add login API", details="Implement /login endpoint"
            ),
            _make_task("step-3", name="Add tests"),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import render_prompt

        rendered = render_prompt("apply-commit", "test-topic")
        assert "<requirement>" in rendered
        assert "# Test Spec" in rendered
        assert "<completed-steps>" in rendered
        assert "**step-1**: First step" in rendered
        assert "<current-task>" in rendered
        assert "Add login API" in rendered
        assert "Implement /login endpoint" in rendered
        assert "**step-3**: Add tests" in rendered

    def test_spec_all_done_empty_next_task(self, tmp_path, monkeypatch):
        """apply-commit with --name but all tasks done returns None."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=True),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import render_prompt

        result = render_prompt("apply-commit", "test-topic")
        assert not result

    def test_no_spec_fails_validation(self, tmp_path, monkeypatch):
        """apply-commit without --name returns None (no spec to render)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)

        from prompt import render_prompt

        result = render_prompt("apply-commit")
        assert not result


@pytest.mark.slow
class TestApplyCommitUserIdentity:
    """Test apply-commit template renders user identity in git command."""

    def test_user_identity_in_commit_command(self, tmp_path, monkeypatch):
        """When meta.json has user_name and user_email, commit uses -c flags."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Add feature", details="Implement X"),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)

        # Add user_name and user_email to meta.json
        meta_path = spec_dir / "meta.json"
        meta_path.write_text(
            json.dumps({
                "workdir": str(repo),
                "user_name": "John Doe",
                "user_email": "john@example.com",
            }),
            encoding="utf-8",
        )
        monkeypatch.chdir(repo)

        from prompt import render_prompt

        rendered = render_prompt("apply-commit", "test-topic")
        assert 'git -c user.name="John Doe"' in rendered
        assert '-c user.email="john@example.com"' in rendered

    def test_no_user_identity_uses_default(self, tmp_path, monkeypatch):
        """When meta.json has no user_name/user_email, uses plain git commit."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Add feature", details="Implement X"),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import render_prompt

        rendered = render_prompt("apply-commit", "test-topic")
        assert "git commit -F-" in rendered
        assert "-c user.name" not in rendered

    def test_user_identity_skipped_when_matches_runtime(
        self, tmp_path, monkeypatch
    ):
        """When meta.json user matches runtime config, skip -c flags."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Add feature", details="Implement X"),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)

        # Write meta.json with explicit user identity
        meta_path = spec_dir / "meta.json"
        meta_path.write_text(
            json.dumps({
                "workdir": str(repo),
                "user_name": "John Doe",
                "user_email": "john@example.com",
            }),
            encoding="utf-8",
        )
        monkeypatch.chdir(repo)

        # Mock get_project_context to return matching identity
        from pathlib import Path as _Path
        from unittest.mock import patch

        from config import ProjectContext

        mock_ctx = ProjectContext(
            cwd=_Path(str(repo)),
            top_workdir=_Path(str(repo)),
            main_worktree=None,
            remote_url="",
            branch="main",
            user_name="John Doe",
            user_email="john@example.com",
        )
        with patch("prompt.get_project_context", return_value=mock_ctx):
            from prompt import render_prompt

            rendered = render_prompt("apply-commit", "test-topic")

        assert "git commit -F-" in rendered
        assert "-c user.name" not in rendered
        assert "-c user.email" not in rendered




@pytest.mark.slow
class TestModifySpecTemplate:
    """Test modify-spec template and prompt logging behavior."""

    def test_modify_spec_renders_with_prompt_context(self, tmp_path, monkeypatch):
        """modify-spec template renders spec_content and prompt_context."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step"),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import render_prompt

        rendered = render_prompt(
            "modify-spec", "test-topic",
            extra_vars={"prompt_context": "Add caching to the API"},
        )
        assert "<user-request>" in rendered
        assert "Add caching to the API" in rendered
        assert "<old-specification>" in rendered
        assert "# Test Spec" in rendered
        assert "**step-1**: First step" in rendered

    def test_modify_spec_missing_prompt_context_fails(self, tmp_path, monkeypatch):
        """modify-spec without prompt_context fails validation."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import render_prompt

        with pytest.raises(SystemExit):
            render_prompt("modify-spec", "test-topic")

    def test_main_modify_spec_renders_with_stdin(
        self, tmp_path, monkeypatch, capsys
    ):
        """main() renders modify-spec template when using --stdin."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step"),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-spec", "--name", "test-topic", "--stdin"],
        )
        monkeypatch.setattr("sys.stdin", io.StringIO("Refactor the auth module"))

        from prompt import main

        main()

        captured = capsys.readouterr()
        assert "<user-request>" in captured.out
        assert "Refactor the auth module" in captured.out


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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import render_prompt

        rendered = render_prompt("modify-todo", "test-topic")
        assert "<updated-specification>" in rendered
        assert "# Test Spec" in rendered
        assert "<completed-steps>" in rendered
        assert "**step-1**: First step" in rendered

    def test_modify_todo_no_completed_tasks(self, tmp_path, monkeypatch):
        """modify-todo without completed tasks omits completed-steps section."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)


        from prompt import render_prompt

        rendered = render_prompt("modify-todo", "test-topic")
        assert "<updated-specification>" in rendered
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = spec_dir / "todo.json"
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-todo", "--name", "test-topic"],
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = spec_dir / "todo.json"
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-todo", "--name", "test-topic"],
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = spec_dir / "todo.json"
        monkeypatch.chdir(repo)

        monkeypatch.setattr(
            "sys.argv",
            ["prompt", "modify-todo", "--name", "test-topic"],
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import cli_apply_one_task

        cli_apply_one_task(["--name", "test-topic", "--json"])

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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import cli_apply_one_task

        cli_apply_one_task(["--name", "test-topic"])

        captured = capsys.readouterr()
        assert "task_id=step-1" in captured.err
        assert captured.out.strip()  # should have rendered output

    def test_all_done_json(self, tmp_path, monkeypatch, capsys):
        """cli_apply_one_task --json all-done outputs all_done=true."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import cli_apply_one_task

        with pytest.raises(SystemExit) as exc_info:
            cli_apply_one_task(["--name", "test-topic", "--json"])
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["all_done"] is True

    def test_all_done_non_json(self, tmp_path, monkeypatch, capsys):
        """cli_apply_one_task without --json exits 0 with empty output."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import cli_apply_one_task

        with pytest.raises(SystemExit) as exc_info:
            cli_apply_one_task(["--name", "test-topic"])
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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import cli_apply_commit

        cli_apply_commit(["--name", "test-topic"])

        captured = capsys.readouterr()
        assert "<current-task>" in captured.out
        assert "Add feature" in captured.out

    def test_all_done_exits_zero(self, tmp_path, monkeypatch, capsys):
        """cli_apply_commit exits 0 with empty output when all done."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import cli_apply_commit

        with pytest.raises(SystemExit) as exc_info:
            cli_apply_commit(["--name", "test-topic"])
        assert exc_info.value.code == 0


@pytest.mark.slow
class TestCliModifySpec:
    """Test cli_modify_spec handler directly."""

    def test_stdin_included_in_output(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec with --stdin includes prompt_context in output."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Add caching support"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--name", "test-topic", "--stdin"])

        captured = capsys.readouterr()
        assert "Add caching support" in captured.out

    def test_json_mode_output(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec --json outputs JSON with prompt key."""
        tasks = [
            _make_task("step-1", name="First step", completed=False),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Refactor module"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--name", "test-topic", "--stdin", "--json"])

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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = spec_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Update the spec"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--name", "test-topic", "--stdin", "--remove-undone"])

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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Revise the plan"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--name", "test-topic", "--stdin", "--remove-undone", "--json"])

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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = spec_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Start fresh"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--name", "test-topic", "--stdin", "--remove-undone"])

        # Verify todo.json is empty list
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert data == []

    def test_without_remove_undone_preserves_todo(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec without --remove-undone does not modify todo.json."""
        tasks = [
            _make_task("step-1", name="First step", completed=True),
            _make_task("step-2", name="Second step", completed=False),
        ]
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = spec_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("Just modify spec"))

        from prompt import cli_modify_spec

        cli_modify_spec(["--name", "test-topic", "--stdin"])

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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        todo_path = spec_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import cli_modify_todo

        cli_modify_todo(["--name", "test-topic"])

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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import cli_modify_todo

        cli_modify_todo(["--name", "test-topic", "--json"])

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
        repo, spec_dir = _setup_topic(tmp_path, "test-topic", tasks)
        monkeypatch.chdir(repo)

        from prompt import main

        main(["apply-one-task", "--name", "test-topic", "--json"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["task_id"] == "step-1"

    def test_fallback_to_cli_render(self, tmp_path, monkeypatch, caplog):
        """main() falls back to cli_render for unknown template names."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                main(["nonexistent-template"])
        assert exc_info.value.code == 1
        assert "Error" in caplog.text

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
        """main() with no args prints usage to stderr and exits 2."""
        from prompt import main

        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        assert "usage:" in captured.err


class TestValidateRequiredMeta:
    """Test validate_required_meta (lines 29-53)."""

    def test_no_front_matter_returns_early(self, capsys):
        """No front-matter -> validate_required_meta returns without error."""
        from prompt import validate_required_meta
        validate_required_meta("no front matter here", {"key": "val"})
        # Should not exit or print error

    def test_no_required_key_returns_early(self, capsys):
        """Front-matter without required key -> no validation."""
        from prompt import validate_required_meta
        content = "---\nversion: 1.0\n---\n\nbody"
        validate_required_meta(content, {})

    def test_missing_required_exits_1(self, caplog):
        """Missing required metadata key -> exit 1 with error."""
        from prompt import validate_required_meta
        content = "---\nrequired:\n  - spec_content\n  - current_task\n---\n\nbody"
        with caplog.at_level(0):
            with pytest.raises(SystemExit) as exc_info:
                validate_required_meta(content, {"spec_content": "ok"})
        assert exc_info.value.code == 1
        assert "missing required metadata" in caplog.text

    def test_all_required_present_no_exit(self, caplog):
        """All required metadata present -> no exit."""
        from prompt import validate_required_meta
        content = "---\nrequired:\n  - name\n  - version\n---\n\nbody"
        with caplog.at_level(0):
            validate_required_meta(content, {"name": "test", "version": "1"})
        assert "missing" not in caplog.text


class TestFormatItemBrief:
    """Test _format_item_brief (line 70)."""

    def test_brief_format(self):
        """_format_item_brief returns concise one-liner."""
        from prompt import _format_item_brief
        result = _format_item_brief({
            "id": "step-1", "name": "Do something",
        })
        assert result == "- step-1: Do something *(details omitted)*"

    def test_brief_missing_fields(self):
        """_format_item_brief handles missing id/name."""
        from prompt import _format_item_brief
        result = _format_item_brief({})
        assert result == "- :  *(details omitted)*"


class TestBuildTaskContextNoSpec:
    """Test _build_task_context when spec.md is missing (line 171)."""

    def test_no_spec_md_returns_empty_content(self, tmp_path):
        """When spec.md doesn't exist, spec_content is empty string."""
        from prompt import _build_task_context
        spec_dir = tmp_path / "specs" / "no-spec"
        spec_dir.mkdir(parents=True)
        # No spec.md
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "no-spec"}), encoding="utf-8",
        )
        result = _build_task_context(spec_dir)
        assert result["spec_content"] == ""
        assert result["spec_content_concise"] == ""


class TestBuildTaskContextNoTodo:
    """Test _build_task_context when no todo.json (lines 226-231)."""

    def test_no_todo_returns_empty_tasks(self, tmp_path):
        """When todo.json doesn't exist, all task fields are empty."""
        from prompt import _build_task_context
        spec_dir = tmp_path / "specs" / "no-todo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "no-todo"}), encoding="utf-8",
        )
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        result = _build_task_context(spec_dir)
        assert result["completed_tasks"] == ""
        assert result["completed_tasks_concise"] == ""
        assert result["current_task_id"] == ""
        assert result["current_task_description"] == ""
        assert result["future_tasks"] == ""
        assert result["future_tasks_concise"] == ""


class TestBuildTaskContextVerboseOverflow:
    """Test _build_task_context when tasks exceed verbose_items (lines 182-186, 205-213)."""

    def test_completed_tasks_brief_overflow(self, tmp_path):
        """Completed tasks beyond verbose_items use brief format."""
        from prompt import _build_task_context
        spec_dir = tmp_path / "specs" / "overflow"
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "overflow"}), encoding="utf-8",
        )
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        tasks = [
            {"id": f"s{i}", "name": f"Task {i}", "details": "details",
             "completed_at": "2026-01-01"}
            for i in range(25)
        ]
        (spec_dir / "todo.json").write_text(json.dumps(tasks), encoding="utf-8")
        result = _build_task_context(spec_dir, verbose_items=20)
        # Should contain brief items for overflow
        assert "*(details omitted)*" in result["completed_tasks"]

    def test_future_tasks_brief_overflow(self, tmp_path):
        """Future tasks beyond verbose_items use brief format."""
        from prompt import _build_task_context
        spec_dir = tmp_path / "specs" / "future-overflow"
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "future-overflow"}), encoding="utf-8",
        )
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        tasks = [{"id": "s0", "name": "Done", "completed_at": "2026-01-01"}]
        tasks.extend([
            {"id": f"s{i}", "name": f"Future {i}", "details": "details",
             "completed_at": ""}
            for i in range(1, 25)
        ])
        (spec_dir / "todo.json").write_text(json.dumps(tasks), encoding="utf-8")
        result = _build_task_context(spec_dir, verbose_items=20)
        # Should contain brief items for overflow future tasks
        assert "*(details omitted)*" in result["future_tasks"]


class TestOutputRendered:
    """Test _output_rendered (lines 327-332)."""

    def test_output_to_file_creates_parent_dirs(self, tmp_path, capsys):
        """_output_rendered creates parent directories for output path."""
        from prompt import _output_rendered
        out_path = tmp_path / "deep" / "nested" / "dir" / "output.md"
        _output_rendered("content", str(out_path))
        assert out_path.read_text(encoding="utf-8") == "content"

    def test_output_to_stdout(self, capsys):
        """_output_rendered prints to stdout when no output_path."""
        from prompt import _output_rendered
        _output_rendered("hello stdout", None)
        assert capsys.readouterr().out.strip() == "hello stdout"


class TestNormalizeSubcmd:
    """Test _normalize_subcmd (line 652)."""

    def test_underscores_to_hyphens(self):
        """_normalize_subcmd converts underscores to hyphens."""
        from prompt import _normalize_subcmd
        assert _normalize_subcmd("apply_one_task") == "apply-one-task"

    def test_hyphens_unchanged(self):
        """_normalize_subcmd leaves hyphens unchanged."""
        from prompt import _normalize_subcmd
        assert _normalize_subcmd("apply-one-task") == "apply-one-task"

class TestMainRoutingDirect:
    """Test main() routing for all subcommands (lines 657-692)."""

    def test_routes_to_apply_commit(self, tmp_path, monkeypatch, capsys):
        """main() routes apply-commit to _do_apply_commit."""
        repo, spec_dir = _setup_topic(tmp_path, "routing-test", [
            _make_task("s1", completed=False),
        ])
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main
        main(["apply-commit", "--name", "routing-test"])

        out = capsys.readouterr().out
        assert "<current-task>" in out

    def test_routes_to_modify_spec(self, tmp_path, monkeypatch, capsys):
        """main() routes modify-spec to _do_modify_spec."""
        repo, spec_dir = _setup_topic(tmp_path, "modify-test", [
            _make_task("s1", completed=False),
        ])
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("modify this"))

        from prompt import main
        main(["modify-spec", "--name", "modify-test", "--stdin"])

        out = capsys.readouterr().out
        assert "<user-request>" in out

    def test_routes_to_modify_todo(self, tmp_path, monkeypatch, capsys):
        """main() routes modify-todo to _do_modify_todo."""
        repo, spec_dir = _setup_topic(tmp_path, "mod-todo-test", [
            _make_task("s1", completed=True),
            _make_task("s2", completed=False),
        ])
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main
        main(["modify-todo", "--name", "mod-todo-test"])

        out = capsys.readouterr().out
        assert "todo" in out.lower() or "step" in out.lower()

    def test_fallback_to_cli_render(self, tmp_path, monkeypatch, caplog):
        """main() falls back to cli_render for unknown subcommand."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                main(["nonexistent-template"])
        assert exc_info.value.code == 1

    def test_no_args_exits_2(self, capsys):
        """main() with no args prints help and exits 2."""
        from prompt import main
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2
        assert "usage:" in capsys.readouterr().err.lower()

    def test_underscore_subcmd_normalized(self, tmp_path, monkeypatch, capsys):
        """main() accepts underscore subcmd and normalizes to hyphen."""
        repo, spec_dir = _setup_topic(tmp_path, "us-test", [
            _make_task("s1", completed=False),
        ])
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))

        from prompt import main
        main(["apply_commit", "--name", "us-test"])

        out = capsys.readouterr().out
        assert "<current-task>" in out


class TestCliApplyOneTaskDirect:
    """Test cli_apply_one_task directly (lines 471-472)."""

    def test_cli_apply_one_task_json(self, tmp_path, monkeypatch, capsys):
        """cli_apply_one_task --json outputs JSON."""
        repo, spec_dir = _setup_topic(tmp_path, "cli-aot", [
            _make_task("s1", completed=False),
        ])
        monkeypatch.chdir(repo)
        from prompt import cli_apply_one_task
        cli_apply_one_task(["--name", "cli-aot", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["task_id"] == "s1"

    def test_cli_apply_one_task_all_done_json(self, tmp_path, monkeypatch, capsys):
        """cli_apply_one_task --json all-done outputs all_done=true."""
        repo, spec_dir = _setup_topic(tmp_path, "cli-aot-done", [
            _make_task("s1", completed=True),
        ])
        monkeypatch.chdir(repo)
        from prompt import cli_apply_one_task
        with pytest.raises(SystemExit) as exc_info:
            cli_apply_one_task(["--name", "cli-aot-done", "--json"])
        assert exc_info.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["all_done"] is True


class TestCliApplyCommitDirect:
    """Test cli_apply_commit directly (lines 521-522)."""

    def test_cli_apply_commit(self, tmp_path, monkeypatch, capsys):
        """cli_apply_commit renders commit prompt."""
        repo, spec_dir = _setup_topic(tmp_path, "cli-ac", [
            _make_task("s1", completed=False),
        ])
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        from prompt import cli_apply_commit
        cli_apply_commit(["--name", "cli-ac"])
        out = capsys.readouterr().out
        assert "<current-task>" in out


class TestCliModifySpecDirect:
    """Test cli_modify_spec directly (lines 567-568)."""

    def test_cli_modify_spec_json(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec --json outputs JSON prompt."""
        repo, spec_dir = _setup_topic(tmp_path, "cli-ms", [
            _make_task("s1", completed=False),
        ])
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("change req"))
        from prompt import cli_modify_spec
        cli_modify_spec(["--name", "cli-ms", "--stdin", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "prompt" in data

    def test_cli_modify_spec_remove_undone(self, tmp_path, monkeypatch, capsys):
        """cli_modify_spec --remove-undone filters todo.json."""
        repo, spec_dir = _setup_topic(tmp_path, "cli-ms-ru", [
            _make_task("s1", completed=True),
            _make_task("s2", completed=False),
            _make_task("s3", completed=False),
        ])
        todo_path = spec_dir / "todo.json"
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", io.StringIO("update"))
        from prompt import cli_modify_spec
        cli_modify_spec(["--name", "cli-ms-ru", "--stdin", "--remove-undone"])
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "s1"


class TestCliModifyTodoDirect:
    """Test cli_modify_todo directly (lines 612-613)."""

    def test_cli_modify_todo_json(self, tmp_path, monkeypatch, capsys):
        """cli_modify_todo --json outputs JSON prompt."""
        repo, spec_dir = _setup_topic(tmp_path, "cli-mt", [
            _make_task("s1", completed=True),
            _make_task("s2", completed=False),
        ])
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        from prompt import cli_modify_todo
        cli_modify_todo(["--name", "cli-mt", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "prompt" in data


class TestCliRender:
    """Test cli_render (lines 618-647)."""

    def test_cli_render_template_not_found(self, tmp_path, monkeypatch, caplog):
        """cli_render with missing template exits 1."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        from prompt import cli_render
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                cli_render(["nonexistent", "--name", "x"])
        assert exc_info.value.code == 1


class TestReadStdinExtraVars:
    """Test _read_stdin_extra_vars (lines 477-490)."""

    def test_stdin_flag_returns_prompt_context(self, monkeypatch):
        """With --stdin flag, returns {'prompt_context': text}."""
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("user input"))
        from prompt import _read_stdin_extra_vars
        result = _read_stdin_extra_vars(stdin_flag=True)
        assert result == {"prompt_context": "user input"}

    def test_no_flag_returns_parsed_json(self, monkeypatch):
        """Without --stdin flag, parses stdin as JSON."""
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO('{"key": "val"}'))
        from prompt import _read_stdin_extra_vars
        result = _read_stdin_extra_vars(stdin_flag=False)
        assert result == {"key": "val"}

    def test_invalid_json_exits_1(self, monkeypatch, caplog):
        """Invalid JSON without --stdin flag exits 1."""
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("{bad json}"))
        from prompt import _read_stdin_extra_vars
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                _read_stdin_extra_vars(stdin_flag=False)
        assert exc_info.value.code == 1
        assert "stdin must be valid JSON" in caplog.text

    def test_empty_stdin_returns_none(self, monkeypatch):
        """Empty stdin returns None."""
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        from prompt import _read_stdin_extra_vars
        result = _read_stdin_extra_vars(stdin_flag=False)
        assert result is None
