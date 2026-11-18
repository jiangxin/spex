"""Execution diagnostics as addressable issue records."""

import json
from pathlib import Path

import performance

STAGES = ("prepare", "host", "collect", "judge", "script", "unknown")
MAX_RECORDED_BYTES = 64 * 1024


def read_recorded(sandbox: Path) -> list[dict]:
    """Load adapter-written issue records from ``<sandbox>/_issues``."""
    root = Path(sandbox) / "_issues"
    if root.is_symlink() or not root.is_dir():
        return []
    issues = []
    for path in sorted(root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_RECORDED_BYTES:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        kind, message = data.get("kind"), data.get("message")
        if not isinstance(kind, str) or not kind or not isinstance(message, str):
            continue
        name = f"_issues/{path.name}"
        case = data.get("case")
        if not isinstance(case, str) or not case:
            suite, case_id = data.get("suite"), data.get("case_id")
            case = (
                f"{suite}/{case_id}"
                if isinstance(suite, str) and suite and isinstance(case_id, str) and case_id
                else "unknown"
            )
        issues.append({
            **data,
            "case": case,
            "trial": data.get("trial") if isinstance(data.get("trial"), str) else None,
            "stage": data.get("stage") if data.get("stage") in STAGES else "unknown",
            "kind": kind,
            "message": message,
            "turn": turn_number(data.get("turn")),
            "recovered": data.get("recovered") if isinstance(
                data.get("recovered"), bool) else None,
            "evidence": [name],
            "command": data.get("command") if isinstance(data.get("command"), str) else None,
            "exit_code": data.get("exit_code") if type(data.get("exit_code")) is int else None,
        })
    return issues


def helper_identity(command: dict) -> tuple | None:
    """Parse ``spex <x-helper> <subcommand>`` from a recorded argv list."""
    argv = command.get("argv") if isinstance(command, dict) else None
    if not isinstance(argv, list) or len(argv) < 3:
        return None
    if any(not isinstance(word, str) for word in argv):
        return None
    if Path(argv[0]).name != "spex":
        return None
    helper, subcommand = argv[1], argv[2]
    if not helper.endswith("-helper") or not performance.IDENTIFIER.fullmatch(helper):
        return None
    if subcommand.startswith("-") or not performance.IDENTIFIER.fullmatch(subcommand):
        return None
    return helper, subcommand


def command_identity(command: dict) -> tuple | None:
    """Prefer argv, else the summarized command/subcommand pair."""
    identity = helper_identity(command)
    if identity is not None:
        return identity
    helper = command.get("command")
    subcommand = command.get("subcommand")
    if (isinstance(helper, str) and helper.endswith("-helper")
            and performance.IDENTIFIER.fullmatch(helper)
            and isinstance(subcommand, str)
            and performance.IDENTIFIER.fullmatch(subcommand)):
        return helper, subcommand
    return None


def operation_key(command: dict) -> tuple | None:
    """Identity plus the helper target, so unrelated calls never pair up."""
    identity = command_identity(command)
    if identity is None:
        return None
    return identity + (
        command.get("spec"), command.get("todo_file_hash"), command.get("step"),
    )


def turn_windows(data: dict) -> dict:
    """Host wall-clock interval per collected turn."""
    windows = {}
    turns = data.get("turns") if isinstance(data, dict) else None
    if not isinstance(turns, dict):
        return windows
    for index, metrics in turns.items():
        turn = turn_number(index)
        host = metrics.get("host") if isinstance(metrics, dict) else None
        if turn is None or not isinstance(host, dict):
            continue
        start = performance.timestamp(host.get("started_at"))
        end = performance.timestamp(host.get("ended_at"))
        if start is not None and end is not None:
            windows[turn] = (start, end)
    return windows


def turn_number(value) -> int | None:
    if type(value) is int and value >= 1:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        number = int(value)
        if number >= 1:
            return number
    return None


def recovered_by_retry(index: int, commands: list[dict], windows: dict,
                       turn: int | None) -> bool:
    """A later exit 0 with the same identity inside the same turn window."""
    identity = operation_key(commands[index])
    if identity is None:
        return False
    window = windows.get(turn) if turn is not None else None
    for later in commands[index + 1:]:
        if turn_number(later.get("turn")) != turn:
            continue
        if later.get("exit_code") != 0 or operation_key(later) != identity:
            continue
        if window is not None:
            started = performance.timestamp(later.get("started_at"))
            if started is not None and started > window[1]:
                continue
        return True
    return False


def issue(row: dict, *, stage: str, kind: str, message: str,
          turn: int | None = None, recovered=None, evidence=None,
          command: str | None = None, exit_code: int | None = None) -> dict:
    """Build one issue record shared by observed and recorded diagnostics."""
    return {
        "case": f"{row.get('suite')}/{row.get('case_id')}",
        "trial": row.get("trial"),
        "stage": stage if stage in STAGES else "unknown",
        "kind": kind,
        "message": message,
        "turn": turn,
        "recovered": recovered,
        "evidence": list(evidence or []),
        "command": command,
        "exit_code": exit_code,
    }


def expected_stops(commands: list[dict], metadata: dict) -> set[int]:
    """The one review-command exit a passing review-failure-stop expects."""
    grouped: dict[int | None, list[int]] = {}
    for index, command in enumerate(commands):
        if command.get("command") != "review-helper":
            continue
        if command.get("subcommand") not in {"status", "entry"}:
            continue
        if type(command.get("exit_code")) is not int or command["exit_code"] == 0:
            continue
        grouped.setdefault(turn_number(command.get("turn")), []).append(index)
    stops = set()
    for turn, indexes in grouped.items():
        if len(indexes) != 1:
            continue
        checks = next(
            (item.get("checks") or [] for item in metadata.get("turn_results") or []
             if turn_number(item.get("turn")) == turn),
            [],
        )
        if any(check.get("check_id") == "review-failure-stop"
               and check.get("verdict") == "pass" for check in checks):
            stops.add(indexes[0])
    return stops


def script_issues(row: dict, commands: list[dict], metadata: dict,
                  windows: dict, evidence: list[str]) -> list[dict]:
    stops = expected_stops(commands, metadata)
    issues = []
    for index, command in enumerate(commands):
        name, code = command.get("command"), command.get("exit_code")
        if not isinstance(name, str) or type(code) is not int or code == 0:
            continue
        if index in stops:
            continue
        turn = turn_number(command.get("turn"))
        label = " ".join(filter(None, (name, command.get("subcommand"))))
        prefix = f"Turn {turn}: " if turn is not None else ""
        issues.append(issue(
            row, stage="script", kind="script_exit",
            message=f"{prefix}{label} exited with code {code}",
            turn=turn,
            recovered=recovered_by_retry(index, commands, windows, turn),
            evidence=evidence, command=label, exit_code=code,
        ))
    return issues


def host_issues(row: dict, data: dict, evidence: list[str],
                script_counts: dict) -> list[dict]:
    turns = data.get("turns") if isinstance(data, dict) else None
    if not isinstance(turns, dict):
        return []
    issues = []
    for index, metrics in turns.items():
        host = metrics.get("host") if isinstance(metrics, dict) else None
        if not isinstance(host, dict):
            continue
        turn = turn_number(index)
        prefix = f"Turn {index}: " if turn is not None else ""
        error = host.get("error")
        if isinstance(error, str) and error:
            issues.append(issue(
                row, stage="host", kind="host_error",
                message=f"{prefix}host reported {error}", turn=turn,
                evidence=evidence,
            ))
        gaps = host.get("gaps")
        if isinstance(gaps, list) and "implausible_host_duration" in gaps:
            issues.append(issue(
                row, stage="host", kind="implausible_host_duration",
                message=f"{prefix}host timing does not cover the observed Spex activity",
                turn=turn, evidence=evidence,
            ))
        reported = script_counts.get(turn, 0)
        for key, kind, label in (
            ("command_failures", "command_failures", "host command(s) failed"),
            ("subagent_spawn_failures", "subagent_spawn_failures",
             "subagent spawn(s) failed"),
            ("subagent_failures", "subagent_failures", "subagent(s) failed"),
        ):
            count = performance.nonnegative(host.get(key))
            if key == "command_failures":
                count = None if count is None else max(0, count - reported)
                label = "other host command(s) failed"
            if count:
                issues.append(issue(
                    row, stage="host", kind=kind,
                    message=f"{prefix}{count} {label}", turn=turn,
                    evidence=evidence,
                ))
    return issues


def trial_issues(row: dict, metadata: dict, judge: dict, data: dict) -> list[dict]:
    """Structure host, script, trial, and judge failures as issue records."""
    trial = str(row.get("trial") or ".")
    commands = (row.get("performance") or {}).get("spex_commands") or []
    windows = turn_windows(data)
    performance_evidence = [f"{trial}/performance.json"]
    issues = script_issues(row, commands, metadata, windows, performance_evidence)
    script_counts = {}
    for item in issues:
        if item["turn"] is not None:
            script_counts[item["turn"]] = script_counts.get(item["turn"], 0) + 1
    issues.extend(host_issues(row, data, performance_evidence, script_counts))

    hard = metadata.get("hard_verdict", metadata.get("verdict"))
    error = metadata.get("error")
    if hard == "run_error" or isinstance(error, str) and error:
        reason = error if isinstance(error, str) and error else "run_error"
        issues.append(issue(
            row, stage=str(metadata.get("error_stage") or "unknown"),
            kind="run_error", message=reason,
            evidence=[f"{trial}/trial.json"],
        ))

    attempt_errors = judge.get("attempt_errors")
    failed_judge = judge.get("verdict") == "judge_error" or bool(judge.get("error"))
    if isinstance(attempt_errors, list) and attempt_errors and not failed_judge:
        issues.append(issue(
            row, stage="judge", kind="judge_attempt",
            message=f"Judge retried after {len(attempt_errors)} failed attempt(s)",
            recovered=True, evidence=[f"{trial}/judge.json"],
        ))
    if judge.get("verdict") == "judge_error" or judge.get("error"):
        issues.append(issue(
            row, stage="judge", kind="judge_error",
            message=f"Judge failed ({judge.get('error') or 'judge_error'})",
            evidence=[f"{trial}/judge.json"],
        ))
    return issues
