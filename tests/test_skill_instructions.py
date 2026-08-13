"""Regression tests for SKILL.md W007 credential-routing language."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "spex" / "SKILL.md"
COMPACT_SOP = REPO_ROOT / "skills" / "spex" / "references" / "compact-sop-style.md"
CREATE_MD = REPO_ROOT / "skills" / "spex" / "commands" / "create.md"
MODIFY_MD = REPO_ROOT / "skills" / "spex" / "commands" / "modify.md"

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
