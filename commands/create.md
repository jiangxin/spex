# spex create

Create a new specification topic with requirement analysis, detailed design,
and test plan.

## Usage

```text
/spex create [prompt]
```

## Procedure

Execute this procedure in a dedicated sub-agent to keep the main context clean.
Follow these steps in order. Do not skip or reorder.

### Step 1: Collect Prompt

If `$prompt` is not provided or empty, ask the user to describe the
requirement. The user's full input becomes `$prompt`.

### Step 2: Generate Topic Name

Based on `$prompt`, generate a short English name (<32 bytes) using only
`[a-z0-9-]`, replacing spaces with `-`. The result is `$topic`
(e.g., `add-login-api`). Do NOT prepend any date prefix.

### Step 3: Create Topic

Run:

```bash
echo "$prompt" | $spex_skill_path/scripts/spex create-topic --json $topic
```

Parse the JSON output. The `topic_name` field is the `$topic` parameter
prefixed with a date stamp in `YYYY-MM-DD-HH-mm` format (e.g., if
`$topic` is `add-login-api`, the `topic_name` becomes
`2026-05-24-10-30-add-login-api`). Save `topic_name` as `$topic_name`
and `topic_path` as `$topic_path`. If the script exits with an error,
return to Step 2 and retry with a different name.

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

The command will output the template path to stdout:

- If user has `<spec_root>/templates/spec.md`, use that custom template
- Otherwise, use the built-in template from `$spex_skill_path/templates/spec.md`

Save the output as `$template_path`.

### Step 5: Create spec.md

Read the template file at `$template_path` and create `$topic_path/spec.md`
using the same language as the user's prompt (e.g., English or Chinese).

Replace the placeholder sections in the template with actual content based
on `$prompt`:

- `<Requirement analysis based on the user's original prompt>` → Actual requirement analysis
- `<Clarifications from the user on ambiguous requirements>` → User clarifications
- `<Detailed design based on analysis...>` → Actual detailed design
- `<Detailed test plan based on the design above>` → Actual test plan

Keep the Constraints section as-is from the template.

### Step 6: Generate todo.json

Break down the work into development steps following DRY, KISS, Small
Batches, Commit Often, and Test Often.

- Group implementation code and its associated test cases in the same
  step — do not split them into separate steps. Each step should be a
  self-contained unit that includes both production code and its tests.

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
- After a step is fully implemented and committed, set `completed_at` to
  the current local timestamp with timezone offset (ISO 8601, e.g.
  `2026-05-20T22:30:00+08:00`) and fill `commit_title` with the actual
  commit title.

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
