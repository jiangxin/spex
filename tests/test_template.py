"""Tests for the Spex stdlib template engine and dialect sync."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import template as tmpl

TEMPLATES = Path(__file__).resolve().parents[1] / "skills" / "spex" / "templates"
AGENTS = TEMPLATES / "AGENTS.md"
PROMPT_TEMPLATES = sorted(
    p for p in TEMPLATES.glob("*.md") if p.name != "AGENTS.md"
)


class TestRenderBasics:
    def test_interpolation_and_or(self):
        assert tmpl.render("Hi {{ name }}!", {"name": "Ada"}) == "Hi Ada!"
        assert tmpl.render("{{ a or b }}", {"a": "", "b": "B"}) == "B"
        assert tmpl.render("{{ a or b }}", {"a": "A", "b": "B"}) == "A"
        assert tmpl.render("X{{ missing }}Y", {}) == "XY"

    def test_if_elif_else_and_not(self):
        src = "{% if a %}A{% elif b %}B{% else %}C{% endif %}"
        assert tmpl.render(src, {"a": "1"}) == "A"
        assert tmpl.render(src, {"b": "1"}) == "B"
        assert tmpl.render(src, {}) == "C"
        assert tmpl.render("{% if not x %}T{% else %}F{% endif %}", {}) == "T"
        assert tmpl.render(
            "{% if a and b %}T{% else %}F{% endif %}", {"a": "1", "b": ""},
        ) == "F"

    def test_default_and_int_filters(self):
        assert tmpl.render("{{ x | default('D') }}", {}) == "D"
        assert tmpl.render("{{ x | default('D') }}", {"x": ""}) == ""
        assert tmpl.render(
            "{{ review_mode | default(mode | default('full')) }}",
            {"mode": "delta"},
        ) == "delta"
        assert tmpl.render(
            "{{ review_mode | default(mode | default('full')) }}", {},
        ) == "full"
        assert tmpl.render(
            "{% if review_round|int >= 2 %}Y{% else %}N{% endif %}",
            {"review_round": "2"},
        ) == "Y"
        assert tmpl.render(
            "{% if review_round|int >= 2 %}Y{% else %}N{% endif %}",
            {"review_round": "$x"},
        ) == "N"
        with pytest.raises(tmpl.TemplateError, match="undefined"):
            tmpl.render("{% if x|int >= 1 %}Y{% endif %}", {})

    def test_comparisons_and_inline_whitespace(self):
        src = (
            "rev{% if m | default(n | default('full')) == 'delta' -%},\n"
            "  diff {{ a or b }}{% endif %}."
        )
        assert tmpl.render(src, {"m": "delta", "a": "", "b": "B"}) == (
            "rev,\n  diff B."
        )
        assert tmpl.render(
            "{% if open_findings and open_findings != '(no open findings)' %}"
            "Y{% else %}N{% endif %}",
            {"open_findings": "(no open findings)"},
        ) == "N"
        assert tmpl.render(
            "A\n{% if x -%}\nB\n{% endif -%}\nC\n", {"x": "1"},
        ) == "A\nB\nC"

    def test_trailing_newline_stripped(self):
        assert tmpl.render("hello\n", {}) == "hello"
        assert tmpl.render("hello", {}) == "hello"

    def test_rejects_forbidden_tags_and_filters(self):
        with pytest.raises(tmpl.TemplateError, match="Unsupported"):
            tmpl.render("{% for x in y %}{% endfor %}", {})
        with pytest.raises(tmpl.TemplateError, match="Unsupported filter"):
            tmpl.render("{{ x | upper }}", {"x": "a"})
        with pytest.raises(tmpl.TemplateError, match="Unexpected"):
            tmpl.render("{% endif %}", {})


class TestPromptTemplateGoldens:
    """Render each shipped prompt template with a fixed context."""

    CONTEXT = {
        "commit_sha": "abc1234",
        "step_id": "step-1",
        "review_file": "review-step-1.json",
        "review_round": 1,
        "spec_name": "demo-spec",
        "spex_skill_dir": "/skill/spex",
        "spex_root": ".spex",
        "spec_content": "# Spec\n",
        "spec_content_concise": "# Spec\n",
        "current_task_description": "Do the thing",
        "completed_tasks_concise": "- done",
        "future_tasks_concise": "- later",
        "completed_tasks": "- done",
        "prompt_context": "User asked for X",
        "acceptance_criteria": "- pass tests",
        "open_findings": "(no open findings)",
        "commit_diff": "diff --git a/x b/x",
        "finding_ids": "r1-f1",
        "user_name": "Ada",
        "user_email": "ada@example.com",
        "check_evidence_reusable": False,
        "review_mode": "full",
        "mode": "full",
        "fix_base_commit_sha": "",
        "fixed_commit_sha": "",
        "pending_has_major": False,
    }

    @pytest.mark.parametrize("path", PROMPT_TEMPLATES, ids=lambda p: p.name)
    def test_renders_without_error(self, path: Path):
        out = tmpl.render(path.read_text(encoding="utf-8"), self.CONTEXT)
        assert isinstance(out, str)
        assert "{{" not in out
        assert "{%" not in out


class TestTemplateScan:
    _FILTER_RE = re.compile(r"\|\s*([A-Za-z_][A-Za-z0-9_]*)")
    _TAG_WORD_RE = re.compile(r"^([A-Za-z_]+)")

    def test_prompt_templates_only_use_allowed_constructs(self):
        for path in PROMPT_TEMPLATES:
            source = path.read_text(encoding="utf-8")
            tmpl._parse(source)  # noqa: SLF001 — dialect parse check
            for body in tmpl.scan_template_constructs(source):
                word_match = self._TAG_WORD_RE.match(body)
                if word_match:
                    word = word_match.group(1)
                    if word in ("if", "elif", "else", "endif"):
                        continue
                    if word in tmpl.FORBIDDEN_TAG_WORDS:
                        pytest.fail(f"{path.name}: forbidden tag {word}")
                for filt in self._FILTER_RE.findall(body):
                    assert filt in tmpl.ALLOWED_FILTERS, (
                        f"{path.name}: unsupported filter |{filt} in {body!r}"
                    )

    def test_agents_md_mentions_dialect_contract(self):
        text = AGENTS.read_text(encoding="utf-8")
        for needle in (
            "template.py",
            "default",
            "int",
            "elif",
            "endif",
            "undefined",
            "Forbidden",
            "for",
            "macro",
            "include",
            "whitespace",
            "same change",
        ):
            assert needle in text, f"AGENTS.md missing {needle!r}"
        assert "Jinja2" in text
        assert "not" in text.lower()
