"""Apply-review-loop SOP consistency tests (R4-F18 / R4-F22)."""

from __future__ import annotations

import re
from pathlib import Path

import review_helper

REPO_ROOT = Path(__file__).resolve().parent.parent
APPLY_REVIEW_LOOP = (
    REPO_ROOT / "skills" / "spex" / "references" / "apply-review-loop.md"
)


def test_cap_numbers_match_max_review_round():
    """Every review-round cap literal in the SOP equals the code constant."""
    text = APPLY_REVIEW_LOOP.read_text(encoding="utf-8")
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
    text = APPLY_REVIEW_LOOP.read_text(encoding="utf-8")
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
