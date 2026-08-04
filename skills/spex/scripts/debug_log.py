"""Script execution tracing for spex CLI subcommands."""

from __future__ import annotations

import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from common import find_matching_specs, local_iso_timestamp, logger
from config import get_project_context

MAX_STREAM_BYTES = 256 * 1024
DEBUG_LOG_NAME = "debug.log"
SESSIONS_DIR_NAME = "sessions"
ACTIVE_SESSION_FILENAME = "active"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_session_id(session_id: str) -> str:
    """Return a safe session id or raise ``ValueError``.

    Rejects empty values, ``.`` / ``..``, path separators, the reserved
    active-pointer name (case-insensitive), and any id that is not in the
    ``[A-Za-z0-9._-]+`` allowlist.
    """
    cleaned = (session_id or "").strip()
    if not cleaned:
        raise ValueError("session_id must be non-empty")
    if cleaned in {".", ".."}:
        raise ValueError(f"invalid session_id: {session_id!r}")
    if "/" in cleaned or "\\" in cleaned or "\0" in cleaned:
        raise ValueError(f"invalid session_id: {session_id!r}")
    if not _SESSION_ID_RE.fullmatch(cleaned):
        raise ValueError(f"invalid session_id: {session_id!r}")
    if cleaned.casefold() == ACTIVE_SESSION_FILENAME.casefold():
        raise ValueError(
            f"session_id is reserved for the active pointer: {session_id!r}"
        )
    return cleaned


def debug_enabled(argv: list[str]) -> bool:
    """Return True if CLI debug flag or config.debug is enabled."""
    if "-d" in argv or "--debug" in argv:
        return True
    ctx = get_project_context()
    return bool(ctx.config.get("debug"))


def parse_name_from_argv(argv: list[str]) -> str | None:
    """Parse --name or --name= from argv."""
    for index, arg in enumerate(argv):
        if arg == "--name" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--name="):
            return arg.split("=", 1)[1]
    return None


def sessions_dir(spex_root: str | Path) -> Path:
    """Return ``<spex_root>/sessions``."""
    return Path(spex_root) / SESSIONS_DIR_NAME


def active_session_path(spex_root: str | Path) -> Path:
    """Return the active-session pointer file path."""
    return sessions_dir(spex_root) / ACTIVE_SESSION_FILENAME


def session_debug_log_path(spex_root: str | Path, session_id: str) -> Path:
    """Return ``<spex_root>/sessions/<session_id>/debug.log``.

    Validates ``session_id`` and asserts the resolved path stays under
    ``sessions_dir(spex_root)``.
    """
    safe_id = validate_session_id(session_id)
    base = sessions_dir(spex_root).resolve()
    path = (base / safe_id / DEBUG_LOG_NAME).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f"session path escapes sessions dir: {session_id!r}"
        ) from exc
    return path


def get_active_session_id(spex_root: str | Path) -> str | None:
    """Read the active create-session id from the pointer file."""
    pointer = active_session_path(spex_root)
    if not pointer.is_file():
        return None
    try:
        session_id = pointer.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.debug("Failed to read active session pointer %s: %s", pointer, exc)
        return None
    if not session_id:
        return None
    try:
        return validate_session_id(session_id)
    except ValueError:
        logger.debug("Ignoring invalid active session id %r", session_id)
        return None


def set_active_session(spex_root: str | Path, session_id: str) -> None:
    """Write ``session_id`` as the active create-session pointer."""
    safe_id = validate_session_id(session_id)
    pointer = active_session_path(spex_root)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(f"{safe_id}\n", encoding="utf-8")


def clear_active_session(spex_root: str | Path) -> None:
    """Remove the active create-session pointer if present."""
    pointer = active_session_path(spex_root)
    try:
        pointer.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("Failed to clear active session pointer %s: %s", pointer, exc)


def merge_session_log_into_spec(
    spex_root: str | Path,
    session_id: str,
    spec_dir: str | Path,
) -> Path | None:
    """Append session log into ``spec_dir/debug.log``, then delete session log.

    Returns the merged target path when a session log file existed (even if
    empty). Returns ``None`` when there was no session log to merge.
    Does not clear the active-session pointer.
    """
    if not session_id:
        return None

    try:
        session_log = session_debug_log_path(spex_root, session_id)
    except ValueError:
        logger.debug("Ignoring invalid session_id for merge: %r", session_id)
        return None
    session_dir = session_log.parent

    def _rmdir_if_empty() -> None:
        try:
            if session_dir.is_dir() and not any(session_dir.iterdir()):
                session_dir.rmdir()
        except OSError as exc:
            logger.debug("Failed to remove empty session dir %s: %s", session_dir, exc)

    if not session_log.is_file():
        # begin-session creates the dir even when debug is off and no log
        # is written; still best-effort clean the empty session dir.
        _rmdir_if_empty()
        return None

    target = Path(spec_dir) / DEBUG_LOG_NAME
    try:
        content = session_log.read_text(encoding="utf-8")
        if content:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(content)
        session_log.unlink(missing_ok=True)
        _rmdir_if_empty()
    except OSError as exc:
        logger.debug(
            "Failed to merge session log %s into %s: %s",
            session_log,
            target,
            exc,
        )
        return None

    return target


