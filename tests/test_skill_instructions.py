"""Regression tests for SKILL.md W007 credential-routing language."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "spex" / "SKILL.md"
COMPACT_SOP = REPO_ROOT / "skills" / "spex" / "references" / "compact-sop-style.md"

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
