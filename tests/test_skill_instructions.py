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
SPEC_ASSETS = REPO_ROOT / "skills" / "spex" / "references" / "spec-assets.md"
TODO_HELPER_COOKBOOK = (
    REPO_ROOT / "skills" / "spex" / "references" / "todo-helper-cookbook.md"
)
RESOLVE_SPEC_LIST = (
    REPO_ROOT / "skills" / "spex" / "references" / "resolve-spec-list.md"
)
APPLY_TASK_PHASES = (
    REPO_ROOT / "skills" / "spex" / "references" / "apply-task-phases.md"
)
APPLY_SUBAGENT_HANDOFF = (
    REPO_ROOT / "skills" / "spex" / "references" / "apply-subagent-handoff.md"
)
MERGE_MD = REPO_ROOT / "skills" / "spex" / "commands" / "merge.md"
ARCHIVE_MD = REPO_ROOT / "skills" / "spex" / "commands" / "archive.md"
INIT_MD = REPO_ROOT / "skills" / "spex" / "commands" / "init.md"
MODIFY_TODO = REPO_ROOT / "skills" / "spex" / "templates" / "modify-todo.md"
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

    def test_redact_before_assigning_user_prompt(self):
        body = _skill_body()
        assert (
            "Redact secrets in user text BEFORE assigning `$user_prompt`"
            in body
        )
        assert "redact" in body.lower()

    def test_user_prompt_assignment_lines_require_redact(self):
        body = _skill_body()
        assignment_lines = [
            line for line in body.splitlines() if "$user_prompt" in line
        ]
        assert assignment_lines, (
            "expected $user_prompt assignment lines in SKILL.md"
        )
        for line in assignment_lines:
            assert "redact" in line.lower(), (
                f"$user_prompt assignment must mention redact: {line!r}"
            )
        joined = "\n".join(assignment_lines)
        assert "pass redacted user text as `$user_prompt`" in joined
        assert "Redact secrets in user text => `$user_prompt`" in joined
        assert "full redacted text => `$user_prompt`" in joined

    def test_no_router_prompt_assignment_or_confidence(self):
        body = _skill_body()
        text = _read(SKILL_MD)
        prompt_lines = [
            line for line in body.splitlines() if "$prompt" in line
        ]
        assert not prompt_lines, (
            "SKILL.md must not assign router $prompt; use $user_prompt: "
            + repr(prompt_lines)
        )
        assert "confidence >= 90%" not in text
        assert "confidence ≥ 90%" not in text
        assert "$spex_skill_dir" in body
        assert "absolute directory containing this `SKILL.md`" in body

        # Front-matter free-form summary (no confidence threshold)
        fm_end = text.find("\n---", 3)
        assert fm_end != -1, "SKILL.md missing front-matter close"
        front_matter = text[: fm_end + 4]
        assert "confidence" not in front_matter.lower()
        assert "explicit command verb/alias with single intent → route" in (
            front_matter
        )
        assert (
            "change-requirements uniquely tied to an active spec → modify"
            in front_matter
        )
        assert "too vague → show Supported Commands" in front_matter
        assert (
            "otherwise list candidates and ask to confirm" in front_matter
        )

        # Ordered Decision rules in Free-form Intent Inference
        rules = _h3_section(body, "Free-form Intent Inference")
        r1 = _index(rules, "Explicit command alias/verb and single intent")
        r2 = _index(rules, "uniquely ties to")
        r3 = _index(rules, "Too short/vague")
        r4 = _index(rules, "Otherwise OR multiple commands plausible")
        assert "-> route" in rules[r1 : r1 + 80]
        assert "`modify`" in rules[r2 : r2 + 120]
        assert "Supported" in rules[r3 : r3 + 80]
        assert "Commands" in rules[r3 : r3 + 120]
        assert "list candidates" in rules[r4 : r4 + 120]
        assert r1 < r2 < r3 < r4, (
            "Decision rules must stay in order: "
            "alias/verb -> modify -> vague -> candidates"
        )

    def test_no_unintended_prompt_var_in_sop_paths(self):
        """Sweep SKILL/commands/references: no leftover router `$prompt`.

        Only the pedagogical forbid in apply-task-phases Phase 3 bind
        rules may mention `$prompt` (JSON field remains `"prompt"`).
        """
        allowed_substrings = {
            APPLY_TASK_PHASES: ("(never call this `$prompt`)",),
        }
        sop_paths = (
            SKILL_MD,
            COMPACT_SOP,
            CREATE_MD,
            MODIFY_MD,
            APPLY_MD,
            APPLY_ONE_STEP_MD,
            MERGE_MD,
            ARCHIVE_MD,
            INIT_MD,
            APPLY_TASK_PHASES,
            APPLY_SUBAGENT_HANDOFF,
            APPLY_REVIEW_LOOP,
            SPEC_ASSETS,
            TODO_HELPER_COOKBOOK,
            RESOLVE_SPEC_LIST,
        )
        leftovers: list[str] = []
        for path in sop_paths:
            allow = allowed_substrings.get(path, ())
            for lineno, line in enumerate(
                _read(path).splitlines(), start=1
            ):
                if "$prompt" not in line:
                    continue
                if any(token in line for token in allow):
                    continue
                leftovers.append(f"{path.name}:{lineno}: {line.strip()}")
        assert not leftovers, (
            "unintended router $prompt in SOP paths "
            "(use $user_prompt / $task_prompt): " + repr(leftovers)
        )
        # Keep the explicit rename forbid so `$task_prompt` cannot drift
        phase3 = _h2_section(
            _read(APPLY_TASK_PHASES), "Phase 3: Build Prompt / Resume Gate"
        )
        _index(phase3, '`$task_prompt` ← `"prompt"`')
        _index(phase3, "(never call this `$prompt`)")


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
    def test_mentions_user_prompt_and_task_prompt(self):
        text = _read(COMPACT_SOP)
        assert "redact" in text.lower()
        assert "`$user_prompt`" in text
        assert "`$task_prompt`" in text
        assert "BEFORE assigning `$user_prompt`" in text
        assert "confidence >= 90%" not in text
        assert "confidence ≥ 90%" not in text
        assert "$prompt" not in text, (
            "compact-sop-style must not use router $prompt; "
            "use $user_prompt / $task_prompt"
        )

        # Free-form decision-rule skeleton (ordered anchors)
        r1 = _index(text, "Explicit alias/verb + single intent -> route")
        r2 = _index(
            text, "Change-requirements uniquely tied to active spec -> `modify`"
        )
        r3 = _index(text, "Too vague -> show Supported Commands")
        r4 = _index(text, "ELSE / multiple plausible -> list candidates")
        assert r1 < r2 < r3 < r4, (
            "Compact free-form rules must stay ordered: "
            "alias/verb -> modify -> vague -> candidates"
        )


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


