#!/usr/bin/env python3
"""Hooks system for spex CLI — find and execute hook scripts."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common import _resolve_hook_roots, get_current_workdir


def find_hook(hook_name: str, workdir=None) -> Path | None:
    """Find the first executable hook file in priority order.

    Args:
        hook_name: Hook filename (e.g. "post-action").
        workdir: Working directory for spex_root resolution.

    Returns:
        Path to the first executable hook found, or None.
    """
    for root in _resolve_hook_roots(workdir):
        candidate = root / hook_name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _build_event_data(event_type: str, payload: dict, workdir=None) -> dict:
    """Build the JSON event envelope from git config and payload.

    Args:
        event_type: The spex command that triggered this hook.
        payload: Command-specific audit information.
        workdir: Working directory for git config lookup.

    Returns:
        Dict with user, email, workdir, event_type, and payload fields.
    """
    def _git_config(key: str) -> str:
        r = subprocess.run(
            ["git", "config", key],
            capture_output=True, text=True, cwd=workdir,
        )
        return r.stdout.strip()

    return {
        "user": _git_config("user.name"),
        "email": _git_config("user.email"),
        "workdir": str(workdir or get_current_workdir() or Path.cwd()),
        "event_type": event_type,
        "time": datetime.now().astimezone().isoformat(),
        "payload": payload,
    }


def run_hook(hook_name: str, event_data: dict, workdir=None) -> None:
    """Find and execute a hook, piping JSON event data to stdin.

    If no hook is found, returns silently.
    If the hook fails (non-zero exit), logs error to stderr.

    Args:
        hook_name: Hook filename to search for.
        event_data: JSON-serializable event envelope.
        workdir: Working directory for hook execution.
    """
    hook_path = find_hook(hook_name, workdir)
    if hook_path is None:
        return

    payload = json.dumps(event_data)
    result = subprocess.run(
        [str(hook_path)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=workdir,
    )
    if result.returncode != 0:
        print(
            f"Hook '{hook_name}' exited with code {result.returncode}:\n"
            f"stderr: {result.stderr.strip()}",
            file=sys.stderr,
        )


def run_post_action(event_type: str, payload: dict, workdir=None,
                    topic_name: str | None = None) -> None:
    """Convenience wrapper to run the post-action hook.

    Args:
        event_type: The spex command that triggered this hook.
        payload: Command-specific audit information.
        workdir: Working directory for hook execution.
        topic_name: Optional topic name added to the payload.
    """
    if topic_name:
        payload = {**payload, "topic_name": topic_name}
    data = _build_event_data(event_type, payload, workdir)
    run_hook("post-action", data, workdir)
