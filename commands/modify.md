# sdd modify

Modify an existing specification's requirements and regenerate the
development plan.

## Usage

```text
/sdd modify [topic_name] [prompt]
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
python <skill-path>/scripts/get_topic.py "$topic_name"
```

Read the command output to determine `$topic`:

- If the output is a single line matching `YYYY-MM-DD-<name>`, set `$topic`
  to that value.
- If the output contains multiple lines, present a numbered list to the
  user and ask them to choose. Set `$topic` to the selected name.
- If the script exits with an error, report the error and stop.

### Step 3: Log Modification Prompt

Run:

```bash
echo "$prompt" | python <skill-path>/scripts/topic-log.py $topic
```

### Step 4: Build Context

Read the following as context for the modification:

- Full contents of `$spec_root/specs/$topic/spec.md` (the existing spec).
- From `$spec_root/specs/$topic/todo.json`, extract all items where
  `completed_at` is not empty. These are the completed steps — their `id`,
  `name`, `details`, `completed_at`, and `commit_title` fields provide
  context on what has already been implemented.

### Step 5: Modify spec.md

Based on the existing spec and the user's modification prompt, update
`$spec_root/specs/$topic/spec.md`:

- Update the **Requirement** section to reflect the new/changed
  requirements.
- Update the **Detailed Design** section accordingly.
- Update the **Test Plan** section accordingly.
- Use the same language as the user's prompt.

Before writing, analyze the current repository structure, architecture,
and existing code to ensure the updated design integrates properly.

### Step 6: Generate todo.json

Based on the updated spec, regenerate `$spec_root/specs/$topic/todo.json`:

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
python <skill-path>/scripts/parse_todo.py validate $spec_root/specs/$topic/todo.json
```

If the script exits with an error, read the error message, fix the JSON
format in `todo.json`, and re-run until validation passes.
