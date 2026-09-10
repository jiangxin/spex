#!/usr/bin/env python3
"""Render a Jinja2 template with metadata and output the result."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from cli import ArgumentParser
from common import (
    atomic_write_json,
    get_spex_root,
    get_template,
    load_meta,
    load_todo,
    local_iso_timestamp,
    logger,
    resolve_spec_dir,
    strip_front_matter,
)
from common import filter_completed_todos as _filter_completed_todos
from config import get_project_context
from todo_helper import normalize_skip_commit

# Review/fix prompt context (Phase 6 compact payloads).
VALID_REVIEW_MODES = ("full", "delta")
DEFAULT_REVIEW_PROMPT_MAX_BYTES = 16_384
# Keep at least this many leading bytes when truncating a diff.
_CRITICAL_DIFF_HEAD_BYTES = 4_096
# Truncate lowest-priority fields first when enforcing the size cap.
# Shrink commit_diff before current_task_description so a large diff cannot
# wipe the task body before the critical-head floor applies.
_REVIEW_CONTEXT_TRUNCATE_ORDER = (
    "spec_content_concise",
    "commit_diff",
    "current_task_description",
)
_REVIEW_CONTEXT_PROTECTED = frozenset({
    "open_findings",
    "acceptance_criteria",
    # Task body is required for review/fix prompts; shrink only after
    # non-protected fields (including commit_diff) are exhausted.
    "current_task_description",
})
_ACCEPTANCE_RE = re.compile(
    r"\*\*Acceptance criteria\*\*\s*:\s*(.*?)(?=\n\*\*[A-Z]|\n##\s|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def validate_required_meta(content, metadata):
    """Check that all keys listed in front-matter 'required' are present in metadata."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return

    front_matter = match.group(1)
    required = []
    in_required = False
    for line in front_matter.splitlines():
        if re.match(r"required:\s*$", line):
            in_required = True
            continue
        if in_required:
            # Match YAML list item format: "  - item_name"
            m = re.match(r"\s+-\s+(.+)", line)
            if m:
                required.append(m.group(1).strip().strip("\"'"))
            else:
                break

    missing = [key for key in required if key not in metadata]
    if missing:
        logger.error(
            "Error: missing required metadata: %s", ", ".join(missing)
        )
        sys.exit(1)


def _format_item_verbose(item):
    """Format a single todo item in verbose markdown style."""
    task_id = item.get("id", "")
    name = item.get("name", "")
    details = item.get("details", "")
    lines = [f"- **{task_id}**: {name}"]
    if details:
        for line in details.splitlines():
            lines.append(f"  {line}" if line else "")
    return "\n".join(lines)


def _format_item_brief(item):
    """Format a single todo item as a brief one-liner."""
    return f"- {item.get('id', '')}: {item.get('name', '')} *(details omitted)*"


def _format_item_concise(item):
    """Format a single todo item as a concise one-liner (id + name only)."""
    return f"- **{item.get('id', '')}**: {item.get('name', '')}"


def _trim_spec_content(spec_content):
    """Trim spec content for commit context using include/exclude strategy.

    Include (primary): if requirement or user-clarification sections exist,
    keep only those. Exclude (fallback): otherwise drop detailed-design,
    test-plan, constraints and keep the rest.
    """
    if not spec_content:
        return ""

    from common import parse_front_matter_description, strip_front_matter

    description = parse_front_matter_description(spec_content)

    include_sections = {"requirement", "user-clarification"}
    exclude_sections = {"detailed-design", "test-plan", "constraints"}
    marker_pattern = re.compile(r"<!--\s*spex:begin:([a-z-]+)\s*-->")

    markers = list(marker_pattern.finditer(spec_content))
    if markers:
        parsed = []
        for i, m in enumerate(markers):
            name = m.group(1)
            start = m.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(
                spec_content
            )
            parsed.append((name, spec_content[start:end].strip()))

        found_include = any(n in include_sections for n, _ in parsed)
        if found_include:
            seen = set()
            kept = []
            for name, content in parsed:
                if name in include_sections and name not in seen:
                    seen.add(name)
                    kept.append(content)
        else:
            kept = [c for n, c in parsed if n not in exclude_sections]
    else:
        body = strip_front_matter(spec_content)
        heading_pattern = re.compile(r"^(# .+)", re.MULTILINE)
        splits = heading_pattern.split(body)

        include_headings = {"# Requirement", "# User Clarification"}
        exclude_headings = {"# Detailed Design", "# Test Plan",
                            "# Constraints"}

        all_sections = []
        i = 1
        while i < len(splits):
            heading = splits[i].strip()
            content = splits[i + 1] if i + 1 < len(splits) else ""
            all_sections.append((heading, heading + content.rstrip()))
            i += 2

        found_include = any(h in include_headings for h, _ in all_sections)
        if found_include:
            seen = set()
            kept = []
            for h, s in all_sections:
                if h in include_headings and h not in seen:
                    seen.add(h)
                    kept.append(s)
        else:
            kept = [s for h, s in all_sections if h not in exclude_headings]

    parts = []
    if description:
        parts.append(description)
    if kept:
        parts.append("\n\n".join(kept))
    return "\n\n".join(parts)


def normalize_review_mode(mode) -> str:
    """Return a valid review mode (`full` or `delta`); default `full`."""
    value = (mode or "").strip().lower()
    if value in VALID_REVIEW_MODES:
        return value
    return "full"


def measure_prompt_bytes(text: str) -> int:
    """Return UTF-8 byte length of a prompt string."""
    if not text:
        return 0
    return len(str(text).encode("utf-8"))


