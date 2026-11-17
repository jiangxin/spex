"""Execution diagnostics backed by saved trial artifacts."""

import json
from pathlib import Path


def retry_key(event: dict) -> tuple | None:
    """Match a helper operation and its known target within one log."""
    command = event.get("command", "")
    subcommand = event.get("subcommand") or event.get("stage")
    if not subcommand and event.get("action") == "apply.post-action":
        subcommand = "post-action"
    if not command.endswith("-helper") or not subcommand or not event.get("log"):
        return None
    target = event.get("spec")
    todo_file = event.get("todo_file_hash")
    if command == "todo-helper" and not (target or todo_file):
        return None
    return (event["log"], command, subcommand, target, todo_file, event.get("step"))


def script_issues(artifact: dict, turn: dict, path: str) -> list[dict]:
    commands = [event for event in artifact.get("value", {}).get("events", [])
                if isinstance(event.get("command"), str) and type(event.get("exit_code")) is int]
    expected_stops = [
        index for index, event in enumerate(commands)
        if event.get("action") == "apply.review-command"
        and event.get("stage") in {"status", "entry"} and event["exit_code"] != 0
    ]
    expected_stop = expected_stops[0] if len(expected_stops) == 1 and any(
        check.get("check_id") == "review-failure-stop" and check.get("verdict") == "pass"
        for check in turn.get("checks", [])
    ) else None
    succeeded = set()
    issues = []
    for index in reversed(range(len(commands))):
        event = commands[index]
        key = retry_key(event)
        if event["exit_code"] == 0:
            if key is not None:
                succeeded.add(key)
        elif index != expected_stop:
            subcommand = event.get("subcommand") or event.get("stage")
            command = " ".join(filter(None, (event["command"], subcommand)))
            issues.append({
                "kind": "script_exit",
                "turn": turn["turn"],
                "message": f"Turn {turn['turn']}: {command} exited with code {event['exit_code']}",
                "command": command,
                "exit_code": event["exit_code"],
                "recovered": key is not None and key in succeeded,
                "evidence": path,
            })
    return list(reversed(issues))


def trial_issues(
    output: Path, relative: str, metadata: dict, judge: dict, data: dict,
) -> list[dict]:
    issues = []
    for turn in metadata.get("turn_results") or []:
        index = turn.get("turn")
        if type(index) is not int or index < 1:
            continue
        path = output / f"turn-{index}.json"
        if path.is_symlink() or not path.is_file():
            continue
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            artifact = saved["artifacts"].get("spex-trace", {})
            issues.extend(script_issues(artifact, turn, f"{relative}/{path.name}"))
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            continue

    for index, metrics in data.get("turns", {}).items():
        gaps = metrics["host"].get("gaps")
        if isinstance(gaps, list) and "implausible_host_duration" in gaps:
            issues.append({
                "kind": "implausible_host_duration",
                "turn": int(index) if index.isascii() and index.isdecimal() else None,
                "message": f"Turn {index}: host timing does not cover the observed Spex activity",
                "evidence": f"{relative}/performance.json",
            })
    if judge.get("verdict") == "judge_error" or judge.get("error"):
        issues.append({
            "kind": "judge_error",
            "message": f"Judge failed ({judge.get('error') or 'judge_error'})",
            "evidence": f"{relative}/judge.json",
        })
    return issues
