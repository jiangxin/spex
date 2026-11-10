"""Run isolated Codex turns and normalize their JSONL evidence."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from workspace import Trial

SESSION_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,127}")
SPEX_CALL = re.compile(
    r"(?:^|[\s/])spex['\"]?\s+(apply-helper|review-helper|todo-helper|prompt)\b([^\n]*)"
)
TRIAL_PERMISSIONS = (
    '{":root"="read", ":workspace_roots"={"."="write", ".git"="write", '
    '".agents"="read", ".codex"="read", ".aws"="read"}}'
)


class TransportError(RuntimeError):
    """A host or transport error separate from model behavior."""


@dataclass(frozen=True)
class HostTurn:
    session: str
    reply: str
    events: list
    raw: str


def command_event(item: dict) -> dict:
    command = item.get("command", "")
    matches = list(SPEX_CALL.finditer(command))
    action = "command"
    if len(matches) == 1:
        helper, args = matches[0].groups()
        if helper == "apply-helper" and re.match(r"\s+post-action\b", args):
            action = "apply.post-action"
        elif helper == "review-helper" or helper == "prompt" and "apply-review" in args:
            action = "apply.review"
        else:
            action = "apply.workflow"
    return {"action": action, "exit_code": item.get("exit_code")}


def failure_reason(output: str) -> str:
    message = output.lower()
    if any(word in message for word in ("429", "rate limit", "usage limit")):
        return "rate_limit"
    if any(word in message for word in ("401", "unauthorized", "not logged in", "authentication")):
        return "authentication"
    return "host_error"


def save_host_trace(
    path: Path, raw: str | bytes | None, *, error: str | None = None
) -> None:
    """Retain event order and outcomes without persisting commands or runtime text."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    records = []
    for line in (raw or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            records.append({"type": "invalid_jsonl"})
            continue
        kind = event.get("type") if isinstance(event, dict) else None
        if kind in ("thread.started", "turn.started", "turn.completed", "item.started",
                    "item.updated", "item.completed", "turn.failed", "error"):
            record = {"type": kind}
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "command_execution":
                command = item.get("command")
                code = item.get("exit_code")
                record["action"] = (
                    command_event({"command": command})["action"]
                    if isinstance(command, str) else "command"
                )
                record["exit_code"] = code if type(code) is int else None
            records.append(record)
        else:
            records.append({"type": "unknown_event"})
    if error is not None:
        records.append({"type": "transport_error", "reason": error})
    if records:
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def parse_events(raw: str, expected: str = "") -> HostTurn:
    session = ""
    reply = ""
    events = []
    finished = False
    try:
        for line in raw.splitlines():
            event = json.loads(line)
            kind = event["type"]
            if kind in ("error", "turn.failed"):
                raise TransportError(failure_reason(line))
            if kind == "thread.started":
                session = event["thread_id"]
            elif kind == "turn.completed":
                finished = True
            elif kind == "item.completed":
                item = event["item"]
                if item["type"] == "agent_message":
                    reply = item["text"]
                elif item["type"] == "command_execution":
                    events.append(command_event(item))
                elif item["type"] in ("file_change", "mcp_tool_call", "collab_tool_call"):
                    events.append({"action": item["type"]})
        if not SESSION_ID.fullmatch(session) or expected and expected != session:
            raise TransportError("session_mismatch")
        if not finished or not isinstance(reply, str) or not reply.strip():
            raise TransportError("incomplete_turn")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise TransportError("invalid_jsonl") from error
    return HostTurn(session, reply, events, raw)


def codex_turn(
    trial: Trial, prompt: str, model: str, timeout: int, session: str = "",
    *, trace_path: Path | None = None,
) -> HostTurn:
    env = trial.env
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", os.defpath)
    env["CODEX_HOME"] = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    codex = os.environ.get("SPEX_EVAL_CODEX", "codex")
    command = [codex, "-a", "never", "exec"]
    command += ["resume", session] if session else []
    command += [
        "--ignore-user-config", "--ignore-rules", "--json", "-m", model,
        "-c", 'default_permissions="spex-eval-trial"',
        "-c", f"permissions.spex-eval-trial.filesystem={TRIAL_PERMISSIONS}",
        "-c", "permissions.spex-eval-trial.network.enabled=false",
        "-c", "allow_login_shell=false",
        "-c", "features.shell_snapshot=false",
        "-c", 'shell_environment_policy.inherit="none"',
    ]
    for name in ("HOME", "PATH", "TMPDIR", "TMPPREFIX", "SPEX_CONFIG_FILE", "GIT_CONFIG_GLOBAL",
                 "GIT_CONFIG_NOSYSTEM", "GIT_ATTR_NOSYSTEM", "PYTHONNOUSERSITE"):
        command += ["-c", f"shell_environment_policy.set.{name}={json.dumps(env[name])}"]
    try:
        result = subprocess.run(
            [*command, "-"], input=prompt, cwd=trial.repo, env=env,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as error:
        if trace_path is not None:
            save_host_trace(trace_path, error.stdout, error="timeout")
        raise TransportError("timeout") from error
    except OSError as error:
        raise TransportError("host_unavailable") from error
    failure = failure_reason(result.stderr + result.stdout) if result.returncode else None
    if trace_path is not None:
        save_host_trace(trace_path, result.stdout, error=failure)
    if failure:
        raise TransportError(failure)
    return parse_events(result.stdout, session)


def host_version() -> str:
    try:
        result = subprocess.run(
            [os.environ.get("SPEX_EVAL_CODEX", "codex"), "--version"],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TransportError("host_unavailable") from error
    return result.stdout.strip()