class TestCreatePlanOnlySop:
    """Lock create.md PLAN-only binding, phases, and Load pointers."""

    def test_binds_input_from_user_prompt(self):
        pre = _h2_section(_read(CREATE_MD), "Preconditions")
        _index(pre, "`$input` ← `$user_prompt`")

    def test_plan_write_whitelist_only_spec_path(self):
        text = _read(CREATE_MD)
        pre = _h2_section(text, "Preconditions")
        _index(pre, "write **only** under `$spec_path`")
        _index(pre, "Glob")
        _index(pre, "Grep")
        _index(pre, "untrusted")
        phase9 = _h3_section(text, "Phase 9: STOP — Do NOT Implement")
        _index(phase9, "outside `$spec_path`")

    def test_phase1_begin_session_precheck_title(self):
        text = _read(CREATE_MD)
        phase1 = _h3_section(text, "Phase 1: Begin Session + Precheck")
        _index(phase1, "create-helper begin-session")
        _index(phase1, "create-helper precheck")
        assert "### Phase 1: Validate Branch" not in text

    def test_phase3_requires_exactly_one_fenced_json(self):
        phase3 = _h3_section(
            _read(CREATE_MD), "Phase 3: Generate Name and Description"
        )
        _index(phase3, "exactly one")
        _index(phase3, "fenced `json`")
        _index(phase3, "Phase 8")
        assert '"name"' in phase3 or "`name`" in phase3
        assert '"description"' in phase3 or "`description`" in phase3

    def test_phase5_6_load_shared_references(self):
        text = _read(CREATE_MD)
        phase5 = _h3_section(text, "Phase 5: Design Specification")
        _index(phase5, "Load and follow `references/spec-assets.md`")
        phase6 = _h3_section(text, "Phase 6: Plan Implementation Steps")
        _index(
            phase6,
            "Load and follow `references/todo-helper-cookbook.md`",
        )
        _index(phase6, "Small batches")
        _index(phase6, "skip_commit")

    def test_has_failure_handling_section(self):
        section = _h2_section(_read(CREATE_MD), "Failure Handling")
        _index(section, "ON_FAIL")
        _index(section, "`$spec_path`")


