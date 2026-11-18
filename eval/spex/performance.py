"""Collect timing and activity separately from scored trial evidence."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from scheduling import execution, execution_label
from workspace import EVAL_LOG_DIR

LOG = logging.getLogger(__name__)
USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
TIMELINE = re.compile(r"^===== APPLY (task (?:begin|committed|done)|"
                      r"(?:review|fix|checks) (?:begin|end)|route|post-action ok)(?: (.*))? =====$")
CLI_END = re.compile(r"^===== END exit=(-?\d+) duration_ms=(\d+) =====$")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
MAX_LOG_BYTES = 16 * 1024 * 1024
SPEX_COMMANDS = frozenset(
    "apply-helper archive branch config create-helper init list merge-helper modify-helper "
    "prompt review-helper spec todo-helper".split()
)
ROUTES = frozenset(
    "phase7_no_findings batch_fix minor_direct_complete major_delta new_major_next_full_round "
    "hard_cap_batch_fix".split()
)


def elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def nonnegative(value):
    return value if type(value) is int and value >= 0 else None


def wall_clock_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def host_metrics(raw: str | bytes | None, duration_ms: int | None, source: str,
                 error: str | None = None, *, started_at: str | None = None,
                 ended_at: str | None = None) -> dict:
    if duration_ms is None:
        duration_ms = delta_ms(timestamp(started_at), timestamp(ended_at))
    record = {
        "duration_ms": duration_ms, "duration_source": source if duration_ms is not None else None,
        "model_requests": None, "parent_usage": None, "subagent_usage": None,
        "commands": None, "command_failures": None, "subagent_starts": None,
        "subagent_failures": None, "subagent_spawn_failures": None, "trace": "missing",
        "gaps": ["missing_request_events", "missing_subagent_usage"],
    }
    for key, value in (("started_at", started_at), ("ended_at", ended_at)):
        if timestamp(value) is not None:
            record[key] = value
    if error:
        record["error"] = error if re.fullmatch(r"[a-z_]{1,64}", error) else "host_error"
        record["gaps"].append(record["error"])
    if not raw:
        record["gaps"].append("missing_host_trace")
        return record
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    counts = dict.fromkeys(
        ("commands", "command_failures", "subagent_starts", "subagent_spawn_failures"), 0,
    )
    seen = set()
    collab = False
    failed_agents = set()
    agent_states_observed = False
    complete = malformed = False
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            malformed = True
            continue
        if not isinstance(event, dict):
            malformed = True
            continue
        if event.get("type") == "turn.completed":
            complete = True
            usage = event.get("usage")
            if isinstance(usage, dict):
                record["parent_usage"] = {key: nonnegative(usage.get(key)) for key in USAGE_FIELDS}
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in seen:
                continue
            seen.add(item_id)
        if item.get("type") == "command_execution":
            counts["commands"] += 1
            counts["command_failures"] += int(
                item.get("status") == "failed" or type(item.get("exit_code")) is int
                and item["exit_code"] != 0
            )
        if item.get("type") == "collab_tool_call":
            collab = True
            if item.get("tool") == "spawn_agent":
                counts["subagent_starts"] += int(item.get("status") == "completed")
                counts["subagent_spawn_failures"] += int(item.get("status") == "failed")
            states = item.get("agents_states")
            if isinstance(states, dict):
                for agent, state in states.items():
                    if isinstance(state, dict) and isinstance(state.get("status"), str):
                        agent_states_observed = True
                        if state["status"] in {"failed", "errored"}:
                            failed_agents.add(agent)
    if collab and not (counts["subagent_starts"] or counts["subagent_spawn_failures"]):
        counts["subagent_starts"] = counts["subagent_spawn_failures"] = None
        record["gaps"].append("missing_subagent_spawn_events")
    counts["subagent_failures"] = len(failed_agents) if agent_states_observed else None
    record.update(counts, trace="complete" if complete and not malformed else "partial",
                  trace_source="codex_jsonl")
    if record["parent_usage"] is None:
        record["gaps"].append("missing_token_usage")
    return record


def timestamp(value):
    if isinstance(value, str) and value:
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return stamp if stamp.tzinfo is not None else None
        except ValueError:
            pass
    return None


def delta_ms(start, end):
    if start is not None and end is not None and end >= start:
        return round((end - start).total_seconds() * 1000)
    return None


def stamp_bounds(value):
    """Represent an ISO timestamp as a range at its recorded precision."""
    parsed = timestamp(value)
    if parsed is None:
        return None
    delta = parsed - datetime(1970, 1, 1, tzinfo=timezone.utc)
    start = (delta.days * 86_400 + delta.seconds) * 10**9 + delta.microseconds * 1000
    fraction = re.search(r"[T ]\d{2}:\d{2}:\d{2}[.,](\d+)", value)
    digits = fraction[1][:9] if fraction else ""
    if len(digits) > 6:
        start += int(digits[6:].ljust(3, "0"))
    return start, start + 10 ** (9 - len(digits)) - 1


def event_bounds(event):
    """Return the latest possible start and earliest possible finish."""
    if type(event.get("start_ns")) is int and type(event.get("end_ns")) is int:
        return event["start_ns"], event["end_ns"]
    stamp = stamp_bounds(event.get("at"))
    duration = nonnegative(event.get("duration_ms"))
    if stamp is None:
        return None
    low, high = stamp
    if "command" in event and duration is not None:
        # Legacy BEGIN is written at flush time, after the command returns.
        return high - duration * 10**6, low
    if event.get("mode") in {"full", "delta"} and duration is not None:
        return high, low + duration * 10**6
    if event.get("action") == "apply.workflow":
        return high, low
    return None


def validate_host_timing(host: dict, native: dict | None) -> None:
    """Compare a host interval only to this turn's persisted Spex evidence."""
    duration = nonnegative(host.get("duration_ms"))
    start, end = stamp_bounds(host.get("started_at")), stamp_bounds(host.get("ended_at"))
    if duration is None and start is None and end is None:
        return
    gaps = host.setdefault("gaps", [])
    evidence = native or {}
    events = evidence.get("timing_events", evidence.get("events", []))
    bounds = [pair for event in events if (pair := event_bounds(event)) is not None]
    if not bounds:
        gaps.append("missing_turn_timing_evidence")
        return
    first, last = min(pair[0] for pair in bounds), max(pair[1] for pair in bounds)
    slack = 5 * 10**9
    if (
        (duration is not None and duration * 10**6 + slack < last - first)
        or (start is not None and start[0] > first + slack)
        or (end is not None and end[1] < last - slack)
        or (start is not None and end is not None and start[0] > end[1])
    ):
        gaps.append("implausible_host_duration")


