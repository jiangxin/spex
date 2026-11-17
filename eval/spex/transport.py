"""Run isolated Codex turns and normalize their JSONL evidence."""

from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from performance import IDENTIFIER
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

    def __init__(self, reason: str, *, partial_events: str | bytes | None = None):
        super().__init__(reason)
        self.partial_events = partial_events


@dataclass(frozen=True)
class HostTurn:
    session: str
    reply: str
    events: list
    raw: str


@dataclass(frozen=True)
class CodexRuntime:
    binary: str
    home: Path
    version: str


def command_event(item: dict) -> dict:
    command = item.get("command", "")
    matches = list(SPEX_CALL.finditer(command))
    action = "command"
    if shell_command(command) == "git rev-parse --short HEAD":
        action = "git.read-head"
    if len(matches) == 1:
        helper, args = matches[0].groups()
        if helper == "apply-helper" and re.match(r"\s+post-action\b", args):
            action = "apply.post-action"
        elif helper == "review-helper" or helper == "prompt" and "apply-review" in args:
            action = "apply.review-command"
        else:
            action = "apply.workflow"
    event = {"action": action, "exit_code": item.get("exit_code")}
    if action == "apply.post-action":
        spec = post_action_target(command)
        if spec is not None:
            event["spec"] = spec
    elif action == "apply.review-command":
        event.update(review_arguments(command))
        if helper == "prompt" and event.get("spec") and event["exit_code"] == 0:
            output = item.get("aggregated_output", "")
            if isinstance(output, str):
                for line in reversed(output.splitlines()):
                    if not line.lstrip().startswith("{"):
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(payload, dict) and payload.get("skipped") is True:
                        event["skipped"] = True
                    break
    return event


def shell_command(command: str) -> str:
    """Unwrap the shell invocation reported by Codex."""
    try:
        words = shlex.split(command)
    except ValueError:
        return ""
    if (len(words) == 3 and Path(words[0]).name in {"bash", "sh", "zsh"}
            and words[1] in {"-c", "-lc"}):
        return words[2]
    return command


def post_action_target(command: str) -> str | None:
    """Extract the target of a standalone Spex post-action command."""
    line = shell_command(command)
    if len(line.splitlines()) != 1:
        return None
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        return None
    if (len(words) not in {4, 5} or Path(words[0]).name != "spex"
            or words[1:3] != ["apply-helper", "post-action"]):
        return None
    if len(words) == 5:
        if words[3] != "--name":
            return None
        target = words[4]
    else:
        target = words[3].removeprefix("--name=")
    return target if IDENTIFIER.fullmatch(target) else None


def review_arguments(command: str) -> dict:
    line, newline, body = shell_command(command).partition("\n")
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        return {}
    if any(re.fullmatch(r"[();<>|&]+", word) and word not in {"<<", "<<-"} for word in words):
        return {}
    if newline:
        if len(words) < 2 or words[-2] != "<<" or not body.rstrip("\n").endswith("\n" + words[-1]):
            return {}
    if len(words) < 3 or Path(words[0]).name != "spex":
        return {}
    options = {
        "--name": "spec", "--commit": "commit", "--mode": "mode", "--step": "step",
        "--base-commit": "base_commit", "--new-commit": "new_commit",
        "--output": None, "-o": None, "--spex-root": None, "--workdir": None,
        "--ids": None, "--evidence": None,
    }
    if words[1:3] == ["prompt", "apply-review"]:
        stage = "prompt"
        words = words[3:]
    elif words[1] == "review-helper":
        stage = next((word for word in words[2:]
                      if word in {"status", "entry", "complete-batch", "finish-pass"}), None)
        if stage is None:
            return {}
        words = words[2:]
        words.remove(stage)
    else:
        return {}
    result = {"stage": stage}
    args = iter(words)
    for word in args:
        flag, separator, value = word.partition("=")
        if flag in options:
            value = value if separator else next(args, "")
            if value and options[flag]:
                result[options[flag]] = value
        elif not word.startswith("-") and word not in {"<<", "<<-"}:
            result.setdefault("spec", word)
    return result