class TestModifyPlanOnlySop:
    """Lock modify.md binding, PLAN whitelist, and Load pointers."""

    def test_binds_spec_name_and_request_from_user_prompt(self):
        pre = _h2_section(_read(MODIFY_MD), "Preconditions")
        _index(pre, "`$user_prompt`")
        _index(pre, "`$spec_name`")
        _index(pre, "`$request`")
        _index(pre, "priority")
        _index(pre, "untrusted")
        _index(pre, "looks like a spec name")
        _index(pre, "`^[a-z0-9-]+$`")
        _index(pre, "≤ 64")
        _index(pre, r"`^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[a-z0-9-]+$`")
        _index(pre, "no whitespace")
        _index(pre, "multi-word")
        _index(pre, "name candidate")
        _index(pre, "`$spec_name` ← the candidate")
        _index(pre, "`[]`")
        _index(pre, "unlike a name")
        _index(pre, "whole `$user_prompt`")
        _index(pre, "rebind")
        _index(pre, "re-run Phase 1 with empty name")
        _index(pre, "not** confirming")
        _index(pre, "`$request`")

    def test_plan_write_whitelist_only_spec_path(self):
        text = _read(MODIFY_MD)
        pre = _h2_section(text, "Preconditions")
        _index(pre, "write **only** under `$spec_path`")
        _index(pre, "Glob")
        _index(pre, "Grep")
        phase10 = _h3_section(text, "Phase 10: STOP — Do NOT Implement")
        _index(phase10, "outside `$spec_path`")

    def test_phase1_loads_resolve_spec_list(self):
        phase1 = _h3_section(_read(MODIFY_MD), "Phase 1: Resolve Spec")
        _index(
            phase1,
            "Load and follow `references/resolve-spec-list.md`",
        )
        _index(phase1, "`[]`")
        _index(phase1, "not** confirm")
        _index(phase1, "`$request`")

    def test_phase2_selecting_spec_does_not_confirm_request(self):
        phase2 = _h3_section(
            _read(MODIFY_MD), "Phase 2: Understand Context and Clarify"
        )
        _index(phase2, "never")
        _index(phase2, "confirms `$request`")

    def test_phase3_loads_spec_assets(self):
        phase3 = _h3_section(_read(MODIFY_MD), "Phase 3: Save Request")
        _index(phase3, "Load and follow `references/spec-assets.md`")

    def test_phase5_readonly_updates_spec_md_only(self):
        phase5 = _h3_section(_read(MODIFY_MD), "Phase 5: Modify spec.md")
        _index(phase5, "update **only** `$spec_path/spec.md`")
        _index(phase5, "Read-only explore")
        _index(phase5, "ON_FAIL")
        lower = phase5.lower()
        assert "integrates with existing code" not in lower
        assert "review current codebase structure" not in lower

    def test_phase7_keeps_hard_planning_principles(self):
        phase7 = _h3_section(
            _read(MODIFY_MD), "Phase 7: Regenerate Development Steps"
        )
        _index(phase7, "`$todo_prompt`")
        _index(phase7, "Preserve completed work")
        _index(phase7, "Small batches")
        _index(phase7, "Self-contained")
        _index(phase7, "skip_commit")
        _index(phase7, "ON_FAIL")
        _index(
            phase7,
            "Load and follow `references/todo-helper-cookbook.md`",
        )

    def test_has_failure_handling_section(self):
        section = _h2_section(_read(MODIFY_MD), "Failure Handling")
        _index(section, "ON_FAIL")
        _index(section, "`$spec_path`")
        _index(section, "Phase 5")
        _index(section, "Phase 7")
        _index(section, "immediate STOP")
        _index(section, "roll back")
        _index(section, "`--remove-undone` recovery")
        _index(section, "Phase 4")
        _index(section, "git restore")
        _index(section, "half-done")