def extract_acceptance_criteria(task_text: str) -> str:
    """Extract acceptance criteria from a task description/details block."""
    if not task_text:
        return ""
    match = _ACCEPTANCE_RE.search(task_text)
    if match:
        return match.group(1).strip()
    # Fallback: last non-empty paragraph mentioning "acceptance".
    for block in reversed(re.split(r"\n{2,}", task_text)):
        if re.search(r"acceptance\s+criteria", block, re.IGNORECASE):
            return block.strip()
    return ""


def should_render_delta_prompt(review_data: Optional[dict]) -> bool:
    """True only when a delta review is warranted (batch/open has major).

    Minor-only batches must not render or launch a delta review prompt.
    """
    if not isinstance(review_data, dict):
        return False
    import review_helper

    data = review_helper.normalize_review_state(dict(review_data))
    pending = list(data.get("pending_findings") or [])
    if pending:
        return bool(data.get("pending_has_major"))
    return any(
        item.get("severity") == "major"
        for item in review_helper.get_open_findings(data)
    )


def is_check_evidence_reusable(
    evidence,
    head_sha: str,
    required_commands=None,
    *,
    tree_clean: Optional[bool] = None,
    spex_root=None,
    cwd=None,
) -> bool:
    """True when lint/test evidence may be reused for the current HEAD.

    Evidence is reusable only when all of the following hold:
    - evidence normalizes and every check exited 0
    - evidence ``commit_sha`` matches ``head_sha``
    - project tree is clean outside spex_root
    - optional ``required_commands`` are all present in the evidence
    """
    import review_helper

    if not head_sha or not str(head_sha).strip():
        return False
    normalized = review_helper.normalize_check_evidence(evidence)
    if not normalized:
        return False
    if not review_helper.evidence_is_successful(normalized, head_sha):
        return False
    if tree_clean is None:
        tree_clean, _ = review_helper.is_project_tree_clean(
            spex_root=spex_root, cwd=cwd,
        )
    if not tree_clean:
        return False
    if required_commands:
        have = {
            str(item.get("command", ""))
            for item in (normalized.get("checks") or [])
            if isinstance(item, dict)
        }
        for command in required_commands:
            if command not in have:
                return False
    return True


def _truncate_utf8(text: str, max_bytes: int, suffix: str = "\n…[truncated]") -> str:
    """Truncate ``text`` to at most ``max_bytes`` UTF-8 bytes."""
    if max_bytes <= 0:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    suffix_bytes = suffix.encode("utf-8")
    keep = max_bytes - len(suffix_bytes)
    if keep <= 0:
        return ""
    clipped = raw[:keep]
    while clipped:
        try:
            return clipped.decode("utf-8") + suffix
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return ""


def apply_prompt_size_cap(
    fields: dict,
    max_bytes: int,
    *,
    protected=None,
    truncate_order=None,
) -> dict:
    """Return a copy of string fields truncated to fit ``max_bytes`` total.

    Protected keys (findings, acceptance criteria) are truncated only after
    all lower-priority fields are exhausted. Diff keeps a critical head when
    the budget still allows it.
    """
    if max_bytes <= 0:
        return {k: "" if isinstance(v, str) else v for k, v in fields.items()}

    out = dict(fields)
    protected_keys = set(protected or _REVIEW_CONTEXT_PROTECTED)
    order = list(truncate_order or _REVIEW_CONTEXT_TRUNCATE_ORDER)

    def _total() -> int:
        return sum(
            measure_prompt_bytes(v) for v in out.values() if isinstance(v, str)
        )

    def _shrink(key: str) -> None:
        if key not in out or not isinstance(out.get(key), str):
            return
        current = out[key]
        current_size = measure_prompt_bytes(current)
        if current_size == 0:
            return
        overflow = _total() - max_bytes
        if overflow <= 0:
            return
        target = max(0, current_size - overflow)
        if key == "commit_diff":
            others = _total() - current_size
            room = max_bytes - others
            if room >= _CRITICAL_DIFF_HEAD_BYTES:
                target = max(
                    target,
                    min(_CRITICAL_DIFF_HEAD_BYTES, current_size),
                )
            else:
                target = max(0, min(target, max(room, 0)))
        out[key] = _truncate_utf8(current, target)

    # First pass: truncate non-protected fields in priority order.
    for key in order:
        if _total() <= max_bytes:
            break
        if key in protected_keys:
            continue
        _shrink(key)

    # Second pass: shrink protected fields only if still over budget.
    if _total() > max_bytes:
        for key in list(dict.fromkeys(
            [k for k in order if k in protected_keys]
            + list(protected_keys)
        )):
            if _total() <= max_bytes:
                break
            _shrink(key)

    # Final force: shrink remaining strings in truncate order first so
    # commit_diff is reduced before current_task_description.
    if _total() > max_bytes:
        force_keys = list(order) + [
            k for k in out
            if k not in order and isinstance(out.get(k), str)
        ]
        for key in force_keys:
            if _total() <= max_bytes:
                break
            if isinstance(out.get(key), str) and out[key]:
                _shrink(key)
    return out