def parse_log(segments: list[str]) -> dict:
    """Read helper-owned anchors, keeping only recognized fields."""
    tasks = []
    task = None
    active_spans = {}
    previous_turn_spans = set()
    spans = []
    routes = []
    commands = []
    command = None
    last_stamp = None
    gaps = set()
    for line in log_lines(segments):
        if line is None:
            if command is not None:
                gaps.add("incomplete_cli_log")
            command = task = None
            previous_turn_spans.update(active_spans)
            active_spans.clear()
            continue
        if line.startswith("===== BEGIN "):
            if command is not None:
                gaps.add("incomplete_cli_log")
            command = {"stamp": line.removeprefix("===== BEGIN ").removesuffix(" =====")}
            continue
        if command is not None:
            if line.startswith("argv: spex ") and "command" not in command:
                parts = line.split()
                name = next((word for word in parts[2:] if not word.startswith("-")), "")
                command["command"] = name if name in SPEX_COMMANDS else None
            end = CLI_END.fullmatch(line)
            if end:
                command.update(exit_code=int(end[1]), duration_ms=int(end[2]))
                stamp = timestamp(command.pop("stamp"))
                if stamp:
                    command["logged_at"] = stamp.isoformat()
                commands.append(command)
                command = None
            continue
        match = TIMELINE.fullmatch(line)
        if not match:
            continue
        kind, fields = match.groups()
        fields = dict(re.findall(r"\b([a-z_]+)=([^\s]+)", fields or ""))
        step = fields.get("step") or fields.get("id")
        if step and not IDENTIFIER.fullmatch(step):
            continue
        at = timestamp(fields.get("ts"))
        if at:
            last_stamp = at
        mode = fields.get("mode") if fields.get("mode") in {"full", "delta"} else None
        round_no = number_field(fields, "round")
        if kind == "task begin":
            if task is not None and task["step"] == step:
                if at and task.get("started_at") != at.isoformat():
                    gaps.add("repeated_task_begin")
                continue
            phase = fields.get("resume_phase")
            task = {"step": step, "status": "interrupted",
                    "resume_phase": phase if phase in {"implement", "review"} else None,
                    "last_phase": phase if phase in {"implement", "review"} else None,
                    "duration_ms": None, "implementation_and_commit_ms": None}
            if at:
                task["started_at"] = at.isoformat()
            tasks.append(task)
        elif kind in {"task committed", "task done"} and task is not None and task["step"] == step:
            start = timestamp(task.get("started_at"))
            if kind == "task committed":
                task["implementation_and_commit_ms"] = delta_ms(start, at)
                task["last_phase"] = "review"
            else:
                task.update(status="complete", duration_ms=delta_ms(start, at))
                if at:
                    task["ended_at"] = at.isoformat()
                task = None
        elif kind.endswith((" begin", " end")) and not kind.startswith("task "):
            phase = kind.split()[0]
            key = (phase, step, round_no, mode)
            if kind.endswith(" begin"):
                span = {"phase": phase, "step": step, "round": round_no, "mode": mode,
                        "status": "interrupted", "duration_ms": None}
                if at:
                    span["started_at"] = at.isoformat()
                if key in active_spans and active_spans[key] == span:
                    continue
                active_spans[key] = span
                spans.append(span)
                if task is not None and task["step"] == step:
                    task["last_phase"] = phase
                continue
            duration = number_field(fields, "duration_ms")
            if phase == "checks":
                measured = number_field(fields, "timed_count")
                count = number_field(fields, "count")
                if ((measured is not None and measured != count)
                        or (measured is None and not duration)):
                    duration = None
                    gaps.add("missing_check_timings")
            span = active_spans.pop(key, None)
            if span is None:
                if key in previous_turn_spans:
                    gaps.add("cross_turn_span")
                    duration = None
                    previous_turn_spans.discard(key)
                if spans and spans[-1].get("status") == "complete" and at and (
                    spans[-1].get("ended_at"), spans[-1]["phase"], spans[-1]["step"]
                ) == (at.isoformat(), phase, step):
                    continue
                span = {"phase": phase, "step": step, "round": round_no, "mode": mode}
                spans.append(span)
            span.update(status="complete", duration_ms=duration)
            if at:
                span["ended_at"] = at.isoformat()
            if task is not None and task["step"] == step and phase == "review":
                if task["resume_phase"] == "review" and span.get("started_at"):
                    task.setdefault("review_started_at", span["started_at"])
        elif kind == "route":
            result = fields.get("result", "")
            if result in ROUTES:
                routes.append({"step": step, "round": round_no, "mode": mode, "result": result})
    if command is not None:
        gaps.add("incomplete_cli_log")
    if not (tasks or spans or routes or commands):
        gaps.add("unrecognized_debug_log")
    for item in tasks:
        if item.get("review_started_at") and item.get("ended_at"):
            item["duration_ms"] = delta_ms(
                timestamp(item["review_started_at"]), timestamp(item["ended_at"]),
            )
    if any(item["duration_ms"] is None for item in tasks if item["status"] == "complete"):
        gaps.add("missing_task_timestamps")
    return {
        "tasks": tasks, "spans": spans, "routes": routes, "commands": commands,
        "gaps": sorted(gaps), "last_event_at": last_stamp.isoformat() if last_stamp else None,
    }


