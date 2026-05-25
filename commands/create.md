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

### Step 1: Clarify Requirement

If `$input` is not provided or empty, ask the user to describe the requirement.

Once you have `$input`, explore the workspace to understand the current
codebase context. Identify any ambiguities, contradictions, or cases where
multiple implementation approaches exist. Ask the user to clarify these
points before proceeding.

After clarification, record the complete, unambiguous requirement as
`$requirement`.

### Step 2: Generate Topic Name

Based on `$requirement`, generate a short English name (<32 bytes) using only
`[a-z0-9-]`, replacing spaces with `-`. The result is `$topic`
(e.g., `add-login-api`). Do NOT prepend any date prefix.

### Step 3: Prepare Topic Directory

Run:

```bash
echo "$requirement" | $spex_skill_path/scripts/spex create-topic --json $topic
```

The script creates the topic directory and `meta.json` (with the
requirement saved to its `prompts` field). Parse the JSON output. The
`topic_name` field is `$topic` prefixed with a date stamp in
`YYYY-MM-DD-HH-mm` format (e.g., `2026-05-24-10-30-add-login-api`).
Save `topic_name` as `$topic_name` and `topic_path` as `$topic_path`.
If the script exits with an error, return to Step 2 and retry with a
different name.

Example JSON output:

```json
{
  "topic_name": "2026-05-24-10-30-add-login-api",
  "topic_path": "/path/to/.specs/specs/2026-05-24-10-30-add-login-api"
}
```

### Step 4: Get Spec Template

Run:

```bash
$spex_skill_path/scripts/spex get --spec-template
```

Save the output as `$template_content`.

### Step 5: Design Specification

Perform detailed requirement analysis and solution design based on
`$requirement`. Consider functional requirements, non-functional requirements,
data models, API contracts, error handling, and edge cases.

Using `$template_content` as the template, create `$topic_path/spec.md`
in the same language as the user's requirement (e.g., English or Chinese).
Replace the placeholder sections (text enclosed in angle brackets or square
brackets) with the analysis and design results. Fill the "User
Clarification" section with clarifications gathered in Step 1. Keep the
Constraints section as-is.

### Step 6: Plan Implementation Steps

Based on the design in `$topic_path/spec.md`, break down the work into
incremental development steps. Each step should be independently
committable and verifiable.

Principles:

- **Small batches**: each step delivers a minimal, working increment.
- **Self-contained**: group production code and its tests in the same
  step — never split them into separate steps.
- **Ordered by dependency**: list steps so that each builds on the
  previous one; no forward references.

Create `$topic_path/todo.json` listing each step in order:

```json
[
  {
    "id": "<step-id>",
    "name": "<step-name>",
    "details": "<detailed description in markdown without headings>",
    "completed_at": "",
    "commit_title": ""
  }
]
```

- `details`: a markdown-formatted description of what this step does,
  including file changes, logic, and acceptance criteria. Do not use
  headings (`#`, `##`, etc.) inside the value — use lists, bold, and
  inline code instead.
- All steps start with `completed_at: ""` and an empty `commit_title`.
  These fields are updated later when each step is implemented.

### Step 7: Validate todo.json

Run:

```bash
$spex_skill_path/scripts/spex todo validate $topic_path/todo.json
```

If the script exits with an error, read the error message, fix the JSON
format in `todo.json`, and re-run until validation passes.

### Step 8: Output

Display the following summary to the user:

```text
**Topic**: `$topic_name`

- Spec: `$topic_path/spec.md`
- Todo: `$topic_path/todo.json`
- Meta: `$topic_path/meta.json`
```
