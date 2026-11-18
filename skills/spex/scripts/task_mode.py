"""Supported modes and template routing for Spex specifications."""

SOFTWARE = "software"
GENERAL = "general"
TASK_MODES = (SOFTWARE, GENERAL)

_GENERAL_TEMPLATES = frozenset({
    "create-spec", "spec-template", "create-todo", "modify-spec", "modify-todo",
})


class TaskModeError(ValueError):
    """An explicitly supplied task mode is invalid."""


def validate_task_mode(mode: str) -> str:
    if mode not in TASK_MODES:
        raise TaskModeError(f"Invalid task mode {mode!r}. Expected software or general.")
    return mode


def template_filename(name: str, mode: str) -> str:
    if validate_task_mode(mode) == GENERAL and name in _GENERAL_TEMPLATES:
        return f"general-{name}.md"
    return f"{name}.md"
