"""Turn-scoped evidence from Spex-owned command logs."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from bisect import bisect_left
from collections import defaultdict
from itertools import chain
from pathlib import Path

from performance import (
    CLI_END,
    IDENTIFIER,
    TIMELINE,
    debug_logs,
    log_spec_name,
    number_field,
    stamp_bounds,
    timestamp,
)
from workspace import EVAL_LOG_DIR

CENTRAL_DEBUG_LOG = f"{EVAL_LOG_DIR}/debug.log"


def snapshot(repo: Path) -> dict:
    return window(repo, None)[0]


def window(repo: Path, baseline: dict | None) -> tuple[dict, dict]:
    """Use only append-only suffixes relative to a runner-owned checkpoint."""
    checkpoint, events, gaps = {}, [], set()
    if baseline is None:
        gaps.add("missing_log_baseline")
    timed = []
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
            timed.extend(parse_timing_spans(lines, source, gaps))
        else:
            events.extend(parse(lines, source, gaps))
    if baseline is not None and baseline.keys() - checkpoint.keys():
        gaps.add("debug_log_removed")
        # A new path could contain older records moved from a missing log.
        events = [event for event in events if event["log"] in baseline]
        timed = [event for event in timed if event["log"] in baseline]
    if timed:
        enrich_todo_events(events, timed)
    if any(event.get("_argv_unparsed") for event in events):
        gaps.add("unrecognized_cli_log")
    events = correlate_central_log(repo, events, gaps)
    if not any("exit_code" in event and "command" in event for event in events):
        gaps.add("missing_spex_commands")
    result = {"events": events, "gaps": sorted(gaps)}
    if timed:
        result["timing_events"] = merge_timing_events(events, timed)
    for event in chain(events, result.get("timing_events", ())):
        event.pop("_argv_fingerprint", None)
        event.pop("_debug_logged_at", None)
        event.pop("_todo_locator", None)
        event.pop("_argv_unparsed", None)
    return checkpoint, result


def correlate_central_log(repo: Path, events: list[dict], gaps: set) -> list[dict]:
    """Link central CLI calls and spec-local anchors from the same turn."""
    commands = [event for event in events if event["log"] == CENTRAL_DEBUG_LOG]
    if not commands:
        return events
    root = repo / ".spex/specs"
    names = {path.name for path in root.glob("*")
             if path.resolve() == path and path.is_dir() and IDENTIFIER.fullmatch(path.name)}
    posts, anchors = defaultdict(list), defaultdict(list)
    for event in commands:
        selector = event.get("spec")
        if selector and selector not in names:
            matches = [name for name in names if selector in name]
            event["spec"] = matches[0] if len(matches) == 1 else None
            if len(matches) > 1:
                gaps.add("ambiguous_trace_spec")
        if event["action"] in {"apply.post-action", "apply.review-command"} and not event["spec"]:
            gaps.add("missing_trace_spec")
        if event["action"] == "apply.post-action" and event["spec"]:
            posts[event["spec"]].append(event)
    for index, event in enumerate(events):
        if event["action"] == "apply.post-action" and "command" not in event:
            anchors[event["spec"]].append(index)
    paired = set()
    for spec in posts.keys() & anchors.keys():
        if len(posts[spec]) != 1 or len(anchors[spec]) != 1:
            gaps.add("ambiguous_post_action_anchor")
            continue
        index = anchors[spec][0]
        anchor = events[index]
        posts[spec][0].update(success_anchor=anchor["sequence"], success_anchor_log=anchor["log"])
        paired.add(index)
    return [event for index, event in enumerate(events) if index not in paired]


def parse_timing_spans(lines: list[str], source: str, gaps: set) -> list[dict]:
    """Read precise CLI bounds and normalized command fields from JSONL."""
    spans = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            span = json.loads(line)
            start, end = span["start_time_unix_nano"], span["end_time_unix_nano"]
            if (type(span["schema_version"]) is not int or span["schema_version"] != 1
                    or type(start) is not int
                    or type(end) is not int or not 0 <= start <= end):
                raise ValueError("Invalid trace span time")
        except (KeyError, TypeError, ValueError, RecursionError):
            gaps.add("unreadable_trace_jsonl")
            continue
        record = {"log": source, "sequence": index, "start_ns": start, "end_ns": end}
        if (spec := log_spec_name(source)) is not None:
            record["spec"] = spec
        # Older captures can contain bounds without a command payload.
        if any(key in span for key in ("name", "attributes", "spex")):
            fields = span_command_fields(span)
            if fields is None:
                gaps.add("unreadable_trace_jsonl")
                continue
            record.update(fields)
        spans.append(record)
    return spans


def span_command_fields(span: dict) -> dict | None:
    attributes, spex = span.get("attributes"), span.get("spex")
    if not isinstance(attributes, dict) or not isinstance(spex, dict):
        return None
    name = span.get("name") or spex.get("subcommand")
    duration, exit_code = spex.get("duration_ms"), attributes.get("process.exit.code")
    if (not isinstance(name, str) or not IDENTIFIER.fullmatch(name.replace("_", "-"))
            or type(duration) is not int or duration < 0 or type(exit_code) is not int):
        return None
    fields = {"command": name.replace("_", "-"), "duration_ms": duration, "exit_code": exit_code}
    if stamp_bounds(spex.get("debug_logged_at")) is not None:
        fields["_debug_logged_at"] = spex["debug_logged_at"]
    words = attributes.get("process.command_args")
    if isinstance(words, list) and words and all(isinstance(word, str) for word in words):
        fields["argv"] = list(words)
        fields["_argv_fingerprint"] = argv_fingerprint(" ".join(words[1:]))
        subcommand = command_verb(words[1:], fields["command"])
        if subcommand:
            fields["subcommand"] = subcommand
            if fields["command"] == "todo-helper":
                index = next(i for i, word in enumerate(words[1:], 1)
                             if word.replace("_", "-") == "todo-helper")
                fields["_todo_locator"] = todo_selector(
                    ["todo-helper", *words[index + 1:]], subcommand,
                )
    return fields


def command_verb(words: list[str], name: str) -> str | None:
    """Find the helper verb, skipping values of legacy selector options."""
    for index, word in enumerate(words):
        if word.replace("_", "-") == name:
            arguments = iter(words[index + 1:])
            for argument in arguments:
                if argument in {"--name", "--todo-json", "--todo-file"}:
                    next(arguments, None)
                elif not argument.startswith("-"):
                    return argument if IDENTIFIER.fullmatch(argument) else None
            break
    return None


def timing_key(record: dict) -> tuple:
    return (Path(record["log"]).parent, record["command"], record["_argv_fingerprint"],
            record["duration_ms"], record["exit_code"])


def match_timing_events(events: list[dict], spans: list[dict]):
    """Pair commands with spans using their existing debug timing metadata."""
    groups = defaultdict(list)
    for index, span in enumerate(spans):
        if "_argv_fingerprint" in span:
            stamp = stamp_bounds(span.get("_debug_logged_at"))
            instant = stamp[0] if stamp else span["end_ns"]
            groups[timing_key(span)].append((instant, index))
    for candidates in groups.values():
        candidates.sort()
    next_index = defaultdict(int)
    legacy = sorted(
        (stamp, index) for index, event in enumerate(events)
        if "_argv_fingerprint" in event and (stamp := stamp_bounds(event.get("at")))
    )
    for stamp, event_index in legacy:
        event = events[event_index]
        key = timing_key(event)
        candidates = groups.get(key, ())
        index = bisect_left(candidates, (stamp[0], -1), lo=next_index[key])
        if index < len(candidates) and candidates[index][0] <= stamp[1]:
            span_index = candidates[index][1]
            yield event_index, span_index, candidates, stamp
            next_index[key] = index + 1


def merge_timing_events(events: list[dict], spans: list[dict]) -> list[dict]:
    """Replace each matching legacy command once, keeping its workflow metadata."""
    matched = set()
    for event_index, span_index, _, _ in match_timing_events(events, spans):
        spans[span_index] = {**events[event_index], **spans[span_index]}
        matched.add(event_index)
    return spans + [event for index, event in enumerate(events) if index not in matched]


def enrich_todo_events(events: list[dict], spans: list[dict]) -> None:
    """Use structured argv when the matching spans agree on todo attribution."""
    for event_index, span_index, candidates, stamp in match_timing_events(events, spans):
        span = spans[span_index]
        if "_todo_locator" not in span or "_debug_logged_at" not in span:
            continue
        start = bisect_left(candidates, (stamp[0], -1))
        end = bisect_left(candidates, (stamp[1] + 1, -1))
        locators = {spans[i].get("_todo_locator") for _, i in candidates[start:end]}
        event = events[event_index]
        if len(locators) != 1:
            if event["log"] == CENTRAL_DEBUG_LOG:
                event["spec"] = None
            continue
        action, selector = span["_todo_locator"]
        event.pop("_argv_unparsed", None)
        if action:
            event["transaction_action"] = action
        if event["log"] == CENTRAL_DEBUG_LOG:
            event["spec"] = selector if selector and IDENTIFIER.fullmatch(selector) else None


def argv_fingerprint(value: str) -> str:
    # Legacy debug logs expose only the first line of the argv header.
    header = value.splitlines()[0] if value else ""
    return hashlib.sha256(header.encode("utf-8", errors="surrogatepass")).hexdigest()


def option(words: list[str], flag: str) -> str | None:
    for index, word in enumerate(words):
        if word.startswith(flag + "="):
            return word.partition("=")[2]
        if word == flag and index + 1 < len(words):
            return words[index + 1]
    return None


# Boolean flags accepted by ``prompt`` / ``review-helper``: they consume no value.
POSITIONAL_SWITCHES = {
    "--json", "--quiet", "--verbose", "--debug", "--force", "--all",
    "--dry-run", "--must-undone", "--must-done", "--help", "-h", "-v", "-d",
    "--stdin", "--details-from-stdin", "--evidence-from-stdin",
}
# Short options that take a value and therefore support the attached form ``-oreport``.
SHORT_VALUE_OPTIONS = {"-o"}


def takes_value(word: str) -> bool:
    """Return True when ``word`` is an option consuming the following token as its value."""
    if "=" in word:
        return False
    if word in POSITIONAL_SWITCHES:
        return False
    # ``-oreport`` carries its value inline, so nothing is consumed.
    return not (len(word) > 2 and word[:2] in SHORT_VALUE_OPTIONS)


def positional_selector(words: list[str], verb: str) -> str | None:
    """Return the first positional token after the verb, skipping option values."""
    if verb not in words:
        return None
    arguments = iter(words[words.index(verb) + 1:])
    for word in arguments:
        if word.startswith("-"):
            if takes_value(word):
                next(arguments, None)
            continue
        if IDENTIFIER.fullmatch(word):
            return word
    return None


TODO_VALUE_OPTIONS = {
    "--name", "--todo-file", "--todo-json", "--id", "--from", "--to",
    "--before", "--after", "--step-name", "--details", "--completed-at",
    "--commit-title", "--skip-commit", "--format",
}
TODO_SWITCHES = {
    "--details-from-stdin", "--done", "--undone", "--wrap", "--no-wrap",
    "-h", "--help",
}


def todo_selector(words: list[str], verb: str) -> tuple[str | None, str | None]:
    """Read the transaction action and spec without mistaking option values for them."""
    positionals, locators = [], {}
    arguments = iter(words[words.index("todo-helper") + 1:])
    for word in arguments:
        if word == "--":
            positionals.extend(arguments)
            break
        flag, equals, value = word.partition("=")
        if flag in TODO_VALUE_OPTIONS:
            value = value if equals else next(arguments, None)
            if value is None:
                return None, None
            if flag in {"--name", "--todo-file", "--todo-json"}:
                locators[flag] = value
        elif word in TODO_SWITCHES:
            continue
        elif word.startswith("-"):
            return None, None
        else:
            positionals.append(word)
    if not positionals or positionals.pop(0) != verb:
        return None, None
    action = None
    if verb == "transaction":
        if not positionals or positionals[0] not in {"start", "commit", "rollback"}:
            return None, None
        action = positionals.pop(0)
    if len(positionals) > 1 or len(positionals) + len(locators) != 1:
        return action, None
    if {"--todo-file", "--todo-json"} & locators.keys():
        return action, None
    return action, locators.get("--name", positionals[0] if positionals else None)


def parse(lines: list[str], source: str, gaps: set) -> list:
    spec = log_spec_name(source)
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
                    words = line.split()[2:]
                    if not any(word in {"todo-helper", "todo_helper"} for word in words):
                        gaps.add("unrecognized_cli_log")
                        words = []
                    else:
                        command["_argv_unparsed"] = True
                words = [word.replace("_", "-") if word in {
                    "apply_helper", "create_helper", "review_helper", "todo_helper",
                } else word for word in words]
                name = next((word for word in words if not word.startswith("-")), "")
                if IDENTIFIER.fullmatch(name):
                    command.update(
                        action="spex.command", command=name,
                        _argv_fingerprint=argv_fingerprint(line.removeprefix("argv: spex ")),
                    )
                    if verb := command_verb(words, name):
                        command["subcommand"] = verb.replace("_", "-")
                        if name == "create-helper" and verb.replace("_", "-") == "post-action":
                            command["event_type"] = option(words, "--event-type")
                if name == "todo-helper" and command.get("subcommand"):
                    action, selector = todo_selector(words, verb)
                    if action:
                        command["transaction_action"] = action
                else:
                    selector = option(words, "--name")
                if (selector is None and source == CENTRAL_DEBUG_LOG
                        and name in {"apply-helper", "review-helper", "prompt"}
                        and command.get("subcommand")):
                    # Some pinned refs use a positional spec selector after the verb.
                    selector = positional_selector(words, verb)
                if selector and IDENTIFIER.fullmatch(selector):
                    if spec is None:
                        command["spec"] = selector
                    elif selector != spec and not spec.endswith("-" + selector):
                        # A selector may be a partial name; keep the resolved path.
                        if selector not in spec:
                            gaps.add("conflicting_trace_spec")
                            command["spec"] = None
                step_flag = "--id" if name == "todo-helper" else "--step"
                step = option(words, step_flag)
                if step and IDENTIFIER.fullmatch(step):
                    command["step"] = step
                if name == "todo-helper":
                    todo_file = option(words, "--todo-file") or option(words, "--todo-json")
                    if todo_file:
                        command["todo_file_hash"] = hashlib.sha256(todo_file.encode()).hexdigest()
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
