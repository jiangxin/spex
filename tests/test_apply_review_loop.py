"""Apply-review-loop SOP consistency tests (batch + delta state machine)."""

from __future__ import annotations

import re
from pathlib import Path

import review_helper

REPO_ROOT = Path(__file__).resolve().parent.parent
APPLY_REVIEW_LOOP = (
    REPO_ROOT / "skills" / "spex" / "references" / "apply-review-loop.md"
)


def _read() -> str:
    return APPLY_REVIEW_LOOP.read_text(encoding="utf-8")


def _h2(text: str, title: str) -> str:
    """Return the ## section body for title (exclusive of next ##)."""
    pattern = rf"(?m)^## {re.escape(title)}\s*\n"
    match = re.search(pattern, text)
    assert match, f"## {title} not found"
    start = match.end()
    nxt = re.search(r"(?m)^## ", text[start:])
    end = start + nxt.start() if nxt else len(text)
    return text[start:end]


def test_cap_numbers_match_max_review_round():
    """Every review-round cap literal in the SOP equals the code constant."""
    text = _read()
    caps = [
        int(m.group(1))
        for m in re.finditer(r"max review round \(currently (\d+)\)", text)
    ]
    assert caps, "expected at least one 'max review round (currently N)' literal"
    assert all(c == review_helper.MAX_REVIEW_ROUND for c in caps), (
        f"cap numbers {caps} do not all equal "
        f"MAX_REVIEW_ROUND={review_helper.MAX_REVIEW_ROUND}"
    )


def test_commit_sha_heal_checks_todo_commit_title():
    """6-entry commit_sha healing must compare HEAD with todo commit_title."""
    text = _read()
    match = re.search(
        r"If status JSON `\"commit_sha\"` is non-empty \*\*but differs\*\*.*?"
        r"abnormal STOP for the user to resolve\.",
        text,
        re.DOTALL,
    )
    assert match, "6-entry commit_sha heal branch not found"
    branch = match.group(0)
    assert "commit_title" in branch, "heal branch must reference commit_title"
    assert "todo.json" in branch, "heal branch must reference todo.json"
    assert "abnormal STOP" in branch, "heal branch must STOP on mismatch"


def test_route_table_covers_severity_and_resume():
    """Documented route table must cover every severity mix + resume state."""
    text = _read()
    overview = _h2(text, "Flow Overview")
    required = [
        "Full review, 0 open findings",
        "Full review, minor-only open",
        "Full review, any major open",
        "Delta, no new major",
        "Delta, new major, round < max",
        "Delta, new major, round = max",
        "Resume `needs_fix`",
        "Resume `awaiting_delta`",
        "`step_review=false`, open major",
        "`step_review=false`, no open major",
    ]
    for needle in required:
        assert needle in overview, f"missing route row: {needle}"
    # Hard-cap must not re-enter delta via mermaid fix→routeD→delta.
    assert "fixCap" in overview or "hard-cap" in overview.lower()
    assert "round ge max| fixCap" in overview or (
        "round ge max| fixCap" in overview.replace(" ", "")
    ) or "fixCap --> phase7" in overview


def test_minor_only_cannot_enter_another_review_round():
    """Minor-only batch fix must go to Phase 7 with no delta and no Round 2."""
    text = _read()
    six_d = _h2(text, "6d. Route after batch fix")
    assert "awaiting_delta" in six_d
    assert "Phase 7" in six_d
    assert "render or launch delta review" in six_d
    assert "bump-round" in six_d
    assert "start another full review round" in six_d
    assert "pending_has_major" in six_d  # must warn not to re-read cleared flag

    six_b = _h2(text, "6b. Route after a full review pass")
    assert "must **not** enter delta review" in six_b
    assert "must **not**\nbump into another full round" in six_b or (
        "must **not** bump into another full round" in six_b
    )