def _git_text(args: list, cwd: Optional[str] = None) -> str:
    """Run a git command and return stdout text, or empty on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
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


def fetch_review_diff(
    commit_sha: str,
    *,
    mode: str = "full",
    base_sha: str = "",
    fixed_sha: str = "",
    cwd: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> str:
    """Return the commit or fix-range diff for review/fix context."""
    mode = normalize_review_mode(mode)
    text = ""
    if mode == "delta" and base_sha and (fixed_sha or commit_sha):
        end = fixed_sha or commit_sha
        text = _git_text(
            ["diff", f"{base_sha}..{end}", "--"], cwd=cwd,
        )
        if not text:
            text = _git_text(
                ["diff", base_sha, end, "--"], cwd=cwd,
            )
    elif commit_sha:
        text = _git_text(["show", "--format=", "--patch", commit_sha], cwd=cwd)
        if not text:
            text = _git_text(["diff", f"{commit_sha}^!", "--"], cwd=cwd)
    if not text:
        return ""
    limit = max_bytes if max_bytes is not None else DEFAULT_REVIEW_PROMPT_MAX_BYTES
    if measure_prompt_bytes(text) > limit:
        return _truncate_utf8(text, limit)
    return text


def _format_current_task_compact(task_description: str) -> str:
    """Keep id/name/details but drop future/completed noise (already excluded)."""
    return (task_description or "").strip()


def build_compact_review_context(
    metadata: dict,
    *,
    mode: str = "full",
    review_data: Optional[dict] = None,
    finding_id: str = "",
    commit_sha: str = "",
    max_bytes: int = DEFAULT_REVIEW_PROMPT_MAX_BYTES,
    cwd: Optional[str] = None,
    include_diff: bool = True,
) -> dict:
    """Build compact metadata fields for apply-review / apply-fix prompts.

    Includes current task, acceptance criteria, relevant spec summary, open
    finding batch, and required diff. Excludes completed/future task bodies,
    completed finding details, and full long spec sections.
    """
    import review_helper

    mode = normalize_review_mode(mode)
    data = None
    if isinstance(review_data, dict):
        data = review_helper.normalize_review_state(dict(review_data))

    sha = (
        commit_sha
        or (data.get("commit_sha") if data else "")
        or metadata.get("commit_sha")
        or ""
    )
    base_sha = (data.get("fix_base_commit_sha") if data else "") or ""
    fixed_sha = (data.get("fixed_commit_sha") if data else "") or sha

    # Spec summary only (never the full long document).
    spec_summary = metadata.get("spec_content_concise") or ""
    if not spec_summary:
        spec_summary = _trim_spec_content(metadata.get("spec_content") or "")

    task_desc = _format_current_task_compact(
        metadata.get("current_task_description") or "",
    )
    acceptance = extract_acceptance_criteria(task_desc)
    if not acceptance:
        acceptance = extract_acceptance_criteria(
            metadata.get("current_task_details") or "",
        )

    open_findings = "(no open findings)"
    has_major = False
    if finding_id and data is not None:
        item = review_helper.get_finding_by_id(data, finding_id)
        if item is not None and not item.get("completed_at"):
            open_findings = review_helper._format_finding_markdown(item)
            has_major = item.get("severity") == "major"
        elif item is not None and item.get("completed_at"):
            open_findings = "(requested finding is already completed)"
    elif data is not None:
        open_items = review_helper.get_open_findings(data)
        # Prefer pending batch when set (fix/delta context).
        pending = list(data.get("pending_findings") or [])
        if pending:
            by_id = {item.get("id"): item for item in open_items}
            batch = [by_id[i] for i in pending if i in by_id]
            open_items = batch or open_items
        has_major = any(i.get("severity") == "major" for i in open_items)
        if pending:
            has_major = bool(data.get("pending_has_major")) or has_major
        open_findings = (
            review_helper._format_open_findings_markdown(open_items)
            if open_items
            else "(no open findings)"
        )

    # Reserve headroom for template boilerplate (~6–8 KiB).
    content_budget = max(1024, max_bytes - 8_192)

    commit_diff = ""
    if include_diff and sha:
        # Cap the initial fetch so the diff cannot monopolize the content
        # budget (leave room for task description + protected fields).
        diff_budget = max(
            _CRITICAL_DIFF_HEAD_BYTES,
            min(max_bytes // 2, content_budget // 2),
        )
        commit_diff = fetch_review_diff(
            sha,
            mode=mode,
            base_sha=base_sha,
            fixed_sha=fixed_sha,
            cwd=cwd,
            max_bytes=diff_budget,
        )

    fields = {
        "spec_content_concise": spec_summary,
        "current_task_description": task_desc,
        "acceptance_criteria": acceptance,
        "open_findings": open_findings,
        "commit_diff": commit_diff,
    }
    capped = apply_prompt_size_cap(fields, content_budget)

    evidence = data.get("check_evidence") if data else None
    bind_sha = sha or head_sha_fallback(cwd)
    reusable = False
    if evidence and bind_sha:
        reusable = is_check_evidence_reusable(
            evidence, bind_sha, tree_clean=None, cwd=cwd,
        )

    return {
        "review_mode": mode,
        "mode": mode,
        "spec_content": "",  # drop full long sections from review/fix context
        "spec_content_concise": capped["spec_content_concise"],
        "completed_tasks": "",
        "completed_tasks_concise": "",
        "future_tasks": "",
        "future_tasks_concise": "",
        "current_task_description": capped["current_task_description"],
        "acceptance_criteria": capped["acceptance_criteria"],
        "open_findings": capped["open_findings"],
        "commit_diff": capped["commit_diff"],
        "fix_base_commit_sha": base_sha,
        "fixed_commit_sha": fixed_sha if mode == "delta" else "",
        "has_major": has_major,
        "check_evidence_reusable": reusable,
        "prompt_max_bytes": max_bytes,
    }


def head_sha_fallback(cwd: Optional[str] = None) -> str:
    """Best-effort HEAD SHA for evidence binding (empty when unavailable)."""
    import review_helper

    return review_helper.get_head_sha(cwd=cwd)


def _build_task_context(spec_dir, verbose_items=20):
    """Extract task context from a spec directory.

    Reads spec.md and todo.json, computes completed/current/future task info.

    Args:
        spec_dir: Path to the spec directory.
        verbose_items: Max number of items to show with full details.
            Items beyond this limit are shown in brief format.

    Returns:
        Dict with keys: spec_content, completed_tasks, current_task_id,
        current_task_description, current_commit_title, resume_phase,
        skip_commit, future_tasks.
    """
    spec_path = spec_dir / "spec.md"
    if spec_path.exists():
        spec_content = spec_path.read_text(encoding="utf-8")
    else:
        spec_content = ""
    spec_content_concise = _trim_spec_content(spec_content)

    todo = load_todo(spec_dir)
    if todo:
        done = [item for item in todo if item.get("completed_at")]
        if len(done) <= verbose_items:
            completed_tasks = "\n\n".join(
                _format_item_verbose(item) for item in done
            )
        else:
            brief_items = done[:-verbose_items]
            verbose_part = done[-verbose_items:]
            parts = [_format_item_brief(item) for item in brief_items]
            parts.extend(_format_item_verbose(item) for item in verbose_part)
            completed_tasks = "\n\n".join(parts)
        completed_tasks_concise = "\n".join(
            _format_item_concise(item) for item in done
        )

        undone = [item for item in todo if not item.get("completed_at")]
        if undone:
            current = undone[0]
            task_id = current.get("id", "")
            current_task_id = task_id
            current_task_description = _format_item_verbose(current)
            current_commit_title = current.get("commit_title") or ""
            # commit_title set but completed_at empty → resume at review
            resume_phase = (
                "review" if current_commit_title.strip() else "implement"
            )
            skip_commit = normalize_skip_commit(current.get("skip_commit"))

            future = undone[1:]
            if future:
                if len(future) <= verbose_items:
                    future_tasks = "\n\n".join(
                        _format_item_verbose(item) for item in future
                    )
                else:
                    verbose_part = future[:verbose_items]
                    brief_items = future[verbose_items:]
                    parts = [
                        _format_item_verbose(item) for item in verbose_part
                    ]
                    parts.extend(
                        _format_item_brief(item) for item in brief_items
                    )
                    future_tasks = "\n\n".join(parts)
                future_tasks_concise = "\n".join(
                    _format_item_concise(item) for item in future
                )
            else:
                future_tasks = ""
                future_tasks_concise = ""
        else:
            current_task_id = ""
            current_task_description = ""
            current_commit_title = ""
            resume_phase = "implement"
            skip_commit = normalize_skip_commit(None)
            future_tasks = ""
            future_tasks_concise = ""
    else:
        completed_tasks = ""
        completed_tasks_concise = ""
        current_task_id = ""
        current_task_description = ""
        current_commit_title = ""
        resume_phase = "implement"
        skip_commit = normalize_skip_commit(None)
        future_tasks = ""
        future_tasks_concise = ""

    return {
        "spec_content": spec_content,
        "spec_content_concise": spec_content_concise,
        "completed_tasks": completed_tasks,
        "completed_tasks_concise": completed_tasks_concise,
        "current_task_id": current_task_id,
        "current_task_description": current_task_description,
        "current_commit_title": current_commit_title,
        "resume_phase": resume_phase,
        "skip_commit": skip_commit,
        "future_tasks": future_tasks,
        "future_tasks_concise": future_tasks_concise,
    }



def _build_metadata(template_name, spec_name=None):
    """Build the metadata dict for template rendering.

    Different template names may produce different metadata.
    """
    metadata = {}
    if spec_name:
        spec_dir = resolve_spec_dir(spec_name)
        metadata["spec_name"] = spec_dir.name
        meta = load_meta(spec_dir)
        if meta:
            metadata.update(meta.to_dict())
    if not metadata:
        ctx = get_project_context()
        metadata["workdir"] = str(ctx.top_workdir) if ctx.in_git_workdir() else ""
        metadata["remote_url"] = ctx.remote_url
        metadata["branch"] = ctx.branch
        metadata["user_name"] = ctx.user_name
        metadata["user_email"] = ctx.user_email
        if ctx.main_worktree:
            metadata["main_worktree"] = ctx.main_worktree
        metadata["created_at"] = local_iso_timestamp()
        metadata["name"] = ""

    if template_name in ("apply-commit", "apply-review", "apply-fix"):
        metadata["spex_root"] = ""
        workdir = metadata.get("workdir", "")
        if workdir:
            try:
                spex_root = get_spex_root()
                rel = os.path.relpath(spex_root, workdir)
                if not rel.startswith(".."):
                    metadata["spex_root"] = rel
            except (ValueError, RuntimeError):
                pass
        ctx = get_project_context()
        if (metadata.get("user_name") == ctx.user_name
                and metadata.get("user_email") == ctx.user_email):
            metadata["user_name"] = ""
            metadata["user_email"] = ""
    # All spec-based templates except spec-template need task context:
    # apply-commit, apply-one-task, apply-review, apply-fix,
    # modify-spec, modify-todo
    if template_name != "spec-template" and spec_name:
        metadata.update(_build_task_context(spec_dir))

    metadata["spex_skill_dir"] = str(Path(__file__).resolve().parent.parent)
    return metadata


def _enrich_review_metadata(
    metadata, spec_name, commit_sha=None, finding_id=None, mode=None,
):
    """Add review-loop fields from review-step-N.json and CLI args.

    Builds a compact full/delta context: current task, acceptance criteria,
    relevant spec summary, open finding batch, and required diff. Excludes
    completed/future task bodies and completed finding details.
    """
    import review_helper

    metadata["spex_skill_dir"] = str(Path(__file__).resolve().parent.parent)
    step_id = metadata.get("current_task_id") or ""
    metadata["step_id"] = step_id
    metadata["finding_id"] = finding_id or ""
    review_mode = normalize_review_mode(mode)
    metadata["skip_delta"] = False

    review_data = None
    path = None
    if step_id and spec_name:
        path = review_helper.resolve_review_path(spec_name, step_id)
        metadata["review_file"] = str(path)
        if path.is_file():
            review_data = review_helper.load_review(path)
            # Prefer explicit CLI mode; else file mode; else full.
            if mode is None:
                review_mode = normalize_review_mode(review_data.get("mode"))
            metadata["review_round"] = int(review_data.get("round", 1))
            metadata["commit_sha"] = (
                commit_sha or review_data.get("commit_sha") or ""
            )
            if finding_id:
                item = review_helper.get_finding_by_id(review_data, finding_id)
                if item is None:
                    logger.error(
                        "Error: finding id '%s' not found in %s",
                        finding_id, path.name,
                    )
                    sys.exit(1)
                if item.get("completed_at"):
                    logger.error(
                        "Error: finding id '%s' is already completed",
                        finding_id,
                    )
                    sys.exit(1)
                metadata["finding_id"] = finding_id
        else:
            metadata["review_round"] = 1
            metadata["commit_sha"] = commit_sha or ""
    else:
        metadata.setdefault("commit_sha", commit_sha or "")
        metadata.setdefault("review_round", 1)
        metadata.setdefault("review_file", "")

    if commit_sha:
        metadata["commit_sha"] = commit_sha

    metadata["review_mode"] = review_mode
    metadata["mode"] = review_mode

    if review_mode == "delta" and not should_render_delta_prompt(review_data):
        metadata["skip_delta"] = True
        metadata["open_findings"] = "(delta review skipped: minor-only batch)"
        metadata["has_major"] = False
        metadata["check_evidence_reusable"] = False
        metadata["commit_diff"] = ""
        metadata["acceptance_criteria"] = extract_acceptance_criteria(
            metadata.get("current_task_description") or "",
        )
        # Still drop bulky context so callers never see full payloads.
        metadata["spec_content"] = ""
        metadata["completed_tasks"] = ""
        metadata["completed_tasks_concise"] = ""
        metadata["future_tasks"] = ""
        metadata["future_tasks_concise"] = ""
        return metadata

    compact = build_compact_review_context(
        metadata,
        mode=review_mode,
        review_data=review_data,
        finding_id=finding_id or "",
        commit_sha=metadata.get("commit_sha") or "",
    )
    metadata.update(compact)
    return metadata


def render_prompt(name, spec_name=None, extra_vars=None, metadata=None):
    """Render a template by name and return the result string.

    Args:
        name: Template name without .md extension (e.g. "spec-template").
        spec_name: Optional spec name for spec-specific metadata.
        extra_vars: Optional dict of additional variables to merge into metadata.
        metadata: Optional pre-built metadata dict. Skips _build_metadata when provided.

    Returns:
        Rendered template content with front-matter stripped.
    """
    from jinja2 import Template

    content = get_template(name + ".md")
    if metadata is None:
        metadata = _build_metadata(name, spec_name)
        if extra_vars:
            metadata.update(extra_vars)

    # All-done detection for task-based templates.
    # apply-one-task / apply-commit: empty description means no current task.
    # apply-review / apply-fix: do NOT reuse the empty-description gate after
    # compact enrichment / size capping (description may be truncated). Gate
    # on pre-enrich task id instead.
    if name in ("apply-one-task", "apply-commit") and not metadata.get(
        "current_task_description",
    ):
        return ""
    if name in ("apply-review", "apply-fix") and not (
        metadata.get("current_task_id") or metadata.get("step_id")
    ):
        return ""

    validate_required_meta(content, metadata)
    rendered = Template(content).render(**metadata)
    return strip_front_matter(rendered)


def _output_rendered(rendered, output_path):
    """Write rendered content to file or stdout."""
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


def _build_parser():
    """Build the top-level parser with subcommand sub-parsers."""
    parser = ArgumentParser(
        prog="spex prompt",
        description="Render Jinja2 templates with metadata.",
    )
    subs = parser.add_subparsers(dest="subcmd", title="Subcommands")

    # apply-one-task
    p = subs.add_parser(
        "apply-one-task",
        description="Render apply-one-task template with spec metadata.",
        help="Render prompt for the next undone task",
    )
    p.add_argument(
        "--name", required=True, help="Spec name (required)",
    )
    p.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Output JSON with task_id and prompt",
    )
    p.add_argument(
        "-o", "--output", help="Output file path (default: stdout)",
    )

    # apply-commit
    p = subs.add_parser(
        "apply-commit",
        description="Render apply-commit template with spec metadata.",
        help="Render commit instructions for the current task",
    )
    p.add_argument("--name", help="Spec name")
    p.add_argument(
        "--stdin", action="store_true", dest="stdin_flag",
        help="Read raw text from stdin as prompt_context",
    )
    p.add_argument(
        "-o", "--output", help="Output file path (default: stdout)",
    )

    # apply-review
    p = subs.add_parser(
        "apply-review",
        description="Render apply-review template with spec metadata.",
        help="Render review instructions for the current task commit",
    )
    p.add_argument("--name", required=True, help="Spec name (required)")
    p.add_argument(
        "--commit", dest="commit_sha", default=None,
        help="Commit SHA under review (default: from review file)",
    )
    p.add_argument(
        "--mode", dest="mode", default=None, choices=list(VALID_REVIEW_MODES),
        help="Review mode: full (default) or delta (post-fix majors only)",
    )
    p.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Output JSON with prompt and review metadata",
    )
    p.add_argument(
        "-o", "--output", help="Output file path (default: stdout)",
    )

    # apply-fix
    p = subs.add_parser(
        "apply-fix",
        description=(
            "Render apply-fix template for a single open finding."
        ),
        help="Render fix instructions for one review finding",
    )
    p.add_argument("--name", required=True, help="Spec name (required)")
    p.add_argument(
        "--finding-id", required=True, dest="finding_id",
        help="Single open finding id to fix (required)",
    )
    p.add_argument(
        "--commit", dest="commit_sha", default=None,
        help="Commit SHA under fix (default: from review file)",
    )
    p.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Output JSON with prompt and review metadata",
    )
    p.add_argument(
        "-o", "--output", help="Output file path (default: stdout)",
    )

    # modify-spec
    p = subs.add_parser(
        "modify-spec",
        description="Render modify-spec template with spec metadata.",
        help="Render prompt for modifying a spec",
    )
    p.add_argument(
        "--name", required=True, help="Spec name (required)",
    )
    p.add_argument(
        "--stdin", action="store_true", dest="stdin_flag",
        help="Read raw text from stdin as prompt_context",
    )
    p.add_argument(
        "--remove-undone", action="store_true", dest="remove_undone",
        help="Remove undone tasks from todo.json before rendering",
    )
    p.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Output JSON with rendered prompt",
    )
    p.add_argument(
        "-o", "--output", help="Output file path (default: stdout)",
    )

    # modify-todo
    p = subs.add_parser(
        "modify-todo",
        description="Render modify-todo template with spec metadata.",
        help="Render prompt for modifying a todo list",
    )
    p.add_argument(
        "--name", required=True, help="Spec name (required)",
    )
    p.add_argument(
        "--stdin", action="store_true", dest="stdin_flag",
        help="Read raw text from stdin as prompt_context",
    )
    p.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Output JSON with rendered prompt",
    )
    p.add_argument(
        "-o", "--output", help="Output file path (default: stdout)",
    )

    return parser


# Known subcommands for routing (fallback to cli_render for others)
_KNOWN_SUBCMDS = {
    "apply-one-task", "apply-commit", "apply-review", "apply-fix",
    "modify-spec", "modify-todo",
}


def _do_apply_one_task(args):
    """Handle apply-one-task subcommand."""
    import json

    from jinja2 import TemplateError

    try:
        metadata = _build_metadata("apply-one-task", args.name)

        # Handle all-done in JSON mode
        if args.json_mode and not metadata.get("current_task_description"):
            print(json.dumps({
                "task_id": "",
                "prompt": "",
                "all_done": True,
                "resume_phase": "",
                "commit_title": "",
                "skip_commit": "",
            }))
            sys.exit(0)

        # Handle all-done in non-JSON mode: exit(0) with empty stdout
        if not args.json_mode and not metadata.get("current_task_description"):
            sys.exit(0)

        # Emit task_id to stderr for orchestrator to capture (non-JSON only)
        if not args.json_mode:
            current_task_id = metadata.get("current_task_id", "")
            if current_task_id:
                print(f"task_id={current_task_id}", file=sys.stderr)

        rendered = render_prompt("apply-one-task", args.name, metadata=metadata)
    except FileNotFoundError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except TemplateError as e:
        logger.error("Error rendering template: %s", e)
        sys.exit(1)

    task_id = metadata.get("current_task_id", "")
    if task_id and args.name:
        from debug_log import emit_apply_anchor

        emit_apply_anchor(
            resolve_spec_dir(args.name),
            f"===== APPLY task begin id={task_id} =====",
        )

    if args.json_mode:
        print(json.dumps({
            "task_id": metadata.get("current_task_id", ""),
            "prompt": rendered,
            "resume_phase": metadata.get("resume_phase", "implement"),
            "commit_title": metadata.get("current_commit_title", ""),
            "skip_commit": metadata.get("skip_commit", "false"),
        }))
    else:
        _output_rendered(rendered, args.output)


def cli_apply_one_task(argv=None):
    """CLI handler for apply-one-task subcommand."""
    args = _build_parser().parse(["apply-one-task"] + (argv or []))
    _do_apply_one_task(args)


def _read_stdin_extra_vars(stdin_flag):
    """Read extra variables from stdin (JSON or raw text with --stdin flag)."""
    import json

    if sys.stdin.isatty():
        return None
    stdin_data = sys.stdin.read().strip()
    if not stdin_data:
        return None
    if stdin_flag:
        return {"prompt_context": stdin_data}
    try:
        return json.loads(stdin_data)
    except json.JSONDecodeError:
        logger.error("Error: stdin must be valid JSON")
        sys.exit(1)


def _do_apply_commit(args):
    """Handle apply-commit subcommand."""
    from jinja2 import TemplateError

    extra_vars = _read_stdin_extra_vars(args.stdin_flag)

    try:
        metadata = _build_metadata("apply-commit", args.name)
        if extra_vars:
            metadata.update(extra_vars)

        # Handle all-done: exit(0) with empty stdout
        if not metadata.get("current_task_description"):
            sys.exit(0)

        rendered = render_prompt("apply-commit", args.name, metadata=metadata)
    except FileNotFoundError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except TemplateError as e:
        logger.error("Error rendering template: %s", e)
        sys.exit(1)

    _output_rendered(rendered, args.output)


def cli_apply_commit(argv=None):
    """CLI handler for apply-commit subcommand."""
    args = _build_parser().parse(["apply-commit"] + (argv or []))
    _do_apply_commit(args)


def _do_apply_review(args):
    """Handle apply-review subcommand."""
    import json

    from jinja2 import TemplateError

    if get_project_context().config.get("step_review") is False:
        payload = {
            "prompt": "",
            "skipped": True,
            "step_review": False,
            "task_id": "",
            "commit_sha": args.commit_sha or "",
            "review_round": 1,
            "review_file": "",
            "mode": normalize_review_mode(getattr(args, "mode", None)),
            "prompt_bytes": 0,
        }
        metadata = _build_metadata("apply-review", args.name)
        payload["task_id"] = metadata.get("current_task_id") or ""
        print(json.dumps(payload))
        sys.exit(0)

    try:
        metadata = _build_metadata("apply-review", args.name)
        # Gate all-done on pre-enrich task presence (id or description).
        # After enrichment, size capping may truncate current_task_description
        # — do not re-check description alone for all-done.
        if not (
            metadata.get("current_task_id")
            or metadata.get("current_task_description")
        ):
            if args.json_mode:
                print(json.dumps({
                    "prompt": "", "all_done": True,
                }))
            sys.exit(0)

        _enrich_review_metadata(
            metadata, args.name,
            commit_sha=args.commit_sha,
            mode=getattr(args, "mode", None),
        )
        if metadata.get("skip_delta"):
            payload = {
                "prompt": "",
                "skipped": True,
                "reason": "minor_only",
                "mode": "delta",
                "task_id": metadata.get("step_id", ""),
                "commit_sha": metadata.get("commit_sha", ""),
                "review_round": metadata.get("review_round", 1),
                "review_file": metadata.get("review_file", ""),
                "has_major": False,
                "prompt_bytes": 0,
            }
            print(json.dumps(payload))
            sys.exit(0)

        if not metadata.get("commit_sha"):
            logger.error(
                "Error: --commit is required when no review file exists",
            )
            sys.exit(1)

        rendered = render_prompt(
            "apply-review", args.name, metadata=metadata,
        )
    except FileNotFoundError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except TemplateError as e:
        logger.error("Error rendering template: %s", e)
        sys.exit(1)

    prompt_bytes = measure_prompt_bytes(rendered)
    max_bytes = int(
        metadata.get("prompt_max_bytes") or DEFAULT_REVIEW_PROMPT_MAX_BYTES
    )
    if prompt_bytes > max_bytes:
        # Shrink variable context and re-render once to enforce the hard cap.
        overhead = prompt_bytes - (
            measure_prompt_bytes(metadata.get("spec_content_concise", ""))
            + measure_prompt_bytes(metadata.get("current_task_description", ""))
            + measure_prompt_bytes(metadata.get("commit_diff", ""))
            + measure_prompt_bytes(metadata.get("open_findings", ""))
            + measure_prompt_bytes(metadata.get("acceptance_criteria", ""))
        )
        content_budget = max(512, max_bytes - max(overhead, 0))
        capped = apply_prompt_size_cap(
            {
                "spec_content_concise": metadata.get("spec_content_concise", ""),
                "current_task_description": metadata.get(
                    "current_task_description", "",
                ),
                "acceptance_criteria": metadata.get("acceptance_criteria", ""),
                "open_findings": metadata.get("open_findings", ""),
                "commit_diff": metadata.get("commit_diff", ""),
            },
            content_budget,
        )
        metadata.update(capped)
        rendered = render_prompt(
            "apply-review", args.name, metadata=metadata,
        )
        prompt_bytes = measure_prompt_bytes(rendered)

    if args.name:
        from debug_log import emit_apply_anchor

        emit_apply_anchor(
            resolve_spec_dir(args.name),
            "===== APPLY review begin "
            f"round={metadata.get('review_round', 1)} "
            f"mode={metadata.get('mode', 'full')} "
            f"commit={metadata.get('commit_sha', '')} "
            f"prompt_bytes={prompt_bytes} =====",
        )

    if args.json_mode:
        print(json.dumps({
            "prompt": rendered,
            "task_id": metadata.get("step_id", ""),
            "commit_sha": metadata.get("commit_sha", ""),
            "review_round": metadata.get("review_round", 1),
            "review_file": metadata.get("review_file", ""),
            "mode": metadata.get("mode", "full"),
            "has_major": bool(metadata.get("has_major")),
            "fix_base_commit_sha": metadata.get("fix_base_commit_sha", ""),
            "fixed_commit_sha": metadata.get("fixed_commit_sha", ""),
            "check_evidence_reusable": bool(
                metadata.get("check_evidence_reusable")
            ),
            "prompt_bytes": prompt_bytes,
            "acceptance_criteria": metadata.get("acceptance_criteria", ""),
        }))
    else:
        _output_rendered(rendered, args.output)


def cli_apply_review(argv=None):
    """CLI handler for apply-review subcommand."""
    args = _build_parser().parse(["apply-review"] + (argv or []))
    _do_apply_review(args)


def _do_apply_fix(args):
    """Handle apply-fix subcommand."""
    import json

    from jinja2 import TemplateError

    try:
        metadata = _build_metadata("apply-fix", args.name)
        # Gate all-done on pre-enrich task presence (id or description).
        # After enrichment, size capping may truncate current_task_description
        # — do not re-check description alone for all-done.
        if not (
            metadata.get("current_task_id")
            or metadata.get("current_task_description")
        ):
            if args.json_mode:
                print(json.dumps({
                    "prompt": "", "all_done": True,
                }))
            sys.exit(0)

        _enrich_review_metadata(
            metadata, args.name,
            commit_sha=args.commit_sha,
            finding_id=args.finding_id,
            mode="full",  # fix prompts are not delta reviews
        )
        if not metadata.get("commit_sha"):
            logger.error(
                "Error: --commit is required when no review file exists",
            )
            sys.exit(1)

        rendered = render_prompt(
            "apply-fix", args.name, metadata=metadata,
        )
    except FileNotFoundError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except TemplateError as e:
        logger.error("Error rendering template: %s", e)
        sys.exit(1)

    prompt_bytes = measure_prompt_bytes(rendered)
    if args.json_mode:
        print(json.dumps({
            "prompt": rendered,
            "task_id": metadata.get("step_id", ""),
            "finding_id": metadata.get("finding_id", ""),
            "commit_sha": metadata.get("commit_sha", ""),
            "review_round": metadata.get("review_round", 1),
            "review_file": metadata.get("review_file", ""),
            "mode": metadata.get("mode", "full"),
            "check_evidence_reusable": bool(
                metadata.get("check_evidence_reusable")
            ),
            "prompt_bytes": prompt_bytes,
            "acceptance_criteria": metadata.get("acceptance_criteria", ""),
        }))
    else:
        _output_rendered(rendered, args.output)


def cli_apply_fix(argv=None):
    """CLI handler for apply-fix subcommand."""
    args = _build_parser().parse(["apply-fix"] + (argv or []))
    _do_apply_fix(args)


def _do_modify_spec(args):
    """Handle modify-spec subcommand."""
    import json

    from jinja2 import TemplateError

    extra_vars = _read_stdin_extra_vars(args.stdin_flag)

    try:
        # Side-effect: remove undone tasks from todo.json before building metadata
        if args.remove_undone:
            spec_dir = resolve_spec_dir(args.name)
            todo_path = spec_dir / "todo.json"
            if todo_path.exists():
                try:
                    data = json.loads(todo_path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        completed = _filter_completed_todos(data)
                        atomic_write_json(todo_path, completed)
                except json.JSONDecodeError:
                    pass  # Silently skip if JSON is invalid

        metadata = _build_metadata("modify-spec", args.name)
        if extra_vars:
            metadata.update(extra_vars)

        rendered = render_prompt("modify-spec", args.name, metadata=metadata)
    except FileNotFoundError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except TemplateError as e:
        logger.error("Error rendering template: %s", e)
        sys.exit(1)

    if args.json_mode:
        print(json.dumps({"prompt": rendered}))
    else:
        _output_rendered(rendered, args.output)


def cli_modify_spec(argv=None):
    """CLI handler for modify-spec subcommand."""
    args = _build_parser().parse(["modify-spec"] + (argv or []))
    _do_modify_spec(args)


def _do_modify_todo(args):
    """Handle modify-todo subcommand."""
    import json

    from jinja2 import TemplateError

    extra_vars = _read_stdin_extra_vars(args.stdin_flag)

    try:
        metadata = _build_metadata("modify-todo", args.name)
        if extra_vars:
            metadata.update(extra_vars)

        # Side-effect: clean undone todos from todo.json
        spec_dir = resolve_spec_dir(args.name)
        todo_path = spec_dir / "todo.json"
        if todo_path.exists():
            try:
                data = json.loads(todo_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    completed = _filter_completed_todos(data)
                    atomic_write_json(todo_path, completed)
            except json.JSONDecodeError:
                pass  # Silently skip if JSON is invalid

        rendered = render_prompt("modify-todo", args.name, metadata=metadata)
    except FileNotFoundError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except TemplateError as e:
        logger.error("Error rendering template: %s", e)
        sys.exit(1)

    if args.json_mode:
        print(json.dumps({"prompt": rendered}))
    else:
        _output_rendered(rendered, args.output)


def cli_modify_todo(argv=None):
    """CLI handler for modify-todo subcommand."""
    args = _build_parser().parse(["modify-todo"] + (argv or []))
    _do_modify_todo(args)


def cli_render(argv):
    """Fallback CLI handler for generic template rendering."""
    from jinja2 import TemplateError

    parser = ArgumentParser(
        prog="spex prompt",
        description="Render a Jinja2 template with metadata.",
    )
    parser.add_argument("name", help="Template name (without .md extension)")
    parser.add_argument("--name", help="Spec name for spec-specific metadata")
    parser.add_argument("--stdin", action="store_true", dest="stdin_flag",
                        help="Read raw text from stdin as prompt_context")
    parser.add_argument("-o", "--output",
                        help="Output file path (default: stdout)")
    args = parser.parse(argv)

    extra_vars = _read_stdin_extra_vars(args.stdin_flag)

    try:
        metadata = _build_metadata(args.name, args.name)
        if extra_vars:
            metadata.update(extra_vars)

        rendered = render_prompt(args.name, args.name, metadata=metadata)
    except FileNotFoundError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    except TemplateError as e:
        logger.error("Error rendering template: %s", e)
        sys.exit(1)

    _output_rendered(rendered, args.output)


def _normalize_subcmd(name):
    """Normalize subcommand/template name: underscores -> hyphens."""
    return name.replace("_", "-")


def main(argv=None):
    """Route prompt subcommands to their handlers."""
    if argv is None:
        argv = sys.argv[1:]

    parser = _build_parser()

    if not argv:
        parser.print_help(sys.stderr)
        sys.exit(2)

    first = argv[0]

    # Let argparse handle flags like --help / -h
    if first.startswith("-"):
        parser.parse(argv)
        return

    # Normalize: accept both underscores and hyphens
    subcmd = _normalize_subcmd(first)

    if subcmd not in _KNOWN_SUBCMDS:
        # Fallback to generic template rendering
        cli_render(argv)
        return

    # Ensure normalized name is used for argparse
    argv = [subcmd] + list(argv[1:])
    args = parser.parse(argv)

    if args.subcmd == "apply-one-task":
        _do_apply_one_task(args)
    elif args.subcmd == "apply-commit":
        _do_apply_commit(args)
    elif args.subcmd == "apply-review":
        _do_apply_review(args)
    elif args.subcmd == "apply-fix":
        _do_apply_fix(args)
    elif args.subcmd == "modify-spec":
        _do_modify_spec(args)
    elif args.subcmd == "modify-todo":
        _do_modify_todo(args)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