def number_field(fields: dict, key: str) -> int | None:
    value = fields.get(key, "")
    return int(value) if value.isascii() and value.isdigit() and len(value) < 15 else None


def log_lines(segments: list[str]):
    for index, segment in enumerate(segments):
        if index:
            yield None
        yield from segment.splitlines()


def debug_logs(repo: Path, filename: str = "debug.log"):
    """Yield bounded workspace logs and read errors without following symlinks."""
    root = repo / ".spex"
    paths = [root / filename, root / EVAL_LOG_DIR / filename]
    for directory in ("specs", "archives", "sessions"):
        parent = root / directory
        if parent.resolve() == parent:
            paths.extend(parent.glob(f"*/{filename}"))
        else:
            yield f"{directory}/{filename}", None, "unsafe_debug_log"
    for path in sorted(paths):
        if not path.exists() and not path.is_symlink():
            continue
        relative = path.relative_to(root)
        if len(relative.parts) not in (1, 2, 3) or (
            len(relative.parts) == 3 and relative.parts[0] not in {"specs", "archives", "sessions"}
        ):
            continue
        if len(relative.parts) == 3 and not IDENTIFIER.fullmatch(relative.parts[1]):
            continue
        source = relative.as_posix()
        try:
            if path.resolve() != path or not path.is_file():
                yield source, None, "unsafe_debug_log"
                continue
            with path.open("rb") as stream:
                content = stream.read(MAX_LOG_BYTES + 1)
            if len(content) > MAX_LOG_BYTES:
                yield source, None, "oversized_debug_log"
                continue
            yield source, content, None
        except OSError:
            yield source, None, "unreadable_debug_log"


