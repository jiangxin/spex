"""Regression tests for SKILL.md W007 credential-routing language."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "spex" / "SKILL.md"
COMPACT_SOP = REPO_ROOT / "skills" / "spex" / "references" / "compact-sop-style.md"
CREATE_MD = REPO_ROOT / "skills" / "spex" / "commands" / "create.md"
MODIFY_MD = REPO_ROOT / "skills" / "spex" / "commands" / "modify.md"
APPLY_MD = REPO_ROOT / "skills" / "spex" / "commands" / "apply.md"
APPLY_ONE_STEP_MD = REPO_ROOT / "skills" / "spex" / "commands" / "apply-one-step.md"
APPLY_REVIEW_LOOP = (
    REPO_ROOT / "skills" / "spex" / "references" / "apply-review-loop.md"
)
README_MD = REPO_ROOT / "README.md"
README_ZH = REPO_ROOT / "README.zh.md"

FORBIDDEN_PHRASES = ("verbatim", "forward user text", "as-is", "in full")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _skill_body() -> str:
    """SKILL.md body with YAML front-matter stripped if present."""
    text = _read(SKILL_MD)
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :]
    return text


def _h2_section(text: str, title: str) -> str:
    """Return a ## section (heading included) until the next ## heading."""
    marker = f"## {title}"
    start = text.find(marker)
    assert start != -1, f"missing ## {title}"
    nxt = text.find("\n## ", start + 1)
    return text[start:] if nxt == -1 else text[start:nxt]


def _h3_section(text: str, title: str) -> str:
    """Return a ### section (heading included) until the next ### heading."""
    marker = f"### {title}"
    start = text.find(marker)
    assert start != -1, f"missing ### {title}"
    nxt = text.find("\n### ", start + 1)
    return text[start:] if nxt == -1 else text[start:nxt]


def _index(text: str, needle: str) -> int:
    idx = text.lower().find(needle.lower())
    assert idx != -1, f"missing {needle!r}"
    return idx


class TestSkillCredentialSafety:
    def test_has_credential_safety_section(self):
        body = _skill_body()
        assert "### Credential Safety" in body

    def test_redact_before_assigning_prompt(self):
        body = _skill_body()
        assert "Redact secrets in user text BEFORE assigning `$prompt`" in body
        assert "redact" in body.lower()

    def test_prompt_assignment_lines_require_redact(self):
        body = _skill_body()
        assignment_lines = [
            line for line in body.splitlines() if "$prompt" in line
        ]
        assert assignment_lines, "expected $prompt assignment lines in SKILL.md"
        for line in assignment_lines:
            assert "redact" in line.lower(), (
                f"$prompt assignment must mention redact: {line!r}"
            )
        joined = "\n".join(assignment_lines)
        assert "pass redacted user text as `$prompt`" in joined
        assert "Redact secrets in user text => `$prompt`" in joined
        assert "redacted free-form text => `$prompt`" in joined


class TestForbiddenForwardingLanguage:
    def test_skill_md_forbids_verbatim_forwarding(self):
        text = _read(SKILL_MD).lower()
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in text, f"SKILL.md must not contain {phrase!r}"

    def test_compact_sop_forbids_verbatim_forwarding(self):
        text = _read(COMPACT_SOP).lower()
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in text, (
                f"compact-sop-style.md must not contain {phrase!r}"
            )


class TestCompactSopRouterSkeleton:
    def test_mentions_redact(self):
        text = _read(COMPACT_SOP)
        assert "redact" in text.lower()
        assert "route with redacted `$prompt`" in text


class TestCommandPersistRedact:
    def test_create_redacts_requirement_before_prepare_spec(self):
        text = _read(CREATE_MD)
        phase2 = _h3_section(text, "Phase 2: Clarify Requirement")
        _index(phase2, "redact secrets in `$requirement`")
        redact_at = _index(text, "redact secrets in `$requirement`")
        persist_at = _index(text, "create-helper prepare-spec")
        assert redact_at < persist_at, (
            "create.md must redact $requirement before prepare-spec persist"
        )

    def test_modify_redacts_request_in_phase_3_before_meta_helper(self):
        phase3 = _h3_section(_read(MODIFY_MD), "Phase 3: Save Request")
        redact_at = _index(phase3, "redact secrets in `$request`")
        helper_at = _index(phase3, "meta-helper")
        assert redact_at < helper_at, (
            "modify.md Phase 3 must redact $request before meta-helper persist"
        )
        first_bullet = next(
            (line for line in phase3.splitlines() if line.startswith("- ")),
            "",
        )
        assert "redact secrets in `$request`" in first_bullet.lower(), (
            "redact $request must be the first Phase 3 instruction "
            "(runs when clarification is skipped)"
        )


