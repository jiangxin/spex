# spex create

Create a new specification topic with requirement analysis, detailed design,
and test plan.

## Usage

```text
/spex create [input]
```

## Procedure

- **Execution**: Run in a dedicated sub-agent to keep the main context clean.
- **Role**: Act as a senior software architect. Focus on requirement
  completeness, edge cases, and testability.

Follow these steps in order. Do not skip or reorder.

### Phase 1: Validate Branch

Run:

```bash
$spex_skill_dir/scripts/spex create-helper --validate
```

If the script exits with an error (non-zero), the error message is already
printed to stderr. Stop execution. On success, continue to the next phase.

### Phase 2: Clarify Requirement

If `$input` is not provided or empty, ask the user to describe the requirement.

Once you have `$input`, explore the workspace to understand the current
codebase context. Identify any ambiguities, contradictions, or cases where
multiple implementation approaches exist. Ask the user to clarify these
points before proceeding.

After clarification, record the complete, unambiguous requirement as
`$requirement`.

### Phase 3: Generate Topic and Description

Based on `$requirement`, generate a JSON object with two fields:

- `topic`: a short English name (<32 bytes) using only `[a-z0-9-]`,
  replacing spaces with `-`. Do NOT prepend any date prefix.
- `description`: a brief English summary of the requirement, ideally
  under 100 characters.

Example: `{"topic": "add-login-api", "description": "Add user login API with JWT authentication"}`

Parse this JSON and save the values as `$topic` and `$description`.

### Phase 4: Prepare Topic Directory

Run:

```bash
echo "$requirement" | $spex_skill_dir/scripts/spex create-topic --json --description "$description" --get-prompt "spec-template" $topic
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

Create `$topic_path/todo.xml` listing each step in order:

```xml
<steps>
  <step>
    <step-id>step-1</step-id>
    <step-name>Short name for the step</step-name>
    <step-markdown-details>
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

- Use lists, bold, and inline code
- Do not use headings (`#`, `##`, etc.)
    </step-markdown-details>
  </step>
</steps>
```

- `<step-markdown-details>`: multi-line Markdown text describing the
  step. No escaping needed — write Markdown directly inside the tag.
- Number steps sequentially: `step-1`, `step-2`, etc.

**CRITICAL — the xml2json parser will reject any deviation from this
structure:**

- Root element **MUST** be `<steps>` (not `<tasks>`, `<todo>`, etc.).
- Each step **MUST** be wrapped in `<step>` (not `<task>`, `<item>`, etc.).
- Each `<step>` **MUST** contain exactly three children in order:
  `<step-id>`, `<step-name>`, `<step-markdown-details>`.

### Phase 7: Convert todo.xml to todo.json

Run:

```bash
$spex_skill_dir/scripts/spex todo xml2json --rm $topic_path/todo.xml
```

If the script exits with an error, read the error message, fix the XML
format in `todo.xml`, and re-run until conversion succeeds.

### Phase 8: Output

Display the following summary to the user:

```text
**Topic**: `$topic_name`

- Spec: `$topic_path/spec.md`
- Todo: `$topic_path/todo.json`
- Meta: `$topic_path/meta.json`
```