def workflow_metrics(repo: Path, previous: dict | None = None, *, new_turn: bool = False) -> dict:
    logs, gaps = [], []
    prior = {log["source"]: log for log in (previous or {}).get("logs", [])}
    for source, content, error in debug_logs(repo):
        if error:
            gaps.append(error)
            continue
        relative = Path(source)
        try:
            earlier = prior.get(source, {})
            offsets = list(earlier.get("turn_offsets", []))
            size = earlier.get("size_bytes")
            if new_turn and size:
                offsets.append(size)
            # A truncated or replaced log cannot be safely split at old offsets.
            prior_hash = earlier.get("content_sha256")
            replaced = bool(prior_hash and hashlib.sha256(content[:size]).hexdigest() != prior_hash)
            if replaced or any(offset > len(content) or content[offset - 1:offset] != b"\n"
                               for offset in offsets):
                offsets = []
                gaps.append("debug_log_replaced")
            offsets = sorted({offset for offset in offsets if offset > 0})
            bounds = [0, *offsets, len(content)]
            segments = [
                content[start:end].decode("utf-8") for start, end in zip(bounds, bounds[1:])
            ]
            parsed = parse_log(segments)
            gaps.extend(parsed.pop("gaps"))
            for task in parsed["tasks"]:
                task["spec"] = relative.parts[1] if len(relative.parts) == 3 else None
            logs.append({
                "source": source, "size_bytes": len(content), "turn_offsets": offsets,
                "content_sha256": hashlib.sha256(content).hexdigest(), **parsed,
            })
        except (OSError, ValueError, OverflowError):
            gaps.append("unreadable_debug_log")
    if not logs:
        gaps.append("missing_debug_log")
    return {"logs": logs, "gaps": sorted(set(gaps))}