class TestModifyPhase9JsonResult:
    """Lock modify.md Phase 9 human summary + machine-result JSON."""

    def test_phase9_has_human_summary_spec_line(self):
        phase9 = _h3_section(_read(MODIFY_MD), "Phase 9: Output")
        assert "**Spec**:" in phase9

    def test_phase9_has_fenced_json_with_required_keys(self):
        phase9 = _h3_section(_read(MODIFY_MD), "Phase 9: Output")
        assert "```json" in phase9
        assert '"spec_name"' in phase9
        assert '"spec_path"' in phase9

    def test_phase9_instructs_parsing_last_fenced_json(self):
        phase9 = _h3_section(_read(MODIFY_MD), "Phase 9: Output")
        _index(phase9, "parse the last fenced")
        _index(phase9, "json")
        _index(phase9, "block")


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
        probe_at = _index(section, "prompt apply-review --json")
        skipped_at = _index(section, '"skipped": true')
        no_6c_at = _index(section, "do **not** enter **6c**")
        phase7_at = _index(section, "to Phase 7")
        assert probe_at < skipped_at < no_6c_at < phase7_at
        # Single detection path — no “read config or probe” dual path
        assert "read config, or" not in section.lower()
        assert "or probe" not in section.lower()
        _index(section, "do **not** read")
        _index(section, ".spex.toml")

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
            # No duplicated review-helper CLI tips in command Phase 6
            assert "config get" not in phase6.lower()
            assert "skip_review" not in phase6
            assert "bump-round" not in phase6
            assert "review-helper" not in phase6

    def test_apply_commands_load_shared_phase_refs(self):
        """Commands Load shared refs; skip_commit semantics live in refs."""
        apply = _read(APPLY_MD)
        one = _read(APPLY_ONE_STEP_MD)

        for text in (apply, one):
            pre = _h2_section(text, "Preconditions")
            _index(pre, "`$user_prompt`")
            _index(pre, "untrusted")
            _index(pre, "SCOPE")
            _index(pre, "`$spex_root`")
            _index(_h2_section(text, "Failure Handling"), "ON_FAIL")
            for phase, title in (
                ("Phase 2: Validate Branch", "apply-task-phases.md"),
                ("Phase 3: Build Prompt / Resume Gate", "apply-task-phases.md"),
                ("Phase 4: Execute Task", "apply-task-phases.md"),
                (
                    "Phase 5: Commit (record commit_title only)",
                    "apply-task-phases.md",
                ),
                ("Phase 7: Mark Task Complete", "apply-task-phases.md"),
            ):
                _index(
                    _h3_section(text, phase),
                    f"Load and follow `references/{title}`",
                )
            phase3 = _h3_section(text, "Phase 3: Build Prompt / Resume Gate")
            _index(phase3, "`$task_prompt`")
            _index(phase3, "`$skip_commit`")
            phase6 = _h3_section(text, "Phase 6: Review Loop")
            _index(phase6, "`$did_commit`")
            phase1 = _h3_section(text, "Phase 1: Resolve Spec")
            _index(
                phase1,
                "Load and follow `references/resolve-spec-list.md`",
            )

        # apply.md: handoff + control-flow + --all / Phase 8–9
        _index(
            _h3_section(apply, "Phase 3: Build Prompt / Resume Gate"),
            "`references/apply-subagent-handoff.md`",
        )
        phase3_apply = _h3_section(
            apply, "Phase 3: Build Prompt / Resume Gate"
        )
        assert "Load and follow" in phase3_apply
        assert "apply-subagent-handoff.md" in phase3_apply
        control = _h2_section(apply, "Control flow")
        _index(control, "```mermaid")
        _index(control, "apply-task-phases.md")
        _index(control, "apply-subagent-handoff.md")
        _index(_h3_section(apply, "Phase 1: Resolve Spec"), "--all")
        _index(_h3_section(apply, "Phase 8: Next Task"), "Phase 3")
        _index(_h3_section(apply, "Phase 9: Post Action"), "post-action")
        assert "apply-subagent-handoff" not in one

        # apply-one-step: HARD STOP + only current task + post-action
        phase4 = _h3_section(one, "Phase 4: Execute Task")
        _index(phase4, "**Only** `$current_task_id`")
        phase8 = _h3_section(one, "Phase 8: Summary and Conditional Post Action")
        _index(phase8, "HARD STOP")
        _index(phase8, "idempotent")
        phase3_one = _h3_section(one, "Phase 3: Build Prompt / Resume Gate")
        _index(phase3_one, "idempotent")

    def test_apply_skip_commit_semantics_in_shared_refs(self):
        """Regression anchors moved to references (no semantic loss)."""
        phases = _read(APPLY_TASK_PHASES)
        handoff = _read(APPLY_SUBAGENT_HANDOFF)

        phase2 = _h2_section(phases, "Phase 2: Validate Branch")
        _index(phase2, "`$spex_root`")
        _index(phase2, "spex config")
        _index(phase2, "Paths")
        _index(phase2, "Do **not** use Config")

        phase3 = _h2_section(phases, "Phase 3: Build Prompt / Resume Gate")
        _index(phase3, "`$task_prompt`")
        _index(phase3, "`$skip_commit`")
        _index(phase3, "**FAIL**")

        phase4 = _h2_section(phases, "Phase 4: Execute Task")
        _index(phase4, "`$skip_commit`")
        _index(phase4, "`$dirty`")
        _index(phase4, "whole working tree")
        _index(phase4, "apply-helper dirty --json")
        _index(phase4, "`$did_commit=false`")
        _index(phase4, "**FAIL/STOP**")
        _index(phase4, "directory boundary")
        _index(phase4, "bare string prefix")
        _index(phase4, "outcome=skip_commit")

        phase5 = _h2_section(phases, "Phase 5: Commit (record commit_title only)")
        _index(phase5, "`$did_commit`")
        _index(phase5, "Recompute `$dirty`")
        _index(phase5, "Leftover dirty paths poison")
        _index(phase5, "do not persist `commit_title`")
        _index(phase5, "outcome=committed")

        phase6 = _h2_section(phases, "Phase 6: Review Loop")
        _index(phase6, "`$did_commit`")
        _index(phase6, "`step_review=false`")
        _index(phase6, "abnormal STOP")
        _index(phase6, '"skipped": true')

        phase7 = _h2_section(phases, "Phase 7: Mark Task Complete")
        _index(phase7, "`$did_commit`")
        _index(phase7, "Refresh `$commit_title` if needed")

        # Handoff decision table (apply main session only)
        _index(handoff, "outcome=skip_commit")
        _index(handoff, "outcome=committed")
        _index(handoff, "intentional STOP")
        _index(handoff, "empty `commit_title` alone")
        _index(handoff, "recompute `$dirty`")
        _index(handoff, "tree dirty")
        _index(handoff, "task's `commit_title`")

    def test_modify_todo_omit_skip_commit_on_coding_example(self):
        text = _read(MODIFY_TODO)
        # Coding append bash block must not pass --skip-commit
        coding = text.split("**Append** a coding step", 1)[1]
        coding = coding.split("**Append** a non-coding", 1)[0]
        bash = coding.split("```bash", 1)[1].split("```", 1)[0]
        assert "--skip-commit" not in bash
        non_coding = text.split("**Append** a non-coding", 1)[1]
        non_coding = non_coding.split("**Show**", 1)[0]
        assert "--skip-commit true" in non_coding
        assert "Do **not** put `--skip-commit true` on coding steps" in text

    def test_review_loop_requires_did_commit_precondition(self):
        text = _read(APPLY_REVIEW_LOOP)
        assert "produced a git commit" in text
        assert "`$did_commit`" in text
        assert "skip_commit" in text
        assert "Orthogonal to global `step_review`" in text

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

    def test_readme_documents_skip_commit(self):
        for path in (README_MD, README_ZH):
            text = _read(path)
            assert "skip_commit" in text, (
                f"{path.name} must document skip_commit"
            )
            assert "step_review" in text, (
                f"{path.name} must relate skip_commit to step_review"
            )
            assert "whole working tree" in text or "整棵工作区" in text, (
                f"{path.name} must document whole-tree dirty checks"
            )
            assert (
                "leftover" in text.lower()
                or "残留" in text
            ), (
                f"{path.name} must document post-commit residue risk"
            )

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