def test_major_batch_requires_delta_then_cap_aware_next_full():
    """Major batches route through delta; new major respects full-round cap."""
    text = _read()
    six_d = _h2(text, "6d. Route after batch fix")
    assert "$awaiting_delta` is true" in six_d
    assert "**6e**" in six_d
    assert "pending_has_major" in six_d

    six_f = _h2(text, "6f. Route after delta / full-round cap")
    assert "bump-round" in six_f
    assert "**6a**" in six_f
    assert "do not bump" in six_f.lower() or "**do not bump**" in six_f
    assert "fourth full review" in six_f.lower()
    assert "**6c**" in six_f
    assert "without** **6e**" in six_f or "without **6e**" in six_f


def test_resume_awaiting_delta_routes_to_6e():
    """After major complete-batch, resume must enter 6e via awaiting_delta."""
    text = _read()
    entry = _h2(text, "6-entry. Resume / continue gate")
    assert "awaiting_delta" in entry
    assert "**6e**" in entry
    assert "Do **not** start **6a**" in entry or "do **not** start **6a**" in entry

    six_e = _h2(text, "6e. Delta review sub-agent")
    assert "minor_only" in six_e
    assert "abnormal STOP" in six_e
    assert "major batch" in six_e.lower() or "$awaiting_delta" in six_e


def test_round_one_always_full_review():
    """Round 1 / 6a must always perform full review mode."""
    text = _read()
    entry = _h2(text, "6-entry. Resume / continue gate")
    assert "$review_mode=full" in entry
    assert "Round 1 always performs full review" in entry

    six_a = _h2(text, "6a. Full review sub-agent")
    assert "--mode full" in six_a
    assert "Always launch **full** mode" in six_a
    assert "Delta mode\nis only for **6e**" in six_a or (
        "Delta mode is only for **6e**" in six_a
    )


def test_cache_check_before_prompt_render():
    """Cache checks must appear before prompt-render commands."""
    text = _read()
    for title, cmd in (
        ("6a. Full review sub-agent", "prompt apply-review"),
        ("6c-ii. Fix + amend one batch", "prompt apply-fix"),
        ("6e. Delta review sub-agent", "prompt apply-review"),
    ):
        section = (
            _h2(text, title)
            if title.startswith("6a") or title.startswith("6e")
            else _h3(text, title)
        )
        cache_at = section.lower().find("cache first")
        assert cache_at >= 0, f"{title}: missing 'cache first'"
        # First "reuse" / "do **not** run" guidance before the CMD fence
        reuse_at = section.find("do **not** run")
        cmd_at = section.find(f"```bash\n$spex_skill_dir/scripts/spex {cmd}")
        assert reuse_at >= 0, f"{title}: missing reuse / do-not-run"
        assert cmd_at >= 0, f"{title}: missing {cmd} CMD"
        assert cache_at < cmd_at, f"{title}: cache check must precede CMD"
        assert reuse_at < cmd_at, f"{title}: reuse gate must precede CMD"


def _h3(text: str, title: str) -> str:
    pattern = rf"(?m)^### {re.escape(title)}\s*\n"
    match = re.search(pattern, text)
    assert match, f"### {title} not found"
    start = match.end()
    nxt = re.search(r"(?m)^### |^## ", text[start:])
    end = start + nxt.start() if nxt else len(text)
    return text[start:end]


def test_batch_fix_uses_complete_batch_not_per_finding_edit():
    """Finding completion must be atomic complete-batch after amend."""
    text = _read()
    six_c = _h2(text, "6c. Batch fix — one sub-agent, one amend")
    assert "complete-batch" in six_c
    assert "mark findings complete inside the sub-agent" in six_c
    six_c_ii = _h3(text, "6c-ii. Fix + amend one batch")
    assert "completed_at" in six_c_ii
    assert "via `edit`" in six_c_ii
    assert "one amend" in six_c.lower()


def test_delta_does_not_increment_full_round():
    """Delta review must not increment the full-review round counter."""
    text = _read()
    invariants = _h2(text, "Invariants (do not weaken)")
    assert "delta review does **not** increment `round`" in invariants
    six_e = _h2(text, "6e. Delta review sub-agent")
    assert "does **not** increment `round`" in six_e
    assert "--mode delta" in six_e
