#!/usr/bin/env python3
"""CRUD operations for per-step review finding files.

Files live at ``<spec_dir>/review-step-N.json`` where N is derived from
the step id (e.g. ``step-1`` → ``review-step-1.json``).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

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
    return data


def save_review(path: Path, data: dict) -> None:
    """Atomically write the review JSON file."""
    atomic_write_json(path, data)


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


def cmd_init(path: Path, step_id: str, commit_sha: str) -> None:
    """Create or reset a review file for the step."""
    data = {
        "step_id": step_id,
        "commit_sha": commit_sha,
        "round": 1,
        "findings": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    save_review(path, data)
    logger.info("Initialized '%s'.", path.name)
    # Programmatic stdout: JSON only (path is in review_file).
    print(json.dumps({
        "review_file": str(path),
        "step_id": step_id,
        "commit_sha": commit_sha,
        "round": 1,
    }))


def cmd_append(path: Path, args) -> None:
    """Append a finding to the review file."""
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

    data = load_review(path)
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


def cmd_bump_round(path: Path) -> None:
    """Increment the review round counter."""
    data = load_review(path)
    data["round"] = int(data.get("round", 1)) + 1
    save_review(path, data)
    logger.info("Bumped round to %d.", data["round"])
    print(json.dumps({"round": data["round"]}))


def cmd_status(path: Path, as_json: bool) -> None:
    """Print review status (open counts and done flag)."""
    data = load_review(path)
    open_major, open_minor = _count_open(data["findings"])
    round_num = int(data.get("round", 1))
    payload = {
        "step_id": data.get("step_id", ""),
        "commit_sha": data.get("commit_sha", ""),
        "round": round_num,
        "open_major": open_major,
        "open_minor": open_minor,
        "done": open_major == 0,
        "review_file": path.name,
    }
    if as_json:
        print(json.dumps(payload))
    else:
        print(
            f"round={payload['round']} "
            f"open_major={payload['open_major']} "
            f"open_minor={payload['open_minor']} "
            f"done={str(payload['done']).lower()}"
        )


def cmd_show(path: Path, open_only: bool, as_json: bool) -> None:
    """Display findings, optionally filtering to open items."""
    data = load_review(path)
    findings = data["findings"]
    if open_only:
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


def _format_open_findings_markdown(findings: list) -> str:
    """Format open findings as markdown for prompt injection."""
    open_items = [
        f for f in findings
        if isinstance(f, dict) and not f.get("completed_at")
    ]
    if not open_items:
        return "(no open findings)"
    parts = []
    for item in open_items:
        block = [
            f"### {item.get('id', '')}: {item.get('title', '')}",
            f"- severity: {item.get('severity', '')}",
            f"- category: {item.get('category', '')}",
        ]
        details = (item.get("details") or "").strip()
        if details:
            block.append("")
            block.append(details)
        parts.append("\n".join(block))
    return "\n\n".join(parts)


def load_open_findings_text(path: Path) -> str:
    """Load review file and return markdown for open findings."""
    data = load_review(path)
    return _format_open_findings_markdown(data["findings"])


def _build_parser():
    """Build the top-level parser with subcommand sub-parsers."""
    parser = ArgumentParser(
        prog="spex review-helper",
        description=(
            "Operate on per-step review finding files "
            "(init, append, edit, bump-round, status, show)."
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
        description="Append a finding to the review file.",
        help="Append a finding",
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
        description="Increment the review round counter.",
        help="Increment review round",
    )
    p_bump.add_argument("--step", required=True, help="Step id")

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

    return parser


def main(argv=None):
    """Parse args, resolve review path, route to subcommand."""
    parser = _build_parser()
    args = parser.parse(argv)

    if not args.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(0)

    step_id = args.step
    path = resolve_review_path(args.name, step_id)

    if args.subcmd == "init":
        cmd_init(path, step_id, args.commit_sha)
    elif args.subcmd == "append":
        cmd_append(path, args)
    elif args.subcmd == "edit":
        cmd_edit(path, args)
    elif args.subcmd == "bump-round":
        cmd_bump_round(path)
    elif args.subcmd == "status":
        cmd_status(path, args.json_mode)
    elif args.subcmd == "show":
        cmd_show(path, args.open_only, args.json_mode)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