def read_performance(output: Path) -> dict:
    path = output / "performance.json"
    try:
        if path.is_symlink():
            raise ValueError("Unsafe performance file")
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or not isinstance(data.get("turns"), dict)
                or any(not isinstance(turn, dict) or not isinstance(turn.get("host"), dict)
                       for turn in data["turns"].values())):
            raise ValueError("Invalid performance data")
        return data
    except FileNotFoundError:
        return {"schema_version": 1, "turns": {}}
    except (OSError, ValueError):
        return {"schema_version": 1, "turns": {}, "gaps": ["unreadable_performance_file"]}


def update(output: Path, *, turn: int | None = None, repo: Path | None = None,
           native: dict | None = None, **metrics) -> None:
    data = read_performance(output)
    try:
        new_turn = turn is not None and str(turn) not in data["turns"]
        if turn is None:
            data.update(metrics)
        else:
            validate_host_timing(metrics["host"], native)
            if native is not None:
                metrics["spex_commands"] = [
                    {key: event[key] for key in (
                        "log", "sequence", "spec", "step", "todo_file_hash", "command",
                        "subcommand", "exit_code", "duration_ms", "start_ns", "end_ns", "at",
                    ) if key in event}
                    for event in native.get("timing_events", native.get("events", []))
                    if "command" in event
                ]
            data["turns"][str(turn)] = metrics
        if repo is not None:
            try:
                data["workflow"] = workflow_metrics(repo, data.get("workflow"), new_turn=new_turn)
            except (OSError, ValueError, TypeError, OverflowError, KeyError):
                data["workflow"] = {"logs": [], "gaps": ["unreadable_workflow_metrics"]}
        if (output / "performance.json").is_symlink():
            raise ValueError("Unsafe performance file")
        temp = output / "performance.tmp"
        if temp.is_symlink():
            raise ValueError("Unsafe temporary file")
        temp.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temp.replace(output / "performance.json")
    except (OSError, ValueError, TypeError, KeyError):
        LOG.warning("Could not save trial performance diagnostics")


def complete_sum(values):
    return sum(values) if values and all(value is not None for value in values) else None


def format_seconds(duration_ms: int | float | None) -> str:
    return "unknown" if duration_ms is None else str(duration_ms / 1000)


def iso_from_ns(value: int | None) -> str | None:
    if type(value) is not int:
        return None
    seconds, nanos = divmod(value, 10**9)
    try:
        stamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    except OverflowError:
        return None
    return f"{stamp.replace(tzinfo=None).isoformat()}.{nanos:09d}+00:00"


def report_stamp(value) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[0-9TtZ +:.,-]+", value):
        return value if timestamp(value) is not None else None
    return None


def timeline_elapsed(at, case_start) -> float | None:
    point = stamp_bounds(at)
    origin = stamp_bounds(case_start)
    return (point[0] - origin[0]) / 10**6 if point and origin else None


def legacy_command_key(source: str, command: dict) -> tuple:
    """Match the fields retained by historical workflow summaries."""
    return (
        Path(source).parent, command.get("command"),
        timestamp(command.get("at") or command.get("logged_at")),
        command.get("duration_ms"), command.get("exit_code"),
    )


