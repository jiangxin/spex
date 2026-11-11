"""Capture trial state and evaluate deterministic Spex workflow checks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from workspace import Trial, git


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True).encode("utf-8")


def capture(trial: Trial) -> dict:
    """Capture Git and spec state without following worktree symlinks."""
    files = git(trial.repo, "ls-files", "-z", "-c", "-o", "--exclude-standard", env=trial.env)
    paths = sorted(set(files.decode("utf-8", "surrogateescape").split("\0")) - {""})
    state = {
        "head": git(trial.repo, "rev-parse", "HEAD", env=trial.env).decode().strip(),
        "status": git(trial.repo, "status", "--porcelain=v1", "-z", env=trial.env).decode(
            "utf-8", "surrogateescape"
        ),
        "index": digest(git(trial.repo, "ls-files", "-s", "-z", env=trial.env)),
        "files": {name: file_state(trial.repo, name) for name in paths},
        "specs": {},
    }
    root = trial.repo / ".spex" / "specs"
    if root.resolve() == root:
        for spec in sorted(root.glob("*")):
            if spec.is_dir() and not spec.is_symlink():
                state["specs"][spec.name] = read_spec(spec)
    return state


def file_state(root: Path, name: str) -> dict | None:
    path = root / name
    if path.parent.resolve() != path.parent or not path.is_file() and not path.is_symlink():
        return None
    if path.is_symlink():
        return {"link": str(path.readlink())}
    return {"sha256": digest(path.read_bytes()), "mode": path.stat().st_mode & 0o777}


def read_spec(path: Path) -> dict:
    record = {}
    for name in ("spec.md", "todo.json", "meta.json"):
        artifact = path / name
        if not artifact.is_file() or artifact.is_symlink():
            continue
        content = artifact.read_text(encoding="utf-8", errors="replace")
        if artifact.suffix == ".json":
            try:
                content = json.loads(content)
            except ValueError:
                content = {"invalid_json": content}
        record[name] = content
    return record


def persist_turn(
    directory: Path,
    turn: int,
    state: dict,
    *,
    user_input: str | None = None,
    reply: str | None = None,
    events: list | None = None,
    acceptance: dict | None = None,
) -> dict:
    """Persist a complete evidence bundle outside the model worktree."""
    artifacts = {
        "state": state,
        "input": user_input,
        "reply": reply,
        "events": events,
        "acceptance": acceptance,
    }
    entries = {
        kind: {"id": f"turn-{turn}:{kind}", "sha256": digest(encode(value)), "value": value}
        for kind, value in artifacts.items() if value is not None
    }
    bundle = {"turn": turn, "artifacts": entries}
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"turn-{turn}.json").open("xb") as stream:
        stream.write(encode(bundle) + b"\n")
    return bundle


def completed(state: dict) -> dict:
    return {key: task for key, task in spec_tasks(state) if task.get("completed_at")}


def spec_tasks(state: dict):
    for spec, artifacts in state["specs"].items():
        tasks = artifacts.get("todo.json")
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict) and isinstance(task.get("id"), str):
                    yield (spec, task["id"]), task


EXPECTATIONS = {
    "no-code-change": "Git HEAD, index, status and workspace files are unchanged",
    "no-spec-write": "Spec artifacts are unchanged",
    "one-spec-changed": "Exactly one spec changed, with no added or removed specs",
    "completed-preserved": "Previously completed tasks are unchanged",
    "one-step": "Exactly one additional task is completed and prior completions are preserved",
    "no-progress": "No additional task is completed and prior completions are preserved",
    "no-post-action": "No apply post-action was invoked",
    "post-action": "Apply post-action succeeded",
    "review-failure-stop": "A review failure ended the turn without further workflow activity",
    "resumed-review": "Review started at the existing step commit and tracked any fixes",
}


def check_gate(check: str, before: dict, after: dict) -> dict:
    """Return a gate verdict; missing normalized trace cannot prove a trace gate."""
    previous = before["artifacts"]["state"]
    current = after["artifacts"]["state"]
    trace = after["artifacts"].get("events")
    old, new = previous["value"], current["value"]
    done, now = completed(old), completed(new)
    preserved = all(now.get(task) == value for task, value in done.items())
    trace_gate = check in {"no-post-action", "post-action", "review-failure-stop", "resumed-review"}
    if check == "resumed-review":
        passed = resumed_review(old, now, trace)
    elif trace_gate:
        passed = trace_check(check, trace, preserved and now == done)
    else:
        passed = {
            "no-code-change": all(
                old[key] == new[key] for key in ("head", "status", "index", "files")
            ),
            "no-spec-write": old["specs"] == new["specs"],
            "one-spec-changed": old["specs"].keys() == new["specs"].keys() and sum(
                artifacts != new["specs"].get(name)
                for name, artifacts in old["specs"].items()
            ) == 1,
            "completed-preserved": preserved,
            "one-step": preserved and len(now) == len(done) + 1,
            "no-progress": preserved and now == done,
        }[check]
    refs = [previous["id"], current["id"]]
    if trace_gate and trace is not None:
        refs.append(trace["id"])
    verdict = "insufficient_evidence" if passed is None else "pass" if passed else "fail"
    return {
        "check_id": check,
        "phase": "workflow",
        "expected": EXPECTATIONS[check],
        "verdict": verdict,
        "evidence_refs": refs,
    }


def same_commit(left: str, right: str) -> bool:
    return bool(
        re.fullmatch(r"[0-9a-f]{7,40}", left)
        and re.fullmatch(r"[0-9a-f]{7,40}", right)
        and (left.startswith(right) or right.startswith(left))
    )


def resumed_review(before: dict, completed_after: dict, trace: dict | None) -> bool | None:
    if trace is None:
        return None
    seed = before["head"]
    pending = [
        key for key, task in spec_tasks(before)
        if not task.get("completed_at")
        and same_commit(seed, str(task.get("commit_title", "")).partition(":")[0])
    ]
    if len(pending) != 1:
        return False
    spec, step = pending[0]
    final = completed_after.get((spec, step), {})
    final_sha = str(final.get("commit_title", "")).partition(":")[0]
    events = [
        event for event in trace["value"]
        if event.get("action") == "apply.review" and event.get("exit_code") == 0
        and event.get("spec") == spec
    ]
    start = next((i for i, event in enumerate(events) if event.get("mode") == "full"), None)
    if start is None:
        return False
    if not same_commit(seed, events[start].get("commit", "")):
        return False
    current_sha = seed
    for event in events[start + 1:]:
        if event.get("step") == step and "new_commit" in event:
            if not same_commit(current_sha, event.get("base_commit", "")):
                return False
            current_sha = event["new_commit"]
    return same_commit(current_sha, final_sha)


def trace_check(check: str, trace: dict | None, no_progress: bool) -> bool | None:
    if check == "review-failure-stop" and not no_progress:
        return False
    if trace is None:
        return None
    # Adapters use action/exit_code for normalized command events.
    events = trace["value"]
    post = [event for event in events if event.get("action") == "apply.post-action"]
    if check == "no-post-action":
        return not post
    if check == "post-action":
        return any(event.get("exit_code") == 0 for event in post)
    if post:
        return False
    review_unknown = False
    for index, event in enumerate(events):
        if event.get("action") != "apply.review":
            continue
        exit_code = event.get("exit_code")
        if type(exit_code) is not int:
            review_unknown = True
        elif exit_code != 0:
            later_actions = [item.get("action") for item in events[index + 1:]]
            if any(
                isinstance(action, str) and action.startswith("apply.") for action in later_actions
            ):
                return False
            return None if any(action != "git.read-head" for action in later_actions) else True
    return None if review_unknown else False
