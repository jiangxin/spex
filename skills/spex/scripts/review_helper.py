#!/usr/bin/env python3
"""CRUD operations for per-step review finding files.

Files live at ``<spec_dir>/review-step-N.json`` where N is derived from
the step id (e.g. ``step-1`` → ``review-step-1.json``).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from cli import ArgumentParser
from common import (
    atomic_write_json,
    local_iso_timestamp,
    logger,
    resolve_spec_dir,
)

VALID_SEVERITIES = ("major", "minor")
VALID_CATEGORIES = (
    "lint",
    "tests",
    "commit-message",
    "code-quality",
    "performance",
    "concurrency",
    "security",
    "other",
)
# Caps full review rounds only; delta review must not increment ``round``.
MAX_REVIEW_ROUND = 3
VALID_MODES = ("full", "delta")

VALID_SUBCOMMANDS = (
    "init",
    "append",
    "edit",
    "bump-round",
    "set-commit",
    "status",
    "show",
    "next",
    "open-batch",
    "set-pending",
    "complete-batch",
)

_PARSE_ARGV: Optional[list[str]] = None

_STEP_NUM_RE = re.compile(r"(\d+)$")


def step_number(step_id: str) -> str:
    """Extract trailing digits from a step id (e.g. step-1 → 1)."""
    match = _STEP_NUM_RE.search(step_id or "")
    if not match:
        logger.error(
            "Error: cannot derive step number from id '%s'.",
            step_id,
        )
        sys.exit(1)
    return match.group(1)


def review_filename(step_id: str) -> str:
    """Return review-step-N.json for the given step id."""
    return f"review-step-{step_number(step_id)}.json"


def resolve_review_path(spec_name: str, step_id: str) -> Path:
    """Resolve the review JSON path under the spec directory."""
    spec_dir = resolve_spec_dir(spec_name)
    return spec_dir / review_filename(step_id)


def _resolve_completed_at(value):
    """Resolve the special value 'now' to a local ISO timestamp."""
    if isinstance(value, str) and value.lower() == "now":
        return local_iso_timestamp()
    return value


def _default_batch_state(commit_sha: str = "") -> dict:
    """Return default batch-state fields for a new or legacy review."""
    return {
        "mode": "full",
        "reviewed_commit_sha": commit_sha or "",
        "pending_findings": [],
        "pending_has_major": False,
        "fix_base_commit_sha": "",
        "fixed_commit_sha": "",
        "check_evidence": None,
    }


def normalize_review_state(data: dict) -> dict:
    """Fill missing/malformed batch-state fields with backward-compatible defaults.

    Mutates ``data`` in place and returns it. Legacy files without the new
    keys behave as a full review with no pending batch. Invalid types are
    replaced rather than raising, so callers can still query open findings.
    """
    defaults = _default_batch_state(str(data.get("commit_sha") or ""))
    mode = data.get("mode", defaults["mode"])
    if mode not in VALID_MODES:
        mode = defaults["mode"]
    data["mode"] = mode

    reviewed = data.get("reviewed_commit_sha", defaults["reviewed_commit_sha"])
    if not isinstance(reviewed, str):
        reviewed = defaults["reviewed_commit_sha"]
    data["reviewed_commit_sha"] = reviewed

    pending = data.get("pending_findings", defaults["pending_findings"])
    if not isinstance(pending, list):
        pending = list(defaults["pending_findings"])
    else:
        pending = [str(x) for x in pending if x is not None and str(x)]
    data["pending_findings"] = pending

    if "pending_has_major" not in data or not isinstance(
        data.get("pending_has_major"), bool,
    ):
        # Missing or non-bool: derive from pending IDs + findings.
        pending_has_major = _pending_ids_have_major(data, pending)
    else:
        pending_has_major = data["pending_has_major"]
    data["pending_has_major"] = pending_has_major

    for key in ("fix_base_commit_sha", "fixed_commit_sha"):
        value = data.get(key, defaults[key])
        if not isinstance(value, str):
            value = defaults[key]
        data[key] = value

    evidence = data.get("check_evidence", defaults["check_evidence"])
    if evidence is not None and not isinstance(evidence, dict):
        evidence = defaults["check_evidence"]
    data["check_evidence"] = evidence
    return data


def _pending_ids_have_major(data: dict, pending_ids: list) -> bool:
    """True if any pending finding id refers to an open major finding."""
    if not pending_ids:
        return False
    by_id = {
        item.get("id"): item
        for item in data.get("findings", [])
        if isinstance(item, dict) and item.get("id")
    }
    for fid in pending_ids:
        item = by_id.get(fid)
        if (
            isinstance(item, dict)
            and not item.get("completed_at")
            and item.get("severity") == "major"
        ):
            return True
    return False


def load_review(path: Path) -> dict:
    """Load a review file; exit on missing or invalid JSON."""
    if not path.is_file():
        logger.error("Error: review file not found: %s", path)
        sys.exit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Error: invalid JSON in '%s': %s", path, exc)
        sys.exit(1)
    if not isinstance(data, dict):
        logger.error("Error: review file must be a JSON object.")
        sys.exit(1)
    if "findings" not in data or not isinstance(data["findings"], list):
        logger.error("Error: review file missing 'findings' list.")
        sys.exit(1)
    return normalize_review_state(data)


def save_review(path: Path, data: dict) -> None:
    """Atomically write the review JSON file (batch-state fields normalized)."""
    atomic_write_json(path, normalize_review_state(data))


def _count_open(findings: list) -> tuple[int, int]:
    """Return (open_major, open_minor) counts."""
    major = 0
    minor = 0
    for item in findings:
        if not isinstance(item, dict):
            continue
        if item.get("completed_at"):
            continue
        severity = item.get("severity", "")
        if severity == "major":
            major += 1
        elif severity == "minor":
            minor += 1
    return major, minor


def _format_finding(item: dict) -> str:
    """Format a single finding for text display."""
    status = "done" if item.get("completed_at") else "open"
    return (
        f"- [{status}] {item.get('id', '')} "
        f"({item.get('severity', '')}/{item.get('category', '')}): "
        f"{item.get('title', '')}"
    )


def _new_review_document(step_id: str, commit_sha: str) -> dict:
    """Build a fresh review document including batch-state defaults."""
    data = {
        "step_id": step_id,
        "commit_sha": commit_sha,
        "round": 1,
        "findings": [],
    }
    data.update(_default_batch_state(commit_sha))
    return data


def cmd_init(path: Path, step_id: str, commit_sha: str) -> None:
    """Create or reset a review file for the step."""
    data = _new_review_document(step_id, commit_sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_review(path, data)
    logger.info("Initialized '%s'.", path.name)
    # Programmatic stdout: JSON only (path is in review_file).
    print(json.dumps({
        "review_file": str(path),
        "step_id": step_id,
        "commit_sha": commit_sha,
        "round": 1,
        "mode": data["mode"],
    }))


def _ensure_review_for_append(
    path: Path, step_id: str, commit_sha: Optional[str],
) -> dict:
    """Load review file, or create it when missing (lazy create).

    ``--commit`` is required when the file does not exist yet.
    """
    if path.is_file():
        return load_review(path)
    if not commit_sha:
        logger.error(
            "Error: review file '%s' does not exist; "
            "pass --commit to create it on first append.",
            path.name,
        )
        sys.exit(1)
    data = _new_review_document(step_id, commit_sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_review(path, data)
    logger.info("Created '%s' on first append.", path.name)
    return data


def cmd_append(path: Path, args) -> None:
    """Append a finding to the review file (lazy-create if missing)."""
    if args.details_from_stdin:
        details = sys.stdin.read()
    elif args.details is not None:
        details = args.details
    else:
        details = ""

    if args.severity not in VALID_SEVERITIES:
        logger.error(
            "Error: severity must be one of: %s.",
            ", ".join(VALID_SEVERITIES),
        )
        sys.exit(1)

    if args.category not in VALID_CATEGORIES:
        logger.error(
            "Error: category must be one of: %s.",
            ", ".join(VALID_CATEGORIES),
        )
        sys.exit(1)

    data = _ensure_review_for_append(
        path, args.step, getattr(args, "commit_sha", None),
    )
    round_num = int(data.get("round", 1))
    if round_num >= 2 and args.severity == "minor":
        logger.error(
            "Error: round %d only allows major findings; "
            "refusing minor id '%s'.",
            round_num,
            args.id,
        )
        sys.exit(1)

    for item in data["findings"]:
        if isinstance(item, dict) and item.get("id") == args.id:
            logger.error("Error: duplicate finding id '%s'.", args.id)
            sys.exit(1)

    entry = {
        "id": args.id,
        "severity": args.severity,
        "category": args.category,
        "title": args.title,
        "details": details,
        "completed_at": "",
    }
    data["findings"].append(entry)
    save_review(path, data)
    logger.info("Appended finding '%s'.", args.id)


def cmd_edit(path: Path, args) -> None:
    """Edit an existing finding by ID."""
    details = args.details
    if args.details_from_stdin:
        details = sys.stdin.read()

    completed_at = args.completed_at
    if completed_at is not None:
        completed_at = _resolve_completed_at(completed_at)

    data = load_review(path)
    found = False
    for item in data["findings"]:
        if isinstance(item, dict) and item.get("id") == args.id:
            if args.severity is not None:
                if args.severity not in VALID_SEVERITIES:
                    logger.error(
                        "Error: severity must be one of: %s.",
                        ", ".join(VALID_SEVERITIES),
                    )
                    sys.exit(1)
                item["severity"] = args.severity
            if args.category is not None:
                if args.category not in VALID_CATEGORIES:
                    logger.error(
                        "Error: category must be one of: %s.",
                        ", ".join(VALID_CATEGORIES),
                    )
                    sys.exit(1)
                item["category"] = args.category
            if args.title is not None:
                item["title"] = args.title
            if details is not None:
                item["details"] = details
            if completed_at is not None:
                item["completed_at"] = completed_at
            found = True
            break

    if not found:
        logger.error("Error: finding id '%s' not found.", args.id)
        sys.exit(1)

    save_review(path, data)
    logger.info("Updated finding '%s'.", args.id)


def cmd_bump_round(path: Path, commit_sha: str) -> None:
    """Increment full-review round and update commit_sha; preserve findings.

    ``round`` counts full review rounds only (capped by MAX_REVIEW_ROUND).
    Delta reviews must not call this; a bump always returns to mode=full.
    """
    data = load_review(path)
    current = int(data.get("round", 1))
    if current >= MAX_REVIEW_ROUND:
        logger.error(
            "Error: cannot bump-round past max review round %d "
            "(current round=%d).",
            MAX_REVIEW_ROUND,
            current,
        )
        sys.exit(1)
    data["round"] = current + 1
    data["commit_sha"] = commit_sha
    data["mode"] = "full"
    data["reviewed_commit_sha"] = commit_sha
    # Clear prior fix batch; a new full round starts fresh.
    data["pending_findings"] = []
    data["pending_has_major"] = False
    data["fix_base_commit_sha"] = ""
    data["fixed_commit_sha"] = ""
    data["check_evidence"] = None
    save_review(path, data)
    logger.info(
        "Bumped round to %d (commit_sha=%s).",
        data["round"], commit_sha,
    )
    print(json.dumps({
        "round": data["round"],
        "commit_sha": commit_sha,
        "mode": data["mode"],
        "findings_count": len(data.get("findings", [])),
    }))
    from debug_log import emit_apply_anchor

    emit_apply_anchor(
        path.parent,
        f"===== APPLY review round → {data['round']} =====",
    )


def cmd_set_commit(path: Path, commit_sha: str) -> None:
    """Update commit_sha only; preserve round and findings."""
    data = load_review(path)
    data["commit_sha"] = commit_sha
    save_review(path, data)
    logger.info(
        "Set commit_sha=%s (round=%s).",
        commit_sha, data.get("round", 1),
    )
    print(json.dumps({
        "commit_sha": commit_sha,
        "round": int(data.get("round", 1)),
        "findings_count": len(data.get("findings", [])),
    }))


def _clean_status_payload(path: Path, step_id: str = "") -> dict:
    """Status when no review file exists (no findings recorded)."""
    return {
        "step_id": step_id,
        "commit_sha": "",
        "round": 1,
        "open_major": 0,
        "open_minor": 0,
        "needs_fix": False,
        "ready_to_complete": True,
        "done": True,
        "exists": False,
        "review_file": path.name,
    }


def cmd_status(path: Path, as_json: bool, step_id: str = "") -> None:
    """Print review status (open counts and fix/complete flags)."""
    if not path.is_file():
        payload = _clean_status_payload(path, step_id)
    else:
        data = load_review(path)
        open_major, open_minor = _count_open(data["findings"])
        round_num = int(data.get("round", 1))
        needs_fix = open_major > 0 or open_minor > 0
        # ready_to_complete: no open majors, and either no open findings
        # or max round reached (open minors may remain after max rounds).
        ready_to_complete = (
            open_major == 0
            and (not needs_fix or round_num >= MAX_REVIEW_ROUND)
        )
        payload = {
            "step_id": data.get("step_id", "") or step_id,
            "commit_sha": data.get("commit_sha", ""),
            "round": round_num,
            "open_major": open_major,
            "open_minor": open_minor,
            "needs_fix": needs_fix,
            "ready_to_complete": ready_to_complete,
            # done: no open findings
            "done": not needs_fix,
            "exists": True,
            "review_file": path.name,
        }
    if as_json:
        print(json.dumps(payload))
    else:
        print(
            f"round={payload['round']} "
            f"open_major={payload['open_major']} "
            f"open_minor={payload['open_minor']} "
            f"needs_fix={str(payload['needs_fix']).lower()} "
            f"ready_to_complete={str(payload['ready_to_complete']).lower()} "
            f"done={str(payload['done']).lower()} "
            f"exists={str(payload['exists']).lower()}"
        )


def cmd_show(
    path: Path,
    open_only: bool,
    as_json: bool,
    finding_id: Optional[str] = None,
) -> None:
    """Display findings, optionally filtering to open items or one id."""
    data = load_review(path)
    findings = data["findings"]
    if finding_id:
        item = get_finding_by_id(data, finding_id)
        if item is None:
            logger.error("Error: finding id '%s' not found.", finding_id)
            sys.exit(1)
        findings = [item]
    elif open_only:
        findings = [
            f for f in findings
            if isinstance(f, dict) and not f.get("completed_at")
        ]

    if as_json:
        print(json.dumps({
            "step_id": data.get("step_id", ""),
            "commit_sha": data.get("commit_sha", ""),
            "round": data.get("round", 1),
            "findings": findings,
        }, indent=2, ensure_ascii=False))
        return

    if not findings:
        print("(no findings)" if not open_only else "(no open findings)")
        return
    for item in findings:
        if isinstance(item, dict):
            print(_format_finding(item))
            details = item.get("details") or ""
            if details.strip():
                for line in details.strip().splitlines():
                    print(f"    {line}")


def _format_finding_markdown(item: dict) -> str:
    """Format a single finding as markdown for prompt injection."""
    block = [
        f"### {item.get('id', '')}: {item.get('title', '')}",
        f"- severity: {item.get('severity', '')}",
        f"- category: {item.get('category', '')}",
    ]
    details = (item.get("details") or "").strip()
    if details:
        block.append("")
        block.append(details)
    return "\n".join(block)


def _format_open_findings_markdown(findings: list) -> str:
    """Format open findings as markdown for prompt injection."""
    open_items = [
        f for f in findings
        if isinstance(f, dict) and not f.get("completed_at")
    ]
    if not open_items:
        return "(no open findings)"
    return "\n\n".join(_format_finding_markdown(item) for item in open_items)


def get_open_findings(data: dict) -> list:
    """Return open (incomplete) findings from a review document."""
    return [
        f for f in data.get("findings", [])
        if isinstance(f, dict) and not f.get("completed_at")
    ]


def get_finding_by_id(data: dict, finding_id: str) -> Optional[dict]:
    """Return a finding dict by id, or None."""
    for item in data.get("findings", []):
        if isinstance(item, dict) and item.get("id") == finding_id:
            return item
    return None


def _finding_summary(item: dict) -> dict:
    """Stable subset of finding fields for batch query output."""
    return {
        "id": item.get("id", ""),
        "severity": item.get("severity", ""),
        "category": item.get("category", ""),
        "title": item.get("title", ""),
        "details": item.get("details", ""),
    }


def build_open_batch_payload(
    data: Optional[dict],
    path: Path,
    step_id: str = "",
    exists: bool = True,
) -> dict:
    """Build the open-batch JSON payload (stable finding order + has_major)."""
    if data is None:
        defaults = _default_batch_state()
        return {
            "step_id": step_id,
            "commit_sha": "",
            "round": 1,
            "mode": defaults["mode"],
            "reviewed_commit_sha": "",
            "pending_findings": [],
            "pending_has_major": False,
            "fix_base_commit_sha": "",
            "fixed_commit_sha": "",
            "check_evidence": None,
            "has_major": False,
            "open_count": 0,
            "findings": [],
            "exists": False,
            "review_file": path.name,
        }
    data = normalize_review_state(data)
    open_items = get_open_findings(data)
    has_major = any(item.get("severity") == "major" for item in open_items)
    return {
        "step_id": data.get("step_id", "") or step_id,
        "commit_sha": data.get("commit_sha", ""),
        "round": int(data.get("round", 1)),
        "mode": data["mode"],
        "reviewed_commit_sha": data["reviewed_commit_sha"],
        "pending_findings": list(data["pending_findings"]),
        "pending_has_major": bool(data["pending_has_major"]),
        "fix_base_commit_sha": data["fix_base_commit_sha"],
        "fixed_commit_sha": data["fixed_commit_sha"],
        "check_evidence": data["check_evidence"],
        "has_major": has_major,
        "open_count": len(open_items),
        "findings": [_finding_summary(item) for item in open_items],
        "exists": exists,
        "review_file": path.name,
    }


def cmd_open_batch(path: Path, step_id: str = "") -> None:
    """Print all open findings for the current round as one JSON batch."""
    if not path.is_file():
        print(json.dumps(build_open_batch_payload(
            None, path, step_id=step_id, exists=False,
        )))
        return
    data = load_review(path)
    print(json.dumps(build_open_batch_payload(
        data, path, step_id=step_id, exists=True,
    )))


def parse_id_list(raw: str) -> list[str]:
    """Parse a comma-separated finding-id list into non-empty strings."""
    if not raw or not str(raw).strip():
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def sha_matches(left: str, right: str) -> bool:
    """True if two commit SHAs refer to the same commit (prefix-safe)."""
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    # Accept short/full prefix match when both look like hex SHAs.
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 7:
        return False
    return longer.startswith(shorter) and all(
        c in "0123456789abcdef" for c in longer
    )


def get_head_sha(cwd: Optional[str] = None) -> str:
    """Return full HEAD SHA, or empty string when unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def is_project_tree_clean(
    spex_root: Optional[str] = None,
    cwd: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """Return (clean, dirty_paths) excluding paths under spex_root."""
    from apply_helper import collect_dirty
    from common import get_spex_root

    root = spex_root or get_spex_root(
        workdir=cwd, require_git=False, auto_init=False,
    )
    try:
        dirty, paths, _ = collect_dirty(root, cwd=cwd)
    except (OSError, subprocess.CalledProcessError):
        return False, ["<git-status-failed>"]
    return (not dirty, list(paths))


def normalize_check_evidence(raw) -> Optional[dict]:
    """Parse and normalize check evidence; return None if invalid."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    commit_sha = raw.get("commit_sha")
    if not isinstance(commit_sha, str) or not commit_sha.strip():
        return None
    checks = raw.get("checks")
    if not isinstance(checks, list) or not checks:
        return None
    normalized_checks = []
    for item in checks:
        if not isinstance(item, dict):
            return None
        command = item.get("command")
        exit_code = item.get("exit_code")
        if not isinstance(command, str) or not command.strip():
            return None
        # bool is a subclass of int; reject so False is not treated as 0.
        if type(exit_code) is not int:
            return None
        completed_at = item.get("completed_at", "")
        if completed_at is None:
            completed_at = ""
        if not isinstance(completed_at, str):
            return None
        normalized_checks.append({
            "command": command,
            "exit_code": exit_code,
            "completed_at": completed_at,
        })
    return {
        "commit_sha": commit_sha.strip(),
        "checks": normalized_checks,
    }


def evidence_is_successful(evidence: dict, expected_sha: str) -> bool:
    """True if evidence is bound to expected_sha and every check exited 0."""
    if not sha_matches(evidence.get("commit_sha", ""), expected_sha):
        return False
    checks = evidence.get("checks") or []
    if not checks:
        return False
    return all(
        isinstance(c, dict)
        and type(c.get("exit_code")) is int
        and c.get("exit_code") == 0
        for c in checks
    )


def _finding_ids_set(ids) -> set[str]:
    """Normalize an iterable of finding ids to a set of strings."""
    return {str(x) for x in ids if x is not None and str(x)}


def validate_complete_batch(
    data: dict,
    finding_ids: list[str],
    base_sha: str,
    new_sha: str,
    evidence: dict,
    head_sha: str,
    tree_clean: bool,
) -> Optional[str]:
    """Return an error message if complete-batch validation fails."""
    data = normalize_review_state(data)
    ids = list(finding_ids)
    if not ids:
        return "finding id list is empty"
    if not base_sha or not new_sha:
        return "base and new commit SHAs are required"
    if sha_matches(base_sha, new_sha):
        return "new commit SHA must differ from base commit SHA"
    if not sha_matches(head_sha, new_sha):
        return "new commit SHA does not match current HEAD"
    if not tree_clean:
        return "project tree is dirty outside spex_root"
    if not evidence_is_successful(evidence, new_sha):
        return "check evidence missing, failed, or not bound to new SHA"

    pending = list(data.get("pending_findings") or [])
    if not pending:
        return "no pending finding batch"
    if _finding_ids_set(pending) != _finding_ids_set(ids):
        return "finding id set does not match pending batch"

    stored_base = data.get("fix_base_commit_sha") or ""
    if not stored_base or not sha_matches(stored_base, base_sha):
        return "base commit SHA does not match fix_base_commit_sha"

    review_sha = data.get("commit_sha") or ""
    if not review_sha or not sha_matches(review_sha, base_sha):
        return "review commit_sha does not match expected base"

    by_id = {
        item.get("id"): item
        for item in data.get("findings", [])
        if isinstance(item, dict) and item.get("id")
    }
    for fid in ids:
        item = by_id.get(fid)
        if item is None:
            return f"finding id '{fid}' not found"
        if item.get("completed_at"):
            return f"finding id '{fid}' is already completed"
    return None


def apply_complete_batch(
    data: dict,
    finding_ids: list[str],
    new_sha: str,
    evidence: dict,
    completed_at: Optional[str] = None,
) -> dict:
    """Mutate review data to mark the pending batch complete (in memory)."""
    stamp = completed_at or local_iso_timestamp()
    id_set = _finding_ids_set(finding_ids)
    for item in data.get("findings", []):
        if isinstance(item, dict) and item.get("id") in id_set:
            item["completed_at"] = stamp
    data["fixed_commit_sha"] = new_sha
    data["check_evidence"] = evidence
    data["commit_sha"] = new_sha
    data["pending_findings"] = []
    data["pending_has_major"] = False
    return normalize_review_state(data)


def complete_batch_already_done(
    data: dict, finding_ids: list[str], new_sha: str,
) -> bool:
    """True if this batch was already completed for new_sha (resume no-op)."""
    data = normalize_review_state(data)
    if not sha_matches(data.get("fixed_commit_sha") or "", new_sha):
        return False
    by_id = {
        item.get("id"): item
        for item in data.get("findings", [])
        if isinstance(item, dict) and item.get("id")
    }
    for fid in finding_ids:
        item = by_id.get(fid)
        if item is None or not item.get("completed_at"):
            return False
    return True


def cmd_set_pending(
    path: Path,
    finding_ids: list[str],
    base_sha: str,
) -> None:
    """Establish a pending fix batch from open finding IDs."""
    ids = list(finding_ids)
    if not ids:
        logger.error("Error: --ids must list at least one finding id.")
        sys.exit(1)
    if len(ids) != len(set(ids)):
        logger.error("Error: --ids contains duplicate finding ids.")
        sys.exit(1)
    if not base_sha:
        logger.error("Error: --base-commit is required.")
        sys.exit(1)

    data = load_review(path)
    by_id = {
        item.get("id"): item
        for item in data.get("findings", [])
        if isinstance(item, dict) and item.get("id")
    }
    for fid in ids:
        item = by_id.get(fid)
        if item is None:
            logger.error("Error: finding id '%s' not found.", fid)
            sys.exit(1)
        if item.get("completed_at"):
            logger.error(
                "Error: finding id '%s' is already completed.", fid,
            )
            sys.exit(1)

    data["pending_findings"] = ids
    data["pending_has_major"] = _pending_ids_have_major(data, ids)
    data["fix_base_commit_sha"] = base_sha
    data["fixed_commit_sha"] = ""
    data["check_evidence"] = None
    save_review(path, data)
    logger.info(
        "Set pending batch (%d findings, base=%s).",
        len(ids), base_sha,
    )
    print(json.dumps({
        "pending_findings": ids,
        "pending_has_major": data["pending_has_major"],
        "fix_base_commit_sha": base_sha,
        "count": len(ids),
    }))


def cmd_complete_batch(
    path: Path,
    finding_ids: list[str],
    base_sha: str,
    new_sha: str,
    evidence_raw,
    spex_root: Optional[str] = None,
    cwd: Optional[str] = None,
) -> None:
    """Atomically complete a pending batch after amend + verification.

    On any validation failure: exit non-zero without writing completed_at.
    Supports resume when amend already moved HEAD but the write was skipped.
    """
    evidence = normalize_check_evidence(evidence_raw)
    if evidence is None:
        logger.error(
            "Error: --evidence must be JSON with commit_sha and "
            "non-empty successful checks.",
        )
        sys.exit(1)

    data = load_review(path)
    ids = list(finding_ids)

    # Idempotent resume: batch already marked complete for this SHA.
    if complete_batch_already_done(data, ids, new_sha):
        logger.info(
            "Pending batch already completed for %s; nothing to write.",
            new_sha,
        )
        print(json.dumps({
            "completed": True,
            "resumed": True,
            "fixed_commit_sha": data.get("fixed_commit_sha", ""),
            "completed_ids": ids,
        }))
        return

    head_sha = get_head_sha(cwd)
    tree_clean, dirty_paths = is_project_tree_clean(
        spex_root=spex_root, cwd=cwd,
    )
    err = validate_complete_batch(
        data, ids, base_sha, new_sha, evidence, head_sha, tree_clean,
    )
    if err:
        logger.error("Error: complete-batch rejected: %s.", err)
        if dirty_paths and not tree_clean:
            logger.error("Dirty paths: %s", ", ".join(dirty_paths[:20]))
        sys.exit(1)

    # Snapshot open state so a failed write cannot leave a partial file
    # (atomic_write_json already replaces whole file; keep in-memory only).
    apply_complete_batch(data, ids, new_sha, evidence)
    save_review(path, data)
    logger.info(
        "Completed pending batch (%d findings, fixed=%s).",
        len(ids), new_sha,
    )
    print(json.dumps({
        "completed": True,
        "resumed": False,
        "fixed_commit_sha": new_sha,
        "completed_ids": ids,
        "check_evidence": evidence,
    }))


def cmd_next(path: Path, step_id: str = "") -> None:
    """Print the first open finding as JSON (or id=null if none)."""
    if not path.is_file():
        print(json.dumps({
            "id": None,
            "open_count": 0,
            "step_id": step_id,
            "commit_sha": "",
            "round": 1,
            "exists": False,
        }))
        return
    data = load_review(path)
    open_items = get_open_findings(data)
    if not open_items:
        print(json.dumps({
            "id": None,
            "open_count": 0,
            "step_id": data.get("step_id", "") or step_id,
            "commit_sha": data.get("commit_sha", ""),
            "round": data.get("round", 1),
            "exists": True,
        }))
        return
    item = open_items[0]
    print(json.dumps({
        "id": item.get("id", ""),
        "severity": item.get("severity", ""),
        "category": item.get("category", ""),
        "title": item.get("title", ""),
        "details": item.get("details", ""),
        "open_count": len(open_items),
        "step_id": data.get("step_id", "") or step_id,
        "commit_sha": data.get("commit_sha", ""),
        "round": data.get("round", 1),
        "exists": True,
    }))


def load_open_findings_text(path: Path) -> str:
    """Load review file and return markdown for open findings."""
    data = load_review(path)
    return _format_open_findings_markdown(data["findings"])


class ReviewHelperParser(ArgumentParser):
    """ArgumentParser with review-helper-specific usage hints."""

    def parse(self, argv=None):
        global _PARSE_ARGV
        _PARSE_ARGV = list(sys.argv[1:] if argv is None else argv)
        try:
            return super().parse(argv)
        finally:
            _PARSE_ARGV = None

    def error(self, message):
        hints = []
        if (
            _PARSE_ARGV
            and "status" in _PARSE_ARGV
            and "--step" in message
        ):
            hints.append(
                "Example: spex review-helper --name <spec> "
                "status --step step-1",
            )
        if "invalid choice" in message:
            hints.append(
                "Valid subcommands: " + ", ".join(VALID_SUBCOMMANDS),
            )
        if hints:
            super().error(message + "\n" + "\n".join(hints))
        else:
            super().error(message)


def _build_parser():
    """Build the top-level parser with subcommand sub-parsers."""
    parser = ReviewHelperParser(
        prog="spex review-helper",
        description=(
            "Operate on per-step review finding files "
            f"({', '.join(VALID_SUBCOMMANDS)})."
        ),
    )
    parser.add_argument(
        "--name", required=True, help="Spec name (required)",
    )

    subs = parser.add_subparsers(dest="subcmd", title="Subcommands")

    p_init = subs.add_parser(
        "init",
        description="Create or reset a review file for a step.",
        help="Create or reset review-step-N.json",
    )
    p_init.add_argument("--step", required=True, help="Step id (e.g. step-1)")
    p_init.add_argument(
        "--commit", required=True, dest="commit_sha",
        help="Short or full commit SHA under review",
    )

    p_append = subs.add_parser(
        "append",
        description=(
            "Append a finding to the review file. "
            "Creates the file on first append when --commit is given."
        ),
        help="Append a finding (lazy-create with --commit)",
    )
    p_append.add_argument("--step", required=True, help="Step id")
    p_append.add_argument("--id", required=True, help="Finding ID")
    p_append.add_argument(
        "--severity", required=True, choices=VALID_SEVERITIES,
        help="Finding severity",
    )
    p_append.add_argument(
        "--category", required=True, choices=VALID_CATEGORIES,
        help="Finding category",
    )
    p_append.add_argument("--title", required=True, help="Short title")
    p_append.add_argument("--details", default=None, help="Details text")
    p_append.add_argument(
        "--details-from-stdin", action="store_true",
        help="Read details from stdin",
    )
    p_append.add_argument(
        "--commit", default=None, dest="commit_sha",
        help=(
            "Commit SHA for lazy file create "
            "(required when review file does not exist yet)"
        ),
    )

    p_edit = subs.add_parser(
        "edit",
        description="Edit an existing finding by ID.",
        help="Edit a finding by ID",
    )
    p_edit.add_argument("--step", required=True, help="Step id")
    p_edit.add_argument("--id", required=True, help="Finding ID to edit")
    p_edit.add_argument(
        "--severity", default=None, choices=VALID_SEVERITIES,
        help="New severity",
    )
    p_edit.add_argument(
        "--category", default=None, choices=VALID_CATEGORIES,
        help="New category",
    )
    p_edit.add_argument("--title", default=None, help="New title")
    p_edit.add_argument("--details", default=None, help="New details text")
    p_edit.add_argument(
        "--details-from-stdin", action="store_true",
        help="Read details from stdin",
    )
    p_edit.add_argument(
        "--completed-at", default=None,
        help="Completion timestamp (or 'now')",
    )

    p_bump = subs.add_parser(
        "bump-round",
        description=(
            "Increment the review round and update commit_sha "
            "after a fix amend. Preserves existing findings."
        ),
        help="Increment round and update commit SHA",
    )
    p_bump.add_argument("--step", required=True, help="Step id")
    p_bump.add_argument(
        "--commit", required=True, dest="commit_sha",
        help="New commit SHA after amend (required)",
    )

    p_set_commit = subs.add_parser(
        "set-commit",
        description=(
            "Update commit_sha after a fix amend without changing "
            "the review round. Preserves existing findings."
        ),
        help="Update commit SHA only (no round bump)",
    )
    p_set_commit.add_argument("--step", required=True, help="Step id")
    p_set_commit.add_argument(
        "--commit", required=True, dest="commit_sha",
        help="Commit SHA after amend (required)",
    )

    p_status = subs.add_parser(
        "status",
        description="Show open finding counts and done flag.",
        help="Show review status",
    )
    p_status.add_argument("--step", required=True, help="Step id")
    p_status.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Output JSON",
    )

    p_show = subs.add_parser(
        "show",
        description="Display findings.",
        help="Display findings",
    )
    p_show.add_argument("--step", required=True, help="Step id")
    p_show.add_argument(
        "--open", action="store_true", dest="open_only",
        help="Show only open (incomplete) findings",
    )
    p_show.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Output JSON",
    )
    p_show.add_argument(
        "--id", default=None, dest="finding_id",
        help=(
            "Show a single finding by ID "
            "(ignores --open; includes completed findings)"
        ),
    )

    # Compatibility aliases for agent probes (prefer show/status/next).
    p_list = subs.add_parser(
        "list",
        description=(
            "Alias: list findings for a step as JSON summary "
            "(same as show --step … --json). "
            "Without --step, exits 0 with empty findings and a hint."
        ),
        help="Alias for show --json (summary)",
    )
    p_list.add_argument(
        "--step", default=None,
        help="Step id (optional; omit → empty findings + hint)",
    )
    p_list.add_argument(
        "--open", action="store_true", dest="open_only",
        help="Show only open (incomplete) findings",
    )

    p_get = subs.add_parser(
        "get",
        description=(
            "Alias: show one finding by ID as JSON "
            "(same as show --step … --id … --json)."
        ),
        help="Alias for show --id --json",
    )
    p_get.add_argument("--step", required=True, help="Step id")
    p_get.add_argument(
        "--id", required=True, dest="finding_id",
        help="Finding ID to show",
    )

    p_next = subs.add_parser(
        "next",
        description="Print the first open finding as JSON.",
        help="First open finding (for one-at-a-time fix loop)",
    )
    p_next.add_argument("--step", required=True, help="Step id")

    p_open_batch = subs.add_parser(
        "open-batch",
        description=(
            "Print all open findings for the current round as one "
            "JSON batch, including has_major and batch-state fields."
        ),
        help="All open findings as one batch (JSON)",
    )
    p_open_batch.add_argument("--step", required=True, help="Step id")

    p_set_pending = subs.add_parser(
        "set-pending",
        description=(
            "Establish a pending fix batch from open finding IDs "
            "and record the fix-base commit SHA."
        ),
        help="Set pending finding batch before fix",
    )
    p_set_pending.add_argument("--step", required=True, help="Step id")
    p_set_pending.add_argument(
        "--ids", required=True,
        help="Comma-separated finding IDs for the pending batch",
    )
    p_set_pending.add_argument(
        "--base-commit", required=True, dest="base_sha",
        help="Commit SHA before the batch fix amend",
    )

    p_complete = subs.add_parser(
        "complete-batch",
        description=(
            "Atomically mark a pending finding batch complete after a "
            "successful amend and verified checks. Writes nothing when "
            "validation fails (findings stay open)."
        ),
        help="Atomically complete pending batch after amend",
    )
    p_complete.add_argument("--step", required=True, help="Step id")
    p_complete.add_argument(
        "--ids", required=True,
        help="Comma-separated finding IDs (must match pending batch)",
    )
    p_complete.add_argument(
        "--base-commit", required=True, dest="base_sha",
        help="Expected fix-base / review commit SHA before amend",
    )
    p_complete.add_argument(
        "--new-commit", required=True, dest="new_sha",
        help="Commit SHA after amend (must equal current HEAD)",
    )
    p_complete.add_argument(
        "--evidence", default=None,
        help="Check evidence JSON (commit_sha + successful checks)",
    )
    p_complete.add_argument(
        "--evidence-from-stdin", action="store_true",
        help="Read check evidence JSON from stdin",
    )
    p_complete.add_argument(
        "--spex-root", default=None,
        help="Spex root to exclude from dirty-tree checks",
    )
    p_complete.add_argument(
        "--workdir", default=None,
        help="Git workdir for HEAD and dirty checks (default: cwd)",
    )

    return parser


def main(argv=None):
    """Parse args, resolve review path, route to subcommand."""
    parser = _build_parser()
    args = parser.parse(argv)

    if not args.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(0)

    # Bare `list` (archived agent probe) must exit 0, not argparse exit=2.
    if args.subcmd == "list" and not args.step:
        print(json.dumps({
            "findings": [],
            "hint": (
                "Provide --step S "
                "(same as show --step S --json)."
            ),
        }, indent=2, ensure_ascii=False))
        return

    step_id = args.step
    path = resolve_review_path(args.name, step_id)

    if args.subcmd == "init":
        cmd_init(path, step_id, args.commit_sha)
    elif args.subcmd == "append":
        cmd_append(path, args)
    elif args.subcmd == "edit":
        cmd_edit(path, args)
    elif args.subcmd == "bump-round":
        cmd_bump_round(path, args.commit_sha)
    elif args.subcmd == "set-commit":
        cmd_set_commit(path, args.commit_sha)
    elif args.subcmd == "status":
        cmd_status(path, args.json_mode, step_id=step_id)
    elif args.subcmd == "show":
        cmd_show(
            path, args.open_only, args.json_mode,
            finding_id=args.finding_id,
        )
    elif args.subcmd == "list":
        # Alias → show-style JSON summary for the step (no --id).
        cmd_show(path, args.open_only, as_json=True)
    elif args.subcmd == "get":
        # Alias → show --id --json.
        cmd_show(
            path, open_only=False, as_json=True,
            finding_id=args.finding_id,
        )
    elif args.subcmd == "next":
        cmd_next(path, step_id=step_id)
    elif args.subcmd == "open-batch":
        cmd_open_batch(path, step_id=step_id)
    elif args.subcmd == "set-pending":
        cmd_set_pending(
            path, parse_id_list(args.ids), args.base_sha,
        )
    elif args.subcmd == "complete-batch":
        if args.evidence_from_stdin:
            evidence_raw = sys.stdin.read()
        elif args.evidence is not None:
            evidence_raw = args.evidence
        else:
            logger.error(
                "Error: pass --evidence or --evidence-from-stdin.",
            )
            sys.exit(1)
        cmd_complete_batch(
            path,
            parse_id_list(args.ids),
            args.base_sha,
            args.new_sha,
            evidence_raw,
            spex_root=args.spex_root,
            cwd=args.workdir,
        )


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