def command_timeline(turns: dict, workflow: dict) -> list[dict]:
    """Use turn-scoped observations and recover commands from older turns."""
    observations = [
        (index, command)
        for index, turn in sorted(turns.items())
        for command in turn.get("spex_commands", [])
    ]
    if not turns or any("spex_commands" not in turn for turn in turns.values()):
        covered = Counter(
            legacy_command_key(command["log"], command)
            for _, command in observations
            if "log" in command and timestamp(command.get("at")) is not None
        )
        for log in workflow.get("logs", []):
            for command in log.get("commands", []):
                key = legacy_command_key(log["source"], command)
                if covered[key]:
                    covered[key] -= 1
                else:
                    observations.append((None, command))
    commands = []
    for index, command in observations:
        name = command.get("command")
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            continue
        verb = command.get("subcommand")
        exit_code = command.get("exit_code")
        entry = {
            "turn": index,
            "command": name,
            "subcommand": verb if isinstance(verb, str) and IDENTIFIER.fullmatch(verb) else None,
            "started_at": iso_from_ns(command.get("start_ns")),
            "ended_at": iso_from_ns(command.get("end_ns")),
            "logged_at": report_stamp(command.get("at") or command.get("logged_at")),
            "duration_ms": nonnegative(command.get("duration_ms")),
            "exit_code": exit_code if type(exit_code) is int else None,
        }
        for key in ("spec", "step", "todo_file_hash"):
            if isinstance(command.get(key), str):
                entry[key] = command[key]
        commands.append(entry)
    return sorted(commands, key=lambda command: timeline_order(
        command["started_at"] or command["logged_at"],
    ))


def timeline_order(at) -> tuple[bool, int]:
    bounds = stamp_bounds(at)
    return bounds is None, bounds[0] if bounds else 0


def summarize_timeline(data: dict, metadata: dict, pending_turns: bool) -> dict:
    recorded = {
        int(index): turn for index, turn in data.get("turns", {}).items()
        if str(index).isascii() and str(index).isdecimal() and int(index) > 0
    }
    indices = set(recorded)
    for default, result in enumerate(metadata.get("turn_results", []), 1):
        index = result.get("turn") if isinstance(result, dict) else None
        indices.add(index if type(index) is int and index > 0 else default)
    timeline = []
    for index in sorted(indices):
        host = recorded.get(index, {}).get("host", {})
        timeline.append({
            "index": index,
            "started_at": report_stamp(host.get("started_at")),
            "ended_at": report_stamp(host.get("ended_at")),
            "duration_ms": nonnegative(host.get("duration_ms")),
        })
    case_start = timeline[0]["started_at"] if timeline and timeline[0]["index"] == 1 else None
    case_end = timeline[-1]["ended_at"] if timeline and not pending_turns else None
    commands = command_timeline(recorded, data.get("workflow", {}))
    for interval in [*timeline, *commands]:
        interval["elapsed_ms"] = timeline_elapsed(interval["started_at"], case_start)
    return {
        "case_started_at": case_start,
        "case_ended_at": case_end,
        "case_elapsed_ms": timeline_elapsed(case_end, case_start),
        "host_turns_timeline": timeline,
        "spex_commands": commands,
    }