def resolve_debug_log_path(argv: list[str]) -> Path | None:
    """Resolve debug.log with mutual-exclusive routing.

    Priority (runtime never dual-writes):
    1. Unique ``--name`` match → ``<spec_dir>/debug.log`` (ignores session)
    2. Active create session → ``sessions/<id>/debug.log``
    3. Fallback → ``<spex_root>/debug.log``
    """
    ctx = get_project_context()
    if not ctx.spex_root:
        return None

    name = parse_name_from_argv(argv)
    if name:
        specs_dir = Path(ctx.spex_root) / "specs"
        if specs_dir.is_dir():
            matches = find_matching_specs(name, specs_dir)
            if len(matches) == 1:
                return matches[0] / DEBUG_LOG_NAME

    session_id = get_active_session_id(ctx.spex_root)
    if session_id:
        return session_debug_log_path(ctx.spex_root, session_id)

    return Path(ctx.spex_root) / DEBUG_LOG_NAME


class TeeIO:
    """Write-through stream wrapper that captures output up to a byte cap."""

    def __init__(self, stream, parts: list[str], meta: dict) -> None:
        self._stream = stream
        self._parts = parts
        self._meta = meta

    def write(self, data: str) -> int:
        if not data:
            return 0
        self._stream.write(data)
        byte_len = len(data.encode("utf-8", errors="replace"))
        self._meta["total_bytes"] += byte_len
        if self._meta["truncated"]:
            return len(data)

        buffered = self._meta["buffered_bytes"]
        remaining = MAX_STREAM_BYTES - buffered
        if byte_len <= remaining:
            self._parts.append(data)
            self._meta["buffered_bytes"] = buffered + byte_len
        else:
            if remaining > 0:
                encoded = data.encode("utf-8", errors="replace")
                self._parts.append(
                    encoded[:remaining].decode("utf-8", errors="ignore")
                )
                self._meta["buffered_bytes"] = MAX_STREAM_BYTES
            self._meta["truncated"] = True
        return len(data)

    def flush(self) -> None:
        self._stream.flush()

    def fileno(self) -> int:
        return self._stream.fileno()

    def isatty(self) -> bool:
        return self._stream.isatty()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def _format_stream_block(label: str, parts: list[str], meta: dict) -> str:
    content = "".join(parts)
    if meta["truncated"]:
        content += f"\n... [truncated, total {meta['total_bytes']} bytes]"
    return f"----- {label} -----\n{content}\n"


def _append_trace(
    log_path: Path,
    argv: list[str],
    stdout_parts: list[str],
    stdout_meta: dict,
    stderr_parts: list[str],
    stderr_meta: dict,
    exit_code: int,
    duration_ms: int,
) -> None:
    timestamp = local_iso_timestamp()
    argv_text = " ".join(argv)
    block = (
        f"===== BEGIN {timestamp} =====\n"
        f"argv: {argv_text}\n"
        f"{_format_stream_block('stdout', stdout_parts, stdout_meta)}"
        f"{_format_stream_block('stderr', stderr_parts, stderr_meta)}"
        f"===== END exit={exit_code} duration_ms={duration_ms} =====\n"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(block)
    except OSError as exc:
        logger.debug("Failed to write debug log to %s: %s", log_path, exc)


def _normalize_exit_code(code) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    try:
        return int(code)
    except (TypeError, ValueError):
        return 1


@contextmanager
def trace_command(log_path: Path, argv: list[str]) -> Iterator[None]:
    """Context manager that tees stdout/stderr and appends a trace block."""
    start = time.monotonic()
    exit_code = 0
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    stdout_meta = {"buffered_bytes": 0, "total_bytes": 0, "truncated": False}
    stderr_meta = {"buffered_bytes": 0, "total_bytes": 0, "truncated": False}

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = TeeIO(old_stdout, stdout_parts, stdout_meta)
    sys.stderr = TeeIO(old_stderr, stderr_parts, stderr_meta)

    try:
        yield
    except SystemExit as exc:
        exit_code = _normalize_exit_code(exc.code)
        raise
    except BaseException:
        exit_code = 1
        raise
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        duration_ms = int((time.monotonic() - start) * 1000)
        _append_trace(
            log_path,
            argv,
            stdout_parts,
            stdout_meta,
            stderr_parts,
            stderr_meta,
            exit_code,
            duration_ms,
        )