class TestCreatePhase8JsonResult:
    """Lock create.md Phase 8 human summary + machine-result JSON contract."""

    def test_phase8_has_human_summary_spec_line(self):
        phase8 = _h3_section(_read(CREATE_MD), "Phase 8: Output")
        assert "**Spec**:" in phase8

    def test_phase8_has_fenced_json_with_required_keys(self):
        phase8 = _h3_section(_read(CREATE_MD), "Phase 8: Output")
        assert "```json" in phase8
        assert '"spec_name"' in phase8
        assert '"spec_path"' in phase8

    def test_phase8_instructs_parsing_last_fenced_json(self):
        phase8 = _h3_section(_read(CREATE_MD), "Phase 8: Output")
        _index(phase8, "parse the last fenced")
        _index(phase8, "json")
        _index(phase8, "block")


class TestSharedSopReferences:
    """Existence + marker locks for shared create/modify references."""

    def test_spec_assets_exists_with_image_markers(self):
        assert SPEC_ASSETS.is_file()
        text = _read(SPEC_ASSETS)
        _index(text, "--add-images")
        _index(text, "assets/")
        _index(text, "![description](assets/filename.png)")
        _index(text, "meta-helper")

    def test_todo_helper_cookbook_skip_commit_matches_modify_todo(self):
        assert TODO_HELPER_COOKBOOK.is_file()
        cookbook = _read(TODO_HELPER_COOKBOOK)
        modify_todo = _read(MODIFY_TODO)

        # Coding append: omit --skip-commit (same rule as modify-todo)
        coding = cookbook.split("**Coding step**", 1)[1]
        coding = coding.split("**Non-coding", 1)[0]
        bash = coding.split("```bash", 1)[1].split("```", 1)[0]
        assert "--skip-commit" not in bash

        non_coding = cookbook.split("**Non-coding", 1)[1]
        non_coding = non_coding.split("## Show", 1)[0]
        assert "--skip-commit true" in non_coding
        assert "Do **not** put `--skip-commit true` on coding steps" in cookbook

        # Shared guidance must stay consistent with modify-todo template
        assert "Do **not** put `--skip-commit true` on coding steps" in (
            modify_todo
        )
        _index(cookbook, "omit")
        _index(cookbook, "`auto`")
        _index(cookbook, "Do **not** use headings")

    def test_resolve_spec_list_exists_with_branch_markers(self):
        assert RESOLVE_SPEC_LIST.is_file()
        text = _read(RESOLVE_SPEC_LIST)
        _index(text, "list --json")
        _index(text, "`[]` / zero elements")
        _index(text, "not** a script error")
        _index(text, "Single element")
        _index(text, "Multiple")
        _index(text, "True error")
        _index(text, "**STOP**")

    def test_apply_task_phases_exists_with_core_anchors(self):
        assert APPLY_TASK_PHASES.is_file()
        text = _read(APPLY_TASK_PHASES)
        _index(text, "`$task_prompt`")
        _index(text, "apply-helper dirty --json")
        _index(text, "skip_commit six-arm")
        _index(text, "**FAIL/STOP**")
        _index(text, "outcome=committed")
        _index(text, "outcome=skip_commit")
        _index(text, "`$did_commit`")
        _index(text, "do not persist `commit_title`")
        _index(text, "Paths")
        _index(text, "directory boundary")

    def test_apply_subagent_handoff_exists_with_outcome_anchors(self):
        assert APPLY_SUBAGENT_HANDOFF.is_file()
        text = _read(APPLY_SUBAGENT_HANDOFF)
        _index(text, "outcome=committed")
        _index(text, "outcome=skip_commit")
        _index(text, "intentional STOP")
        _index(text, "empty `commit_title` alone")
        _index(text, "apply-helper dirty --json")
        _index(text, "Do **not** rely on sub-agent")
        _index(text, "`$task_prompt`")


