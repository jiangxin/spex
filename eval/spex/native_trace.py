"""Turn-scoped evidence from Spex-owned command logs."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from itertools import chain
from pathlib import Path

from performance import CLI_END, IDENTIFIER, TIMELINE, debug_logs, number_field, timestamp


def snapshot(repo: Path) -> dict:
    return window(repo, None)[0]


def window(repo: Path, baseline: dict | None) -> tuple[dict, dict]:
    """Use only append-only suffixes relative to a runner-owned checkpoint."""
    checkpoint, events, gaps = {}, [], set()
    if baseline is None:
        gaps.add("missing_log_baseline")
    timed = []
    span_sources = set()
    files = chain(debug_logs(repo), debug_logs(repo, "trace.jsonl"))
    for source, content, error in files:
        if error:
            gaps.add(error)
            checkpoint[source] = None
            continue
        checkpoint[source] = [len(content), hashlib.sha256(content).hexdigest()]
        if baseline is None:
            continue
        previous = baseline.get(source)
        if source in baseline and previous is None:
            gaps.add("missing_log_prefix")
            continue
        offset = previous[0] if previous else 0
        if previous and (
            offset > len(content) or hashlib.sha256(content[:offset]).hexdigest() != previous[1]
            or (offset and content[offset - 1:offset] != b"\n")
        ):
            gaps.add("debug_log_replaced")
            continue
        if offset == len(content):
            continue
        try:
            lines = content[offset:].decode("utf-8").splitlines()
        except UnicodeError:
            gaps.add("unreadable_debug_log")
            continue
        if not content.endswith(b"\n"):
            gaps.add("incomplete_cli_log")
            lines.pop()
        if Path(source).name == "trace.jsonl":
            spans = parse_timing_spans(lines, source, gaps)
            if spans:
                span_sources.add(Path(source).parent)
                timed.extend(spans)
        else:
            events.extend(parse(lines, source, gaps))
    if baseline is not None and baseline.keys() - checkpoint.keys():
        gaps.add("debug_log_removed")
        # A new path could contain older records moved from a missing log.
        events = [event for event in events if event["log"] in baseline]
        timed = [event for event in timed if event["log"] in baseline]
    if not any("exit_code" in event and "command" in event for event in events):
        gaps.add("missing_spex_commands")
    result = {"events": events, "gaps": sorted(gaps)}
    if timed:
        result["timing_events"] = timed + [
            event for event in events
            if "command" not in event or Path(event["log"]).parent not in span_sources
        ]
    return checkpoint, result


def parse_timing_spans(lines: list[str], source: str, gaps: set) -> list[dict]:
    """Read precise CLI bounds from supported JSONL spans."""
    spans = []
    for line in lines:
        if not line.strip():
            continue
        try:
            span = json.loads(line)
            start, end = span["start_time_unix_nano"], span["end_time_unix_nano"]
            if (span["schema_version"] != 1 or type(start) is not int
                    or type(end) is not int or not 0 <= start <= end):
                raise ValueError("Invalid trace span time")
        except (KeyError, TypeError, ValueError):
            gaps.add("unreadable_trace_jsonl")
            continue
        spans.append({"log": source, "start_ns": start, "end_ns": end})
    return spans


def option(words: list[str], flag: str) -> str | None:
    for index, word in enumerate(words):
        if word.startswith(flag + "="):
            return word.partition("=")[2]
        if word == flag and index + 1 < len(words):
            return words[index + 1]
    return None


def parse(lines: list[str], source: str, gaps: set) -> list:
    parts = Path(source).parts
    spec = parts[1] if len(parts) == 3 and parts[0] == "specs" else None
    events = []
    command = None
    reviews = {}
    for index, line in enumerate(lines):
        location = {"log": source, "sequence": index, "spec": spec}
        if line.startswith("===== BEGIN "):
            if command is not None:
                gaps.add("incomplete_cli_log")
            stamp = line.removeprefix("===== BEGIN ").removesuffix(" =====")
            command = {**location, "at": stamp if timestamp(stamp) else None}
        elif command is not None:
            if index == command["sequence"] + 1 and line.startswith("argv: spex "):
                try:
                    words = shlex.split(line)[2:]
                except ValueError:
                    gaps.add("unrecognized_cli_log")
                    words = []
                words = [word.replace("_", "-") if word in {
                    "apply_helper", "review_helper", "todo_helper",
                } else word for word in words]
                name = next((word for word in words if not word.startswith("-")), "")
                if IDENTIFIER.fullmatch(name):
                    command.update(action="spex.command", command=name)
                selector = option(words, "--name")
                if selector and IDENTIFIER.fullmatch(selector):
                    if spec is None:
                        command["spec"] = selector
                    elif selector != spec and not spec.endswith("-" + selector):
                        # A selector may be a partial name; keep the resolved path.
                        if selector not in spec:
                            gaps.add("conflicting_trace_spec")
                            command["spec"] = None
                step = option(words, "--step")
                if step and IDENTIFIER.fullmatch(step):
                    command["step"] = step
                if name == "apply-helper" and "post-action" in words:
                    command["action"] = "apply.post-action"
                elif name == "review-helper":
                    command["action"] = "apply.review-command"
                    command["stage"] = next(
                        (stage for stage in ("status", "open-batch", "complete-batch")
                         if stage in words), None,
                    )
                elif name == "prompt" and "apply-review" in words:
                    command["action"] = "apply.review-command"
                    command["stage"] = "prompt"
                    command["commit"] = option(words, "--commit")
            if command.get("stage") == "prompt" and line.startswith("[truncated prompt stdout, "):
                fields = dict(re.findall(r"(?:, |; )([a-z_]+)=([^;\]]+)", line))
                if fields.get("skipped") == "True":
                    command["skipped"] = True
                    command["step"] = fields.get("task_id")
                    command["commit"] = fields.get("commit_sha") or command.get("commit")
            end = CLI_END.fullmatch(line)
            if end:
                if "command" in command:
                    if (
                        command["action"] == "apply.post-action" and events
                        and events[-1]["action"] == "apply.post-action"
                        and "command" not in events[-1]
                        and events[-1]["sequence"] + 1 == command["sequence"]
                    ):
                        command["success_anchor"] = events.pop()["sequence"]
                    if (
                        command["action"] in {"apply.review-command", "apply.post-action"}
                        and not command["spec"]
                    ):
                        gaps.add("missing_trace_spec")
                    events.append({**command, "exit_code": int(end[1]), "duration_ms": int(end[2])})
                else:
                    gaps.add("unrecognized_cli_log")
                command = None
        elif match := TIMELINE.fullmatch(line):
            kind, fields = match.groups()
            values = dict(re.findall(r"\b([a-z_]+)=([^\s]+)", fields or ""))
            stamp = timestamp(values.get("ts"))
            if stamp:
                location["at"] = values["ts"]
            step = values.get("step") or values.get("id")
            if step and not IDENTIFIER.fullmatch(step):
                continue
            if kind == "post-action ok":
                events.append({**location, "action": "apply.post-action", "exit_code": 0})
            elif kind in {"task begin", "task committed", "task done", "route"}:
                events.append({**location, "action": "apply.workflow", "step": step})
            elif kind in {"review begin", "review end"}:
                mode, commit = values.get("mode"), values.get("commit", "")
                if mode not in {"full", "delta"} or not re.fullmatch(r"[0-9a-f]{7,64}", commit):
                    continue
                key = step, mode, commit, values.get("round")
                if kind == "review begin":
                    if key in reviews:
                        gaps.add("incomplete_review_log")
                        continue
                    reviews[key] = len(events)
                    events.append({
                        **location, "action": "apply.review", "step": step,
                        "mode": mode, "commit": commit,
                    })
                elif key in reviews:
                    events[reviews.pop(key)].update(
                        exit_code=0, duration_ms=number_field(values, "duration_ms"),
                    )
                else:
                    gaps.add("unpaired_review_end")
            elif kind == "fix end":
                base, new = values.get("base", ""), values.get("new", "")
                if all(re.fullmatch(r"[0-9a-f]{7,64}", sha) for sha in (base, new)):
                    events.append({
                        **location, "action": "apply.review", "step": step,
                        "base_commit": base, "new_commit": new, "exit_code": 0,
                        "duration_ms": number_field(values, "duration_ms"),
                    })
    if command is not None:
        gaps.add("incomplete_cli_log")
    if reviews:
        gaps.add("incomplete_review_log")
    return events