def trial_summary(output: Path, metadata: dict, data: dict | None = None) -> dict:
    try:
        return summarize_metrics(
            output, metadata, data if data is not None else read_performance(output),
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return summarize_metrics(output, metadata, {
            "gaps": ["unreadable_performance_file"],
        })


def summarize_metrics(output: Path, metadata: dict, data: dict) -> dict:
    turns = list(data.get("turns", {}).values())
    hosts = [turn["host"] for turn in turns]
    workflow = data.get("workflow", {})
    tasks = [task for log in workflow.get("logs", []) for task in log["tasks"]]
    reviews = [dict(span, source=log["source"]) for log in workflow.get("logs", [])
               for span in log["spans"] if span["phase"] == "review"]
    timed = [task for task in tasks if task["duration_ms"] is not None]
    interrupted = [task for task in tasks if task["status"] == "interrupted"]
    host_turns = max(len(turns), len(metadata.get("turn_results", [])))
    all_turns_measured = bool(hosts) and len(hosts) == host_turns
    complete_traces = all_turns_measured and all(host["trace"] == "complete" for host in hosts)
    host_duration_ms = (
        complete_sum([nonnegative(host["duration_ms"]) for host in hosts])
        if all_turns_measured else None
    )
    automatic_total_ms = nonnegative(data.get("automatic_total_ms", metadata.get("duration_ms")))
    case = metadata.get("case")
    planned_turns = case.get("turns") if isinstance(case, dict) else None
    pending_turns = (
        metadata.get("verdict") == "pending"
        and isinstance(planned_turns, list)
        and len(metadata.get("turn_results", [])) < len(planned_turns)
    )
    duration_ms, duration_source = None, "unknown"
    if not pending_turns:
        if host_duration_ms is not None:
            duration_ms, duration_source = host_duration_ms, "host"
        elif automatic_total_ms is not None:
            duration_ms, duration_source = automatic_total_ms, "automatic"
    return {
        "detail": "performance.json" if (output / "performance.json").is_file() else None,
        "host_turns": host_turns,
        "recorded_host_turns": len(turns),
        "host_duration_ms": host_duration_ms,
        "automatic_total_ms": automatic_total_ms,
        "duration_ms": duration_ms,
        "duration_s": None if duration_ms is None else duration_ms / 1000,
        "duration_source": duration_source,
        **summarize_timeline(data, metadata, pending_turns),
        "model_requests": None,
        "review_rounds": (
            len({(span["source"], span["step"], span["round"]) for span in reviews
                 if span["round"] is not None}) if workflow.get("logs") else None
        ),
        "slowest_step": max(timed, key=lambda task: task["duration_ms"], default=None),
        "interrupted_steps": interrupted,
        "full_reviews": (
            sum(span["mode"] == "full" for span in reviews) if workflow.get("logs") else None
        ),
        "delta_reviews": (
            sum(span["mode"] == "delta" for span in reviews) if workflow.get("logs") else None
        ),
        "subagent_starts": (
            complete_sum([host["subagent_starts"] for host in hosts]) if complete_traces else None
        ),
        "parent_usage": {
            key: complete_sum([(host["parent_usage"] or {}).get(key) for host in hosts])
            if all_turns_measured else None
            for key in USAGE_FIELDS
        },
        "gaps": sorted(set(data.get("gaps", []) + workflow.get("gaps", []) + [
            reason for condition, reason in (
                (not all_turns_measured, "missing_turn_metrics"),
                (not workflow, "missing_workflow_metrics"),
                (any(nonnegative(host["duration_ms"]) is None for host in hosts),
                 "missing_host_duration"),
                (bool(hosts) and not complete_traces, "incomplete_host_trace"),
                (any(host["subagent_starts"] is None for host in hosts), "missing_subagent_starts"),
                (any(host["parent_usage"] is None for host in hosts), "missing_token_usage"),
            ) if condition
        ] + [gap for host in hosts for gap in host.get("gaps", [])])),
    }


def report_lines(rows: list[dict]) -> list[str]:
    lines = [
        "", "## Performance", "",
        "| Case | Host turns | Duration (s) | Source | Slowest step | "
        "Rounds; full / delta passes | Subagents | "
        "Input / cached / output / reasoning tokens | Detail |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    samples = {}
    for row in rows:
        perf = row["performance"]
        case = f"{row['suite']}/{row['case_id']}"
        step = perf["slowest_step"]
        slowest = f"{step['step']} ({step['duration_ms']} ms)" if step else None
        if perf["interrupted_steps"]:
            stopped = ", ".join(
                f"{task['step']} ({task.get('last_phase') or task['resume_phase'] or 'unknown'})"
                for task in perf["interrupted_steps"]
            )
            slowest = f"{slowest or 'unknown'} / interrupted {stopped}"
        detail = f"[metrics]({row['trial']}/{perf['detail']})" if perf["detail"] else "—"
        duration_ms, source = perf["duration_ms"], perf["duration_source"]
        fields = [case, perf["host_turns"], format_seconds(duration_ms), source, slowest,
                  f"{display([perf['review_rounds']])}; "
                  f"{display((perf['full_reviews'], perf['delta_reviews']))}",
                  perf["subagent_starts"],
                  display(perf["parent_usage"].values()), detail]
        cells = ["unknown" if value is None else str(value) for value in fields]
        lines.append("| " + " | ".join(cells) + " |")
        setting = execution_label(row.get("execution", execution(None)))
        key = (case, row["host"], row["model"], row["collection"], row["spex_ref"], setting)
        samples.setdefault(key, {}).setdefault(source, []).append(duration_ms)
    lines.extend([
        "",
        "Duration sums the host turn wall-clock measurements when all are available. "
        "The automatic source covers the full automated trial, including grading. "
        "Sample counts show each duration source's coverage among trials with matching settings.",
        "",
        "Model requests are unknown when the host lacks request-level events. "
        "Review, fix and checks may overlap.",
        "",
    ])
    for row in rows:
        gaps = row["performance"]["gaps"]
        if gaps:
            lines.append(f"- {row['suite']}/{row['case_id']} diagnostics gaps: "
                         + ", ".join(gaps) + ".")
    for (case, host, model, collection, ref, setting), by_source in samples.items():
        total = sum(len(values) for values in by_source.values())
        if total < 2:
            continue
        for source, values in by_source.items():
            if source == "unknown":
                continue
            lines.append(
                f"- {case} ({host}/{model}, {collection}, {(ref or 'unknown')[:8]}, {setting}): "
                f"{source} duration for {len(values)}/{total} samples, "
                f"median {format_seconds(median(values))} s, max {format_seconds(max(values))} s."
            )
    return lines + timeline_lines(rows)


def timeline_lines(rows: list[dict]) -> list[str]:
    lines = []
    for row in rows:
        perf = row["performance"]
        turns = perf["host_turns_timeline"]
        commands = perf["spex_commands"]
        if not turns and not commands:
            continue
        if not lines:
            lines.extend([
                "", "## Execution timeline", "",
                "Elapsed measures time from the first host dispatch. "
                "Legacy command logs may provide only their log timestamp.", "",
            ])
        case = f"{row['suite']}/{row['case_id']}"
        lines.extend([
            f"### {case} ({row['trial']})", "",
            "| Event | Started | Ended | Logged | Duration (s) | Elapsed (s) | Exit |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ])
        lines.append(timeline_row("Case start", started=perf["case_started_at"],
                                  elapsed=0 if perf["case_started_at"] else None))
        entries = []
        for turn in turns:
            label = f"Host turn {turn['index']}"
            start, end = turn["started_at"], turn["ended_at"]
            entries.extend([
                (start, timeline_row(f"{label} start", started=start, elapsed=turn["elapsed_ms"])),
                (end, timeline_row(f"{label} end", ended=end, duration=turn["duration_ms"],
                                   elapsed=timeline_elapsed(end, perf["case_started_at"]))),
            ])
        for command in commands:
            label = " ".join(filter(None, (command["command"], command["subcommand"])))
            start, logged = command["started_at"], command["logged_at"]
            entries.append((start or logged, timeline_row(
                f"`{label}`", started=start, ended=command["ended_at"], logged=logged,
                duration=command["duration_ms"], elapsed=command["elapsed_ms"],
                exit_code=command["exit_code"],
            )))
        entries.sort(key=lambda entry: timeline_order(entry[0]))
        lines.extend(line for _, line in entries)
        lines.append(timeline_row("Case end", ended=perf["case_ended_at"],
                                  duration=perf["duration_ms"], elapsed=perf["case_elapsed_ms"]))
        lines.append("")
    return lines


def timeline_row(label, *, started=None, ended=None, logged=None, duration=None, elapsed=None,
                 exit_code=None) -> str:
    fields = (label, started, ended, logged, format_seconds(duration), format_seconds(elapsed),
              exit_code)
    return "| " + " | ".join("unknown" if value is None else str(value) for value in fields) + " |"


def display(values) -> str:
    return " / ".join("unknown" if value is None else str(value) for value in values)
