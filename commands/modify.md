# spex modify

Modify an existing specification's requirements and regenerate the
development plan.

## Usage

```text
/spex modify [topic_name] [prompt]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Step 1: Collect Prompt

If `$prompt` is not provided or empty, ask the user to describe what
changes they want to make to the spec. The user's full input becomes
`$prompt`.

### Step 2: Resolve Topic

Run:

```bash
<skill-path>/scripts/spex get-topic --json "$topic_name"
```

Read the command output:

- If the output is a single JSON line, parse it and set `$topic` to
  `topic_name` and `$topic_path` to `topic_path`.
- If the output contains multiple JSON lines, present a numbered list of
  `topic_name` values to the user and ask them to choose. Set `$topic`
  and `$topic_path` from the selected entry.
- If the script exits with an error, report the error and stop.

### Step 3: Log Modification Prompt

1. Read `$topic_path/meta.json`.
2. Append `$prompt` to the `prompts` array.
3. Write the updated JSON back to `$topic_path/meta.json`.

### Step 4: Build Context

Read the following as context for the modification:

- Full contents of `$topic_path/spec.md` (the existing spec).
- From `$topic_path/todo.json`, extract all items where
  `completed_at` is not empty. These are the completed steps — their `id`,
  `name`, `details`, `completed_at`, and `commit_title` fields provide
  context on what has already been implemented.

### Step 5: Modify spec.md

Based on the existing spec and the user's modification prompt, update
`$topic_path/spec.md`:

- Update the **Requirement** section to reflect the new/changed
  requirements.
- Update the **Detailed Design** section accordingly.
- Update the **Test Plan** section accordingly.
- Use the same language as the user's prompt.

Before writing, analyze the current repository structure, architecture,
and existing code to ensure the updated design integrates properly.

### Step 6: Generate todo.json

Based on the updated spec, regenerate `$topic_path/todo.json`:

- **Preserve completed steps**: Keep all items with non-empty
  `completed_at` unchanged, in their original order, at the start of the
  list.
- **Fix conflicts**: If any completed step's implementation conflicts with
  the new requirements, add a new step after the completed steps to fix
  the conflict.
- **Discard incomplete steps**: Remove all items with empty `completed_at`
  from the old todo.json.
- **Add new steps**: Based on the updated spec, add remaining development
  steps needed to fulfill the new requirements.
- **Overwrite**: Write the new list to `todo.json`, replacing its previous
  contents entirely.

Follow the same format and rules as the create command:

- Group implementation code and its associated test cases in the same
  step.
- Each step should be a self-contained unit (DRY, KISS, Small Batches).
- Use the standard todo.json item format with `id`, `name`, `details`,
  `completed_at`, and `commit_title` fields.

### Step 7: Validate todo.json

Run:

```bash
<skill-path>/scripts/spex todo validate $topic_path/todo.json
```

If the script exits with an error, read the error message, fix the JSON
format in `todo.json`, and re-run until validation passes.

### Step 8: Output

Display the following summary to the user:

```text
**Topic**: `$topic`

- Spec: `$topic_path/spec.md`
- Todo: `$topic_path/todo.json`
```
