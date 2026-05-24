# spex create

Create a new specification topic with requirement analysis, detailed design,
and test plan.

## Usage

```text
/spex create [prompt]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Step 1: Collect Prompt

If `$prompt` is not provided or empty, ask the user to describe the
requirement. The user's full input becomes `$prompt`.

### Step 2: Generate Topic Name

Based on `$prompt`, generate a topic name:

- Compose a short English name (<32 bytes) using only `[a-z0-9-]`,
  replacing spaces with `-`.
- Prepend the current local date and time as `YYYY-MM-DD-HH-MM`.
- The result is `$topic` (e.g., `2026-05-20-14-30-add-login-api`).

### Step 3: Create Topic Directory

Run:

```bash
<skill-path>/scripts/spex create-topic $topic
```

If the script exits with an error (e.g., topic already exists or invalid
name), return to Step 2 and retry with a different name.

### Step 4: Log Original Prompt

Run:

```bash
echo "$prompt" | <skill-path>/scripts/spex write-log $topic
```

This records the user's original prompt via stdin.

### Step 5: Generate meta.json

Collect workspace metadata and write it to
`$spec_root/specs/$topic/meta.json`.

Gather the following values by running shell commands:

- `workdir`: run `git rev-parse --show-toplevel`
- `remote_url`: run `git remote get-url origin` (use empty string
  if the command fails)
- `branch`: run `git branch --show-current`
- `user_name`: run `git config user.name`
- `user_email`: run `git config user.email`
- `created_at`: current local timestamp in ISO 8601 with timezone
  offset (e.g., `2026-05-24T20:00:00+08:00`)

Write the file in JSON format:

```json
{
  "workdir": "<value>",
  "remote_url": "<value>",
  "branch": "<value>",
  "user_name": "<value>",
  "user_email": "<value>",
  "created_at": "<value>"
}
```

### Step 6: Create spec.md

Create the file `$spec_root/specs/$topic/spec.md` using the same language as the
user's prompt (e.g., English or Chinese). Use the following template:

```markdown
# Requirement

<Requirement analysis based on the user's original prompt>

# User Clarification

<Clarifications from the user on ambiguous requirements>

# Constraints

- DRY — Don't Repeat Yourself: analyze existing architecture and code,
  reuse what exists, **never** generate duplicate code.
- KISS — Keep It Simple, Stupid: no over-engineering; keep it simple while
  considering performance and security.
- Single Responsibility: each function/method does one thing; consider
  splitting if it exceeds 30 lines.
- Small Batches: break development into atomic tasks so each step is under
  200 lines of code, easy to review, cherry-pick, and revert.
- Commit Often: create a commit after each development task; follow the
  Conventional Commits format; wrap commit messages at 72 characters.
- Test Often: run lint and unit tests after each step; proceed only when
  all checks pass.

# Detailed Design

<Detailed design based on analysis of the current repository architecture
and codebase>

# Test Plan

<Detailed test plan based on the design above>
```

Before writing the Requirement, Detailed Design, and Test Plan sections,
analyze the current repository structure, architecture, and existing code
to ensure the design integrates properly.

For the User Clarification section, ask the user to clarify any ambiguities
discovered during requirement analysis. If nothing is ambiguous, leave the
section empty.

### Step 7: Generate todo.json

Break down the work into development steps following DRY, KISS, Small
Batches, Commit Often, and Test Often.

- Group implementation code and its associated test cases in the same
  step — do not split them into separate steps. Each step should be a
  self-contained unit that includes both production code and its tests.

Create `$spec_root/specs/$topic/todo.json` listing each step in order:

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

### Step 8: Validate todo.json

Run:

```bash
<skill-path>/scripts/spex todo validate $spec_root/specs/$topic/todo.json
```

If the script exits with an error, read the error message, fix the JSON
format in `todo.json`, and re-run until validation passes.

### Step 9: Output

Display the following summary to the user:

```text
**Topic**: `$topic`

- Spec: `$spec_root/specs/$topic/spec.md`
- Todo: `$spec_root/specs/$topic/todo.json`
- Meta: `$spec_root/specs/$topic/meta.json`
```
