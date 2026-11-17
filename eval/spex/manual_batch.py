"""Serialize publication and dispatch for a current-host evaluation batch."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from workspace import case_dir


@contextmanager
def locked(sandbox: Path):
    fd = os.open(sandbox / ".manual.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read(path: Path, default=None):
    if path.is_symlink():
        raise ValueError(f"Unexpected linked batch file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def write(path: Path, data: dict) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def check_unpublished_case(sandbox: Path, key: str, entries: dict) -> None:
    if (sandbox / "queue.json").exists():
        raise ValueError("Cannot add cases after the dispatch queue is initialized")
    # The legacy flat reply names use the concatenated suite and case.
    stem = key.replace("/", "-")
    if any(existing.replace("/", "-") == stem for existing in entries):
        raise ValueError(f"Ambiguous handoff filename for {key}")


def check_prepare(sandbox: Path, suite: str, case: str) -> None:
    with locked(sandbox):
        entries = read(sandbox / "batch-index.json", {})
        key = f"{suite}/{case}"
        if key not in entries:
            check_unpublished_case(sandbox, key, entries)


def publish(sandbox: Path, suite: str, case: str, output: Path, environment: dict) -> dict:
    key = f"{suite}/{case}"
    with locked(sandbox):
        path = sandbox / "batch-index.json"
        entries = read(path, {})
        relative = output.relative_to(sandbox).as_posix()
        if relative != key or output != case_dir(sandbox, suite, case):
            raise ValueError(f"Unexpected manual trial directory: {output}")
        if key in entries:
            return entries[key]["environment"]
        check_unpublished_case(sandbox, key, entries)
        entries[key] = {"trial": relative, "environment": environment}
        write(path, entries)
        return environment
