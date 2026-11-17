"""Script execution tracing for spex CLI subcommands."""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Iterator

from common import find_matching_specs, local_iso_timestamp, logger
from config import get_project_storage, load_config

MAX_STREAM_BYTES = 256 * 1024
PROMPT_STDOUT_LOG_BYTES = 2 * 1024
DEBUG_LOG_NAME = "debug.log"
TRACE_JSONL_NAME = "trace.jsonl"
SESSIONS_DIR_NAME = "sessions"
ACTIVE_SESSION_FILENAME = "active"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_PROMPT_SUMMARY_KEYS = (
    "task_id",
    "commit_sha",
    "review_round",
    "all_done",
    "skipped",
    "step_id",
    "resume_phase",
    "commit_title",
)


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
    return bool(load_config().get("debug"))


def append_debug_anchor(log_path: Path, line: str) -> None:
    """Append a timeline anchor best-effort (APPLY/tee); swallow OSError.

    CREATE prepare/post-action anchors use a raising writer in
    ``create_helper`` instead — do not route those through this helper.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        text = line if line.endswith("\n") else f"{line}\n"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as exc:
        logger.debug("Failed to write debug anchor to %s: %s", log_path, exc)


def emit_apply_anchor(
    spec_dir: str | Path,
    line: str,
    argv: list[str] | None = None,
) -> None:
    """Append an APPLY timeline anchor when debug is enabled."""
    if not debug_enabled(argv if argv is not None else sys.argv):
        return
    append_debug_anchor(Path(spec_dir) / DEBUG_LOG_NAME, line)


# ---------------------------------------------------------------------------
# Structured review-flow telemetry (helper-owned APPLY anchors)
# ---------------------------------------------------------------------------

APPLY_SPAN_KINDS = ("review", "fix", "checks")
APPLY_ROUTE_RESULTS = (
    "phase7_no_findings",
    "batch_fix",
    "minor_direct_complete",
    "major_delta",
    "new_major_next_full_round",
    "hard_cap_batch_fix",
)


def _format_apply_field_value(value) -> str:
    """Serialize a field value for an APPLY anchor line."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value if v is not None and str(v))
    if value is None:
        return ""
    return str(value)


def format_apply_event(event: str, **fields) -> str:
    """Build ``===== APPLY <event> [k=v ...] =====`` without a trailing newline.

    Field order follows insertion order. Empty values are omitted so anchors
    stay skim-friendly. ``event`` is the free-form middle token sequence
    (e.g. ``review begin``, ``fix end``, ``route result=major_delta``).
    """
    parts = [f"===== APPLY {event}"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)) and not value:
            continue
        parts.append(f"{key}={_format_apply_field_value(value)}")
    return " ".join(parts) + " ====="


def emit_apply_task(spec_dir: str | Path, event: str, **fields) -> None:
    emit_apply_anchor(spec_dir, format_apply_event(f"task {event}", **fields, ts=apply_timestamp()))


def apply_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def apply_span_state_path(spec_dir: str | Path) -> Path:
    """Sidecar path for open review-flow spans beside ``debug.log``."""
    return Path(spec_dir) / f"{DEBUG_LOG_NAME}.apply_span"


def read_apply_spans(spec_dir: str | Path) -> dict:
    """Load open span map ``{kind: {...}}``; empty dict on missing/invalid."""
    path = apply_span_state_path(spec_dir)
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def has_open_apply_span(spec_dir: str | Path, kind: str) -> bool:
    """True when an open span of ``kind`` exists beside the debug log."""
    return kind in read_apply_spans(spec_dir)


