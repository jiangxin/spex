"""Prompt spec selectors stay distinct from template names and reject old flags."""

import io
from unittest.mock import Mock

import prompt
import pytest
from debug_log import parse_name_from_argv

COMMANDS = sorted(prompt._KNOWN_SUBCMDS)


@pytest.mark.parametrize("command", sorted(prompt._KNOWN_SUBCMDS - {"review-plan"}))
def test_specialized_positional_selector(command):
    args = prompt._build_parser().parse([command, "topic", "--json"])
    assert args.name == "topic"
    assert prompt._build_parser().parse([command, "--json", "topic"]).name == "topic"


@pytest.mark.parametrize("command", COMMANDS + ["custom-template"])
@pytest.mark.parametrize("selector", [
    ["--name", "topic"], ["--name=topic"], ["topic", "extra"],
])
def test_invalid_selector_has_no_side_effects(command, selector, monkeypatch):
    metadata = Mock()
    stdin = Mock()
    monkeypatch.setattr(prompt, "_build_metadata", metadata)
    monkeypatch.setattr(prompt, "_read_stdin_extra_vars", stdin)
    with pytest.raises(SystemExit) as error:
        prompt.main([command, *selector])
    assert error.value.code == 2
    metadata.assert_not_called()
    stdin.assert_not_called()


@pytest.mark.parametrize("command", sorted(prompt._KNOWN_SUBCMDS - {"apply-commit"}))
def test_required_selector_never_dispatches(command, monkeypatch):
    dispatch = Mock()
    monkeypatch.setattr(prompt, "_do_" + command.replace("-", "_"), dispatch)
    with pytest.raises(SystemExit) as error:
        prompt.main([command])
    assert error.value.code == 2
    dispatch.assert_not_called()


def test_apply_commit_selector_remains_optional():
    assert prompt._build_parser().parse(["apply-commit"]).name is None


@pytest.mark.parametrize("command", COMMANDS + ["custom-template"])
def test_empty_selector_never_dispatches(command, monkeypatch, capsys):
    handler = "_do_render" if command == "custom-template" else "_do_" + command.replace("-", "_")
    dispatch = Mock()
    monkeypatch.setattr(prompt, handler, dispatch)
    args = [command, ""]
    with pytest.raises(SystemExit) as error:
        prompt.main(args)
    assert error.value.code == 2
    message = "requires an absolute spec path" if command == "review-plan" else (
        "Spec name must not be empty"
    )
    assert message in capsys.readouterr().err
    dispatch.assert_not_called()
    assert parse_name_from_argv(["spex", "--debug", "prompt", *args]) is None


def test_modify_spec_rejects_removed_option(monkeypatch, capsys):
    dispatch = Mock()
    monkeypatch.setattr(prompt, "_do_modify_spec", dispatch)
    with pytest.raises(SystemExit) as error:
        prompt.main(["modify-spec", "topic", "--remove-undone"])
    assert error.value.code == 2
    assert "unrecognized arguments: --remove-undone" in capsys.readouterr().err
    dispatch.assert_not_called()


@pytest.mark.parametrize("spec_name", [None, "topic", "apply-helper"])
def test_generic_template_and_spec_are_independent(spec_name, monkeypatch, capsys):
    metadata = Mock(return_value={"base": "metadata"})
    render = Mock(return_value="Rendered")
    monkeypatch.setattr(prompt, "_build_metadata", metadata)
    monkeypatch.setattr(prompt, "render_prompt", render)
    monkeypatch.setattr("sys.stdin", io.StringIO("Context"))
    args = ["custom-template"] + ([spec_name] if spec_name else []) + ["--stdin"]
    prompt.main(args)
    metadata.assert_called_once_with("custom-template", spec_name)
    render.assert_called_once_with("custom-template", spec_name, metadata={
        "base": "metadata", "prompt_context": "Context",
    })
    assert capsys.readouterr().out == "Rendered\n"


@pytest.mark.parametrize("arguments", [
    ["apply_review", "--commit", "abc", "topic", "--json"],
    ["custom-template", "topic", "--output", "apply-helper"],
])
def test_debug_prompt_selector(arguments):
    assert parse_name_from_argv(["spex", "--debug", "prompt", *arguments]) == "topic"
