# spex create

**PLAN only** — this command produces spec documents and a todo list.
It does NOT write any application code.

Create a new specification topic with requirement analysis, detailed design,
and test plan.

## Usage

```text
/spex create [input]
```

## Procedure

- **Role**: Act as a senior software architect. Focus on requirement
  completeness, edge cases, and testability.

**SCOPE: This command creates documents only — `spec.md`, `todo.json`,
`meta.json` inside the topic directory. NO application code is written.
NO existing project files are modified. Implementation happens later
via `/spex apply` or `/spex apply-one-step`.**

Follow these steps in order. Do not skip or reorder.

### Phase 1: Validate Branch

Run:

```bash
$spex_skill_dir/scripts/spex create-helper precheck
```

If the script exits with an error (non-zero), the error message is already
printed to stderr. Stop execution. On success, continue to the next phase.

### Phase 2: Clarify Requirement

If `$input` is not provided or empty, ask the user to describe the requirement.

Once you have `$input`, explore the workspace **only enough to understand
where the relevant code lives and what existing patterns to reference in the
spec**. Identify any ambiguities, contradictions, or cases where
multiple implementation approaches exist. Ask the user to clarify these
points before proceeding. **Do NOT read full implementation details or start
modifying any files — those are handled by `/spex apply`.**

After clarification, record the complete, unambiguous requirement as
`$requirement`.

### Phase 3: Generate Topic and Description

Based on `$requirement`, generate a JSON object with two fields:

- `topic`: a short English name (<32 bytes) using only `[a-z0-9-]`,
  replacing spaces with `-`. Do NOT prepend any date prefix.
- `description`: a brief English summary of the requirement, used as
  merge commit message and PR description. Wrap lines at ~60 characters.

Example: `{"topic": "add-login-api", "description": "Add user login API with JWT authentication"}`

Parse this JSON and save the values as `$topic` and `$description`.

### Phase 4: Prepare Topic Directory

Run:

```bash
echo "$requirement" | $spex_skill_dir/scripts/spex create-helper prepare-spec --description "$description" --topic $topic
```

The script creates the topic directory and `meta.json` (with the
requirement saved to its `prompts` field and the description saved to
its `description` field). Parse the JSON output and
save these variables:

- `$topic_name` ← `topic_name` (topic with date prefix,
  e.g., `2026-05-24-10-30-add-login-api`)
- `$topic_path` ← `topic_path`
- `$spec_template` ← `spec_template`

If the script exits with an error, return to Phase 3 and retry with a
different name.

Example JSON output:

```json
{
  "topic_name": "2026-05-24-10-30-add-login-api",
  "topic_path": "/path/to/.spex/specs/2026-05-24-10-30-add-login-api",
  "spec_template": "# [Title]\n..."
}
```

**Sub-agent boundary.** Launch a sub-agent to execute Phases 5
through 7. The sub-agent receives `$requirement`, `$topic_name`,
`$topic_path`, and `$spec_template` as context. If the sub-agent
fails, report the error to the user and retry. After it completes,
continue with Phase 8 in the main context.

### Phase 5: Design Specification

Perform detailed requirement analysis and solution design based on
`$requirement`. Consider functional requirements, non-functional requirements,
data models, API contracts, error handling, and edge cases.

Using `$spec_template` as the template, create `$topic_path/spec.md`
in the same language as the user's requirement (e.g., English or Chinese).
Replace the placeholder sections (HTML comments like
`<!-- Replace this section with ... -->`) with the analysis and design
results. Fill the "User Clarification" section with clarifications
gathered in Phase 2. Keep the Constraints section as-is.
Do not remove or modify `<!-- spex:begin:* -->` comment lines.

### Phase 6: Plan Implementation Steps

Based on the design in `$topic_path/spec.md`, break down the work into
incremental development steps. Each step should be independently
committable and verifiable.

Principles:

- **Small batches**: each step delivers a minimal, working increment.
- **Self-contained**: group production code and its tests in the same
  step — never split them into separate steps.
- **Ordered by dependency**: list steps so that each builds on the
  previous one; no forward references.

Use `spex todo-helper` to build `todo.json` step by step.
Number steps sequentially: `step-1`, `step-2`, etc.

**Append** a step — use `--details-from-stdin` with a heredoc for
multi-line Markdown details:

```bash
$spex_skill_dir/scripts/spex todo-helper --topic $topic_name append \
  --id step-1 --name "Short name" --details-from-stdin <<'DETAILS'
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

- Create `src/auth.py` with login endpoint
- Add input validation for email and password
- Write unit tests in `tests/test_auth.py`

**Acceptance criteria**: all tests pass, endpoint returns JWT
DETAILS
```

**Show** current steps (to review before adding more):

```bash
$spex_skill_dir/scripts/spex todo-helper --topic $topic_name show \
  --format markdown
```

**Edit** a step (only specified fields are updated):

```bash
$spex_skill_dir/scripts/spex todo-helper --topic $topic_name edit \
  --id step-1 --details-from-stdin <<'DETAILS'
Updated multi-line details for this step.

- Revised implementation approach
- Added error handling requirements
DETAILS
```

**Remove** a step:

```bash
$spex_skill_dir/scripts/spex todo-helper --topic $topic_name remove \
  --id step-1
```

The `details` field supports multi-line Markdown:

- Including file changes, logic, and acceptance criteria, etc.
- Use lists, bold, and inline code.
- Do not use headings (`#`, `##`, etc.)

### Phase 7: Post-Action

Run:

```bash
$spex_skill_dir/scripts/spex create-helper post-action --topic $topic_name
```

If the script exits with an error, read the error message, fix the
JSON format in `todo.json`, and re-run until validation succeeds.

### Phase 8: Output

Display the following summary to the user:

```text
**Topic**: `$topic_name`

- Spec: `$topic_path/spec.md`
- Todo: `$topic_path/todo.json`
- Meta: `$topic_path/meta.json`
```

### Phase 9: STOP — Do NOT Implement

**This is a hard stop. Do NOT write any application code, modify any
project files, or begin implementing the steps planned in `todo.json`.**

Planning is complete. The `/spex create` command's sole responsibility
was to produce the spec documents (`spec.md`, `todo.json`, `meta.json`)
inside the topic directory.

Wait for the user to review the spec and invoke `/spex apply` or
`/spex apply-one-step` when ready.