class TestMergeArchiveInitSop:
    """§6–8 polish: Inputs vs Phase 1, dry-run STOP, slim archive,
    init edges, Failure Handling / `$user_prompt` binding."""

    def test_merge_inputs_flags_only_selection_in_phase1(self):
        text = _read(MERGE_MD)
        inputs = _h2_section(text, "Inputs")
        _index(inputs, "`$spec_name`")
        _index(inputs, "--dry-run")
        assert "CLI searches" not in inputs
        assert "auto-select" not in inputs
        phase1 = _h3_section(text, "Phase 1: Resolve Spec")
        _index(
            phase1,
            "Load and follow `references/resolve-spec-list.md`",
        )
        pre = _h2_section(text, "Preconditions")
        _index(pre, "`$user_prompt`")
        _index(pre, "untrusted")
        _index(pre, "--dry-run")
        _index(pre, "**STOP**")
        fail = _h2_section(text, "Failure Handling")
        _index(fail, "ON_FAIL")
        _index(fail, "dry-run")
        phase2 = _h3_section(text, "Phase 2: Validate")
        _index(phase2, "spex_branch")
        _index(phase2, "fast-fail")

    def test_archive_preconditions_slim_cli_only(self):
        text = _read(ARCHIVE_MD)
        pre = _h2_section(text, "Preconditions")
        _index(pre, "`$user_prompt`")
        _index(pre, "Do **not** move")
        _index(pre, "only run the CLI")
        _index(pre, "`$spec_path`")
        _index(pre, "--dry-run")
        _index(pre, "**STOP**")
        _index(pre, "anywhere")
        _index(pre, "--json")
        # Script-enforced rules must not be re-taught in Preconditions
        assert "todo.json" not in pre
        assert "fuzzy" not in pre.lower()
        fail = _h2_section(text, "Failure Handling")
        _index(fail, "ON_FAIL")
        _index(fail, "dry-run")
        phase2 = _h3_section(text, "Phase 2: Report Results")
        _index(phase2, "$spec_path")
        _index(phase2, "--json")
        _index(phase2, "dry_run")
        _index(phase2, "results")
        assert "Archived: <name> -> <dest>" not in phase2

    def test_init_edge_notes_and_failure_handling(self):
        text = _read(INIT_MD)
        pre = _h2_section(text, "Preconditions")
        _index(pre, "`$user_prompt`")
        _index(pre, "Non-git")
        _index(pre, "Already initialized")
        _index(pre, "Warnings")
        fail = _h2_section(text, "Failure Handling")
        _index(fail, "ON_FAIL")
        _index(fail, "exit 0")
        _index(fail, "Warnings")