SOP_STEP_REVIEW_PATHS = (
    APPLY_REVIEW_LOOP,
    APPLY_MD,
    APPLY_ONE_STEP_MD,
    README_MD,
    README_ZH,
)


class TestApplyStepReviewSop:
    def test_6a_skipped_continues_to_phase_7(self):
        section = _h2_section(_read(APPLY_REVIEW_LOOP), "6a. Review sub-agent")
        skipped_at = _index(section, '"skipped": true')
        no_launch_at = _index(section, "do **not** launch a review sub-agent")
        phase7_at = _index(section, "proceed to Phase 7")
        assert skipped_at < no_launch_at < phase7_at
        assert "loop STOP" in section
        assert "not" in section.lower()

    def test_6_entry_step_review_false_skips_6c(self):
        section = _h2_section(
            _read(APPLY_REVIEW_LOOP), "6-entry. Resume / continue gate"
        )
        _index(section, "`step_review` is false")
        _index(section, "do **not** enter **6c**")
        _index(section, "to Phase 7")
        _index(section, '"skipped": true')

    def test_loop_stop_is_abnormal_only(self):
        text = _read(APPLY_REVIEW_LOOP)
        round_model = _h2_section(text, "Round Model")
        _index(round_model, "STOP** is only for abnormal failures")
        _index(round_model, '"skipped": true')
        _index(round_model, "is **not** a STOP")
        _index(round_model, "proceed to Phase 7")

    def test_apply_commands_exclude_step_review_false_from_stop(self):
        for path in (APPLY_MD, APPLY_ONE_STEP_MD):
            phase6 = _h3_section(_read(path), "Phase 6: Review Loop")
            _index(phase6, "Load and follow `references/apply-review-loop.md`")
            _index(phase6, "abnormal failure")
            _index(phase6, "`step_review=false` is **not** an abnormal STOP")
            _index(phase6, '"skipped": true')
            _index(phase6, "the loop continues to")
            _index(phase6, "Phase 7")
            assert "config get" not in phase6.lower()
            assert "skip_review" not in phase6

    def test_docs_name_step_review_not_skip_review(self):
        for path in SOP_STEP_REVIEW_PATHS:
            text = _read(path)
            assert "skip_review" not in text, f"{path.name} must not name skip_review"
            if path in (APPLY_REVIEW_LOOP, APPLY_MD, APPLY_ONE_STEP_MD):
                assert "step_review" in text, f"{path.name} must name step_review"

    def test_readme_lists_step_review_true(self):
        for path in (README_MD, README_ZH):
            text = _read(path)
            assert "step_review       = true" in text, (
                f"{path.name} config example must show step_review = true"
            )
            assert "skip_review" not in text


class TestApplyReviewNoCheckout:
    def test_review_loop_reattaches_after_review(self):
        section = _h2_section(_read(APPLY_REVIEW_LOOP), "6a. Review sub-agent")
        _index(section, "git checkout")
        _index(section, "detached HEAD")
        ensure_at = _index(section, "apply-helper ensure-branch")
        six_b_at = _index(section, "Then continue to **6b**")
        assert ensure_at < six_b_at

    def test_review_loop_reattaches_after_fix(self):
        text = _read(APPLY_REVIEW_LOOP)
        section = _h3_section(text, "6c-ii. Fix + amend one finding")
        _index(section, "apply-helper ensure-branch")
        _index(section, "detached HEAD")

    def test_apply_review_template_forbids_checkout(self):
        path = (
            REPO_ROOT / "skills" / "spex" / "templates" / "apply-review.md"
        )
        text = _read(path)
        _index(text, "Git / HEAD safety")
        _index(text, "FORBIDDEN")
        _index(text, "git checkout")
        _index(text, "detached HEAD")
