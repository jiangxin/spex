"""Script execution tracing for spex CLI subcommands."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from common import find_matching_specs, local_iso_timestamp, logger
from config import get_project_context

MAX_STREAM_BYTES = 256 * 1024
DEBUG_LOG_NAME = "debug.log"


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


def resolve_debug_log_path(argv: list[str]) -> Path | None:
    """Resolve debug.log path under spec dir or spex_root fallback."""
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
