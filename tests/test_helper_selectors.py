"""Positional todo/review selectors must validate before business writes."""

from unittest.mock import Mock

import debug_log
import pytest
import review_helper
import todo_helper

REVIEW_ARGS = {
    "init": ["--step", "step-1", "--commit", "abc123"],
    "append": ["--step", "step-1", "--id", "r1-f1", "--severity", "minor",
               "--category", "tests", "--title", "Finding"],
    "edit": ["--step", "step-1", "--id", "r1-f1"],
    "bump-round": ["--step", "step-1", "--commit", "abc123"],
    "set-commit": ["--step", "step-1", "--commit", "abc123"],
    "status": ["--step", "step-1"],
    "show": ["--step", "step-1"],
    "list": [],
    "get": ["--step", "step-1", "--id", "r1-f1"],
    "next": ["--step", "step-1"],
    "open-batch": ["--step", "step-1"],
    "set-pending": ["--step", "step-1", "--ids", "r1-f1",
                    "--base-commit", "abc123"],
    "complete-batch": ["--step", "step-1", "--ids", "r1-f1",
                       "--base-commit", "abc123", "--new-commit", "def456"],
}
TODO_ARGS = {
    "validate": [], "show": [],
    "append": ["--step-name", "First step"],
    "edit": ["--id", "1"], "remove": ["--id", "1"],
}


@pytest.mark.parametrize("command,options", REVIEW_ARGS.items())
def test_review_positional_selectors(command, options):
    args = review_helper._build_parser().parse([command, "topic", *options])
    assert args.name == "topic"


@pytest.mark.parametrize("command,options", TODO_ARGS.items())
def test_todo_positional_selectors(command, options):
    args = todo_helper._build_parser().parse([command, "topic", *options])
    assert args.name == "topic"


@pytest.mark.parametrize("module,commands", [
    (review_helper, REVIEW_ARGS), (todo_helper, TODO_ARGS),
])
@pytest.mark.parametrize("invalid", ["legacy", "equals", "extra", "missing", "empty"])
def test_invalid_selectors_fail_before_resolution(module, commands, invalid, monkeypatch):
    resolver = Mock(side_effect=AssertionError("Must not resolve an invalid selector"))
    monkeypatch.setattr(module, "resolve_spec_dir", resolver)
    for command, options in commands.items():
        names = {
            "legacy": ["--name", "topic"], "equals": ["--name=topic"],
            "extra": ["topic", "extra"], "missing": [], "empty": [""],
        }[invalid]
        with pytest.raises(SystemExit) as error:
            module.main([command, *names, *options])
        assert error.value.code == 2
    resolver.assert_not_called()


@pytest.mark.parametrize("command,options", TODO_ARGS.items())
def test_todo_conflicting_locators_leave_file_unchanged(command, options, tmp_path):
    path = tmp_path / "todo.json"
    path.write_text("[]\n")
    with pytest.raises(SystemExit) as error:
        todo_helper.main([command, "topic", *options, "--todo-file", str(path)])
    assert error.value.code == 2
    assert path.read_text() == "[]\n"


@pytest.mark.parametrize("locators", [
    ["--todo-file", ""],
    ["topic", "--todo-file", ""],
    ["", "--todo-file", "todo.json"],
])
def test_todo_rejects_empty_locators_before_resolution(locators, monkeypatch):
    resolver = Mock(side_effect=AssertionError("Must not resolve an empty locator"))
    monkeypatch.setattr(todo_helper, "_resolve_todo_path", resolver)
    with pytest.raises(SystemExit) as error:
        todo_helper.main(["show", *locators])
    assert error.value.code == 2
    resolver.assert_not_called()


@pytest.mark.parametrize("helper,options", [
    ("todo-helper", ["show"]), ("review_helper", ["status", "--step", "step-1"]),
])
def test_debug_routes_positional_selector(helper, options):
    assert debug_log.parse_name_from_argv(["spex", "-d", helper, *options, "topic"]) == "topic"


@pytest.mark.parametrize("args", [
    ["todo-helper", "show", "topic", "--todo-file", "todo.json"],
    ["todo-helper", "show", "topic", "--todo-file", ""],
    ["todo-helper", "show", "--name=topic"],
    ["review-helper", "show", "topic"],
    ["review-helper", "status", "", "--step", "step-1"],
])
def test_debug_ignores_invalid_selectors(args):
    assert debug_log.parse_name_from_argv(["spex", "-d", *args]) is None