def failure_reason(output: str) -> str:
    message = output.lower()
    if any(word in message for word in ("429", "rate limit", "usage limit")):
        return "rate_limit"
    if any(word in message for word in ("401", "unauthorized", "not logged in", "authentication",
                                        "not authenticated", "login required")):
        return "authentication"
    if any(word in message for word in (
        "app-server", "app server", "appserver", "failed to initialize", "initialize app",
    )):
        return "app_server_init"
    if any(word in message for word in (
        "goals_", ".sqlite", "operation not permitted", "permission denied", "read-only file",
    )):
        return "state_dir_unwritable"
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


def codex_binary() -> str:
    return os.environ.get("SPEX_EVAL_CODEX", "codex")


def ensure_state_home(path: Path) -> Path:
    """Create a writable Codex state directory or raise a classified error."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".spex-eval-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        database = path / "goals_probe.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("create table if not exists probe (id integer primary key)")
        database.unlink(missing_ok=True)
    except OSError as error:
        raise TransportError("state_dir_unwritable") from error
    return path.resolve()


def resolve_codex_home(preferred: Path | None = None) -> Path:
    candidates = []
    override = os.environ.get("SPEX_EVAL_CODEX_HOME")
    if override:
        candidates.append(Path(override))
    if preferred is not None:
        candidates.append(Path(preferred))
    configured = os.environ.get("CODEX_HOME")
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path(tempfile.gettempdir()) / "spex-eval-codex-home")
    errors = []
    for candidate in candidates:
        try:
            return ensure_state_home(candidate)
        except TransportError as error:
            errors.append(error)
    raise errors[-1] if errors else TransportError("state_dir_unwritable")


def host_version(binary: str | None = None) -> str:
    try:
        result = subprocess.run(
            [binary or codex_binary(), "--version"],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TransportError("host_unavailable") from error
    return result.stdout.strip() or "unknown"


def probe_app_server(runtime: CodexRuntime, timeout: int = 20) -> None:
    """Exercise app-server startup without running a full scored trial turn."""
    env = os.environ.copy()
    env["CODEX_HOME"] = str(runtime.home)
    command = [
        runtime.binary, "-a", "never", "exec", "--json", "--ephemeral",
        "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
        "-s", "read-only", "--disable", "shell_tool",
        "-c", 'web_search="disabled"',
        "-c", 'shell_environment_policy.inherit="none"',
        "-",
    ]
    try:
        result = subprocess.run(
            command, input="Reply with OK.", cwd=tempfile.gettempdir(), env=env,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TransportError("app_server_init") from error
    except OSError as error:
        raise TransportError("host_unavailable") from error
    output = result.stderr + result.stdout
    if result.returncode == 0:
        return
    reason = failure_reason(output)
    if reason == "host_error":
        reason = "app_server_init"
    raise TransportError(reason)


def prepare_codex_runtime(
    preferred_home: Path | None = None, *, probe: bool = True, timeout: int = 20,
) -> CodexRuntime:
    """Shared startup preflight for trial execution and judging."""
    binary = codex_binary()
    version = host_version(binary)
    home = resolve_codex_home(preferred_home)
    runtime = CodexRuntime(binary, home, version)
    if probe:
        probe_app_server(runtime, timeout=timeout)
    return runtime


def codex_env(trial: Trial | None, runtime: CodexRuntime) -> dict[str, str]:
    if trial is None:
        env = os.environ.copy()
    else:
        env = trial.env
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", os.defpath)
    env["CODEX_HOME"] = str(runtime.home)
    return env


def codex_turn(
    trial: Trial, prompt: str, model: str, timeout: int, session: str = "",
    *, trace_path: Path | None = None, runtime: CodexRuntime | None = None,
) -> HostTurn:
    if runtime is None:
        runtime = CodexRuntime(
            codex_binary(), resolve_codex_home(trial.directory / "codex-home"), "unknown",
        )
    env = codex_env(trial, runtime)
    command = [runtime.binary, "-a", "never", "exec"]
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
        raise TransportError("timeout", partial_events=error.stdout) from error
    except OSError as error:
        raise TransportError("host_unavailable") from error
    failure = failure_reason(result.stderr + result.stdout) if result.returncode else None
    if trace_path is not None:
        save_host_trace(trace_path, result.stdout, error=failure)
    if failure:
        raise TransportError(failure, partial_events=result.stdout)
    try:
        return parse_events(result.stdout, session)
    except TransportError as error:
        error.partial_events = result.stdout
        raise