def _write_apply_spans(spec_dir: str | Path, spans: dict) -> None:
    """Persist open span map; delete sidecar when empty."""
    path = apply_span_state_path(spec_dir)
    try:
        if not spans:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(spans, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.debug("Failed to write apply span state %s: %s", path, exc)


def start_apply_span(
    spec_dir: str | Path,
    kind: str,
    *,
    argv: list[str] | None = None,
    emit_begin: bool = True,
    **fields,
) -> dict | None:
    """Record a review-flow span start and optionally emit a begin anchor.

    Returns the span dict when debug is enabled; ``None`` when skipped.
    Replaces any existing open span of the same ``kind``.
    """
    if kind not in APPLY_SPAN_KINDS:
        raise ValueError(f"unknown apply span kind: {kind!r}")
    if not debug_enabled(argv if argv is not None else sys.argv):
        return None

    started_at = apply_timestamp()
    span = {
        "kind": kind,
        "started_at": started_at,
        "started_mono": time.monotonic(),
        **{k: v for k, v in fields.items() if v is not None and v != ""},
    }
    spans = read_apply_spans(spec_dir)
    spans[kind] = span
    _write_apply_spans(spec_dir, spans)

    if emit_begin:
        emit_fields = {
            "ts": started_at,
            **{k: v for k, v in fields.items() if k != "started_mono"},
        }
        emit_apply_anchor(
            spec_dir,
            format_apply_event(f"{kind} begin", **emit_fields),
            argv=argv if argv is not None else sys.argv,
        )
    return span


def end_apply_span(
    spec_dir: str | Path,
    kind: str,
    *,
    argv: list[str] | None = None,
    duration_ms: int | None = None,
    **fields,
) -> dict | None:
    """Close an open span, emit an end anchor with ``duration_ms``, and clear it.

    Returns the closed span (including ``duration_ms``) when one was open and
    debug is enabled; ``None`` when skipped or no matching open span.
    """
    if kind not in APPLY_SPAN_KINDS:
        raise ValueError(f"unknown apply span kind: {kind!r}")
    if not debug_enabled(argv if argv is not None else sys.argv):
        return None

    spans = read_apply_spans(spec_dir)
    span = spans.pop(kind, None)
    if span is None:
        return None
    _write_apply_spans(spec_dir, spans)

    ended_at = apply_timestamp()
    if duration_ms is None:
        started_mono = span.get("started_mono")
        if isinstance(started_mono, (int, float)):
            duration_ms = max(0, int((time.monotonic() - started_mono) * 1000))
        else:
            duration_ms = 0

    # Prefer end-call fields; fall back to begin-span metadata for continuity.
    merged = {
        k: v
        for k, v in span.items()
        if k not in {"kind", "started_at", "started_mono"}
    }
    merged.update({k: v for k, v in fields.items() if v is not None and v != ""})
    merged["ts"] = ended_at
    merged["duration_ms"] = duration_ms

    emit_apply_anchor(
        spec_dir,
        format_apply_event(f"{kind} end", **merged),
        argv=argv if argv is not None else sys.argv,
    )
    return merged


def emit_apply_route(
    spec_dir: str | Path,
    result: str,
    *,
    argv: list[str] | None = None,
    **fields,
) -> None:
    """Emit a route-decision anchor (helper-owned; no agent prose)."""
    if result not in APPLY_ROUTE_RESULTS:
        logger.debug("Unknown apply route result: %s", result)
    emit_apply_anchor(
        spec_dir,
        format_apply_event(
            "route",
            ts=local_iso_timestamp(),
            result=result,
            **fields,
        ),
        argv=argv if argv is not None else sys.argv,
    )


def sum_check_evidence_duration_ms(evidence: dict | None) -> int:
    """Sum optional per-check ``duration_ms`` from check_evidence; else 0."""
    if not isinstance(evidence, dict):
        return 0
    total = 0
    for item in evidence.get("checks") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("duration_ms")
        if type(value) is int and value >= 0:
            total += value
    return total


def parse_name_from_argv(argv: list[str]) -> str | None:
    """Parse helper selectors without dispatching or resolving a spec."""
    for index, arg in enumerate(argv):
        if index == 0 and (arg == "spex" or arg.endswith("/spex")):
            continue
        if arg in {"-d", "--debug", "-V", "--version", "-h", "--help"}:
            continue
        command = arg.replace("_", "-")
        if command in {
            "create-helper", "apply-helper", "todo-helper", "review-helper", "prompt",
            "archive", "run-hook",
        }:
            return _parse_helper_selector(command, argv[index + 1:])
        break
    return None


def _parse_helper_selector(command: str, argv: list[str]) -> str | None:
    if command == "create-helper":
        from create_helper import _build_parser
    elif command == "apply-helper":
        from apply_helper import _build_parser
    elif command == "todo-helper":
        from todo_helper import _build_parser
    elif command == "review-helper":
        from review_helper import _build_parser

    try:
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            if command == "prompt":
                from prompt import _parse_args as parse_prompt

                args = parse_prompt(argv)
            elif command == "archive":
                from archive import _parse_args as parse_archive

                args = parse_archive(argv)
            elif command == "run-hook":
                from cli import parse_run_hook_args

                args = parse_run_hook_args(argv)
            elif command == "todo-helper":
                from todo_helper import _parse_args as parse_todo

                args = parse_todo(_build_parser(), argv)
            else:
                args = _build_parser().parse(argv)
    except SystemExit:
        return None
    return getattr(args, "name", None)


def parse_flag_from_argv(argv: list[str], flag: str) -> str | None:
    """Parse ``--flag value`` or ``--flag=value`` from argv."""
    equals_prefix = f"{flag}="
    for index, arg in enumerate(argv):
        if arg == flag and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(equals_prefix):
            return arg.split("=", 1)[1]
    return None


def is_prompt_argv(argv: list[str]) -> bool:
    """Return True if argv is a ``spex prompt ...`` invocation."""
    for arg in argv:
        if arg in {"-d", "--debug", "-V", "--version", "-h", "--help"}:
            continue
        if arg == "spex" or arg.endswith("/spex"):
            continue
        return arg == "prompt"
    return False


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

    Moves the default JSONL trace alongside the debug log.
    Also relocates the session ``.prev_end`` sidecar onto the target log when
    content was merged (so post-merge ``gap_ms`` continues), and always removes
    the session sidecar so the empty session directory can be cleaned up.

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
    _merge_session_trace(session_dir, Path(spec_dir))

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

        # gap_ms sidecar lives beside the log; move it with merged content so
        # the session dir is empty enough for _rmdir_if_empty, and the first
        # post-merge trace on the spec log can still emit gap_ms.
        session_sidecar = _prev_end_state_path(session_log)
        if session_sidecar.is_file():
            try:
                if content:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    session_sidecar.replace(_prev_end_state_path(target))
                else:
                    session_sidecar.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug(
                    "Failed to relocate/remove session prev_end %s: %s",
                    session_sidecar,
                    exc,
                )
                try:
                    session_sidecar.unlink(missing_ok=True)
                except OSError:
                    pass

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


def _merge_session_trace(session_dir: Path, spec_dir: Path) -> None:
    source = session_dir / TRACE_JSONL_NAME
    if not source.is_file():
        return
    target = spec_dir / TRACE_JSONL_NAME
    try:
        spec_dir.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as incoming, target.open("ab") as output:
            snapshot = os.fstat(incoming.fileno())
            if os.path.samestat(snapshot, os.fstat(output.fileno())):
                return
            remaining = snapshot.st_size
            while remaining:
                chunk = incoming.read(min(remaining, 64 * 1024))
                if not chunk:
                    break
                output.write(chunk)
                remaining -= len(chunk)
        source.unlink()
    except OSError as exc:
        logger.debug("Failed to merge session trace %s into %s: %s", source, target, exc)


def _configured_log_dir() -> Path | None:
    value = os.environ.get("SPEX_LOG_DIR", "").strip()
    if not value:
        return None
    try:
        return Path(value).expanduser()
    except RuntimeError as exc:
        logger.debug("Failed to expand SPEX_LOG_DIR: %s", exc)
        return None


def resolve_debug_log_path(argv: list[str]) -> Path | None:
    """Resolve debug.log with mutual-exclusive routing.

    Priority (runtime never dual-writes); exact-before-fuzzy across both trees:
    1. ``SPEX_LOG_DIR`` → ``<log_dir>/debug.log``
    2. Exact selector in ``specs/`` → ``<spec_dir>/debug.log``
    3. Exact selector in ``archives/`` → ``<archived_dir>/debug.log``
    4. Unique fuzzy selector in ``specs/`` → ``<spec_dir>/debug.log``
    5. Unique fuzzy selector in ``archives/`` → ``<archived_dir>/debug.log``
    6. Active create session → ``sessions/<id>/debug.log``
    7. Fallback → ``<spex_root>/debug.log``
    """
    log_dir = _configured_log_dir()
    if log_dir is not None:
        return log_dir / DEBUG_LOG_NAME

    ctx = get_project_storage()
    if not ctx.spex_root:
        return None

    name = parse_name_from_argv(argv)
    if name:
        spex_root = Path(ctx.spex_root)
        specs_dir = spex_root / "specs"
        archives_dir = spex_root / "archives"

        exact_specs = specs_dir / name
        if exact_specs.is_dir():
            return exact_specs / DEBUG_LOG_NAME

        exact_archives = archives_dir / name
        if exact_archives.is_dir():
            return exact_archives / DEBUG_LOG_NAME

        if specs_dir.is_dir():
            matches = find_matching_specs(name, specs_dir)
            if len(matches) == 1:
                return matches[0] / DEBUG_LOG_NAME

        if archives_dir.is_dir():
            matches = find_matching_specs(name, archives_dir)
            if len(matches) == 1:
                return matches[0] / DEBUG_LOG_NAME

    session_id = get_active_session_id(ctx.spex_root)
    if session_id:
        return session_debug_log_path(ctx.spex_root, session_id)

    return Path(ctx.spex_root) / DEBUG_LOG_NAME


def resolve_trace_file_path(debug_path: Path | None) -> Path | None:
    """Resolve the trace destination, preferring environment over config."""
    log_dir = _configured_log_dir()
    env_path = os.environ.get("SPEX_TRACE_FILE", "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        return log_dir / path if log_dir is not None else path

    ctx = get_project_storage()
    configured = str(ctx.config.get("trace_file") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_absolute():
            return path
        if log_dir is not None:
            return log_dir / path
        if ctx.spex_root:
            return Path(ctx.spex_root) / path
        return None
    if log_dir is not None:
        return log_dir / TRACE_JSONL_NAME
    return debug_path.with_name(TRACE_JSONL_NAME) if debug_path is not None else None


def safe_flush_debug_log_path(
    argv: list[str],
    pre_resolved: Path | None,
) -> Path | None:
    """Choose a post-command flush path that never recreates specs stubs.

    Selection:
    1. Post-command ``resolve_debug_log_path`` when available
    2. ``pre_resolved`` only if its parent directory still exists
    3. ``<spex_root>/debug.log`` when spex_root is configured
    4. ``None`` to skip the flush
    """
    resolved = resolve_debug_log_path(argv)
    if resolved is not None:
        return resolved

    if pre_resolved is not None and pre_resolved.parent.is_dir():
        return pre_resolved

    ctx = get_project_storage()
    if ctx.spex_root:
        return Path(ctx.spex_root) / DEBUG_LOG_NAME
    return None


def _is_under_specs_tree(path: Path) -> bool:
    """Return True if ``path`` lies under ``<spex_root>/specs`` (may be missing).

    Uses path structure relative to configured ``spex_root``, so the check
    still holds when the entire ``specs/`` directory has vanished.
    """
    ctx = get_project_storage()
    if ctx.spex_root:
        specs_root = Path(ctx.spex_root) / "specs"
        try:
            path.resolve(strict=False).relative_to(specs_root.resolve(strict=False))
            return True
        except ValueError:
            return False
    # No spex_root: refuse classic ``.../specs/<name>/`` parents.
    return path.parent.name == "specs"


def _prepare_debug_log_parent(log_path: Path) -> bool:
    """Ensure ``log_path`` parent exists; never recreate vanished specs dirs.

    Returns False when the write should be skipped.
    """
    parent = log_path.parent
    if parent.is_dir():
        return True

    # Refuse mkdir for any missing parent under specs/, even if specs/ itself
    # is absent. Never mkdir(parents=True) for a missing parent under specs/.
    if _is_under_specs_tree(parent):
        logger.debug(
            "Refusing to recreate vanished specs debug log parent: %s",
            parent,
        )
        return False

    try:
        parent.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        logger.debug("Failed to create debug log parent %s: %s", parent, exc)
        return False


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


def _summarize_prompt_stdout(content: str, total_bytes: int) -> str:
    """Return a skim-friendly prompt stdout for debug.log (not caller stdout)."""
    stripped = content.strip()
    if stripped:
        try:
            data = json.loads(stripped)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            bits = [f"total={total_bytes}B"]
            keys = sorted(str(k) for k in data.keys())
            bits.append(f"keys={','.join(keys)}")
            for key in _PROMPT_SUMMARY_KEYS:
                if key not in data:
                    continue
                bits.append(f"{key}={data[key]!s}")
            prompt_val = data.get("prompt")
            if isinstance(prompt_val, str):
                prompt_len = len(prompt_val.encode("utf-8", errors="replace"))
                bits.append(f"prompt_len={prompt_len}")
            return (
                f"[truncated prompt stdout, {'; '.join(bits)}]\n"
            )

    encoded = content.encode("utf-8", errors="replace")
    if len(encoded) <= PROMPT_STDOUT_LOG_BYTES:
        if total_bytes > len(encoded):
            return (
                f"{content}"
                f"\n... [truncated prompt stdout, total={total_bytes}B]\n"
            )
        return content
    head = encoded[:PROMPT_STDOUT_LOG_BYTES].decode("utf-8", errors="ignore")
    return f"{head}\n... [truncated prompt stdout, total={total_bytes}B]\n"


def _format_stdout_for_log(
    argv: list[str], parts: list[str], meta: dict
) -> str:
    """Format stdout for the log; summarize/truncate prompt commands only."""
    if is_prompt_argv(argv):
        content = "".join(parts)
        summarized = _summarize_prompt_stdout(content, meta["total_bytes"])
        return f"----- stdout -----\n{summarized}\n"
    return _format_stream_block("stdout", parts, meta)


def _parse_iso_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _prev_end_state_path(log_path: Path) -> Path:
    """Sidecar path for the last flushed block's end timestamp."""
    return Path(str(log_path) + ".prev_end")


def _previous_end_instant(log_path: Path) -> datetime | None:
    """Return previous END wall time for gap_ms.

    BEGIN is stamped at flush time (command end), so that stamp is the END.
    Read it from a sidecar written on each successful flush — never by
    regex-scanning the log body, which can be poisoned by BEGIN/END lines
    embedded in stdout/stderr payloads.
    """
    if not log_path.is_file():
        return None
    state_path = _prev_end_state_path(log_path)
    if not state_path.is_file():
        return None
    try:
        raw = state_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return _parse_iso_timestamp(raw)


def _remember_end_instant(log_path: Path, end: datetime) -> None:
    """Persist last END stamp next to the log for the next gap_ms calculation."""
    state_path = _prev_end_state_path(log_path)
    try:
        state_path.write_text(end.isoformat() + "\n", encoding="utf-8")
    except OSError as exc:
        logger.debug("Failed to write gap prev_end to %s: %s", state_path, exc)


def _build_meta_line(
    argv: list[str], log_path: Path, now: datetime
) -> str:
    """Build ``meta:`` line with argv fields and gap_ms since previous END."""
    step = parse_flag_from_argv(argv, "--step")
    if step is None:
        step = parse_flag_from_argv(argv, "--id")
    commit = parse_flag_from_argv(argv, "--commit")

    parts: list[str] = []
    if step is not None:
        parts.append(f"step={step}")
    if commit is not None:
        parts.append(f"commit={commit}")

    prev_end = _previous_end_instant(log_path)
    if prev_end is not None:
        gap_ms = max(0, int((now - prev_end).total_seconds() * 1000))
        parts.append(f"gap_ms={gap_ms}")

    if not parts:
        return "meta:\n"
    return f"meta: {' '.join(parts)}\n"


def _append_trace(
    log_path: Path,
    argv: list[str],
    stdout_parts: list[str],
    stdout_meta: dict,
    stderr_parts: list[str],
    stderr_meta: dict,
    exit_code: int,
    duration_ms: int,
) -> str | None:
    timestamp = local_iso_timestamp()
    now = _parse_iso_timestamp(timestamp) or datetime.now().astimezone()
    argv_text = " ".join(argv)
    meta_line = _build_meta_line(argv, log_path, now)
    block = (
        f"===== BEGIN {timestamp} =====\n"
        f"argv: {argv_text}\n"
        f"{meta_line}"
        f"{_format_stdout_for_log(argv, stdout_parts, stdout_meta)}"
        f"{_format_stream_block('stderr', stderr_parts, stderr_meta)}"
        f"===== END exit={exit_code} duration_ms={duration_ms} =====\n"
    )
    if not _prepare_debug_log_parent(log_path):
        return None
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(block)
        _remember_end_instant(log_path, now)
    except OSError as exc:
        logger.debug("Failed to write debug log to %s: %s", log_path, exc)
        return None
    return timestamp


def _normalize_exit_code(code) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    try:
        return int(code)
    except (TypeError, ValueError):
        return 1


def _append_cli_span(
    path: Path, argv: list[str], start_ns: int, end_ns: int,
    duration_ms: int, exit_code: int, debug_logged_at: str | None,
) -> None:
    command = next((arg.replace("_", "-") for arg in argv[1:] if not arg.startswith("-")), "")
    attributes = {
        "process.executable.name": "spex",
        "process.command_args": argv,
        "process.pid": os.getpid(),
        "process.exit.code": exit_code,
    }
    if exit_code:
        attributes["error.type"] = "nonzero_exit"
    span = {
        "schema_version": 1,
        "name": command,
        "kind": "INTERNAL",
        "start_time_unix_nano": start_ns,
        "end_time_unix_nano": end_ns,
        "attributes": attributes,
        "status": {"code": "ERROR" if exit_code else "UNSET"},
        "spex": {
            "subcommand": command,
            "duration_ms": duration_ms,
            "started_at": datetime.fromtimestamp(start_ns / 1e9).astimezone().isoformat(),
            "ended_at": datetime.fromtimestamp(end_ns / 1e9).astimezone().isoformat(),
        },
    }
    if debug_logged_at is not None:
        span["spex"]["debug_logged_at"] = debug_logged_at
    if _prepare_debug_log_parent(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(span, separators=(",", ":")) + "\n")


@contextmanager
def trace_command(log_path: Path | None, argv: list[str]) -> Iterator[None]:
    """Context manager that tees stdout/stderr and appends a trace block.

    The flush path is chosen via ``safe_flush_debug_log_path`` after the
    command body returns. This matters for ``prepare-spec``: the pre-command
    path may be the active session log (the new spec does not exist yet),
    but handoff merges/deletes that file and clears the active pointer, after
    which the selector uniquely matches the new spec. Flushing the pre-resolved
    session path would recreate an orphan session log; re-resolving appends
    the tee block to ``<spec_dir>/debug.log`` instead.

    After ``archive`` moves a spec to ``archives/``, re-resolve follows the
    archived directory so tee appends there instead of recreating a vanished
    ``specs/<name>/`` stub via ``mkdir``.
    """
    start = time.monotonic()
    start_ns = time.time_ns()
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
        end_ns = time.time_ns()
        flush_path = safe_flush_debug_log_path(argv, log_path)
        debug_logged_at = None
        if flush_path is not None:
            debug_logged_at = _append_trace(
                flush_path,
                argv,
                stdout_parts,
                stdout_meta,
                stderr_parts,
                stderr_meta,
                exit_code,
                duration_ms,
            )
        try:
            trace_path = resolve_trace_file_path(flush_path)
            if trace_path is not None and (
                flush_path is None or trace_path.resolve() != flush_path.resolve()
            ):
                _append_cli_span(
                    trace_path, argv, start_ns, end_ns, duration_ms, exit_code, debug_logged_at,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("Failed to write CLI span: %s", exc)
