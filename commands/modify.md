# spex modify

Modify an existing specification's requirements and regenerate the
development plan.

## Usage

```text
/spex modify [topic_name] [prompt]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Collect Prompt

If `$prompt` is not provided or empty, ask the user to describe what
changes they want to make to the spec. The user's full input becomes
`$prompt`.

### Phase 2: Resolve Topic

Run:

```bash
$spex_skill_dir/scripts/spex get-topic --json "$topic_name"
```

Read the command output and parse it as a JSON array:

- If the array contains a single element, set `$topic_name` to its
  `topic_name` and `$topic_path` to its `topic_path`.
- If the array contains multiple elements, present a numbered list of
  `topic_name` values to the user and ask them to choose. Set `$topic_name`
  and `$topic_path` from the selected entry.
- If the script exits with an error, report the error and stop.

### Phase 3: Build Prompt

Run:

```bash
echo "$prompt" | $spex_skill_dir/scripts/spex prompt modify-spec --json --topic $topic_name --stdin
```

Parse the JSON output from stdout:

- If the command exits with a non-zero exit code, report the stderr
  message and stop.
- Otherwise, save `$modify_prompt` from the `"prompt"` field.

### Phase 4: Modify spec.md

Using `$modify_prompt` as the prompt, update `$topic_path/spec.md`
according to the instructions rendered in the prompt.

### Phase 5: Generate todo.xml

Run:

```bash
$spex_skill_dir/scripts/spex prompt modify-todo --json --topic $topic_name
```

This command renders a JSON output with the `"prompt"` field.

Parse the JSON output from stdout:

- If the command exits with a non-zero exit code, report the stderr
  message and stop.
- Otherwise, save `$todo_prompt` from the `"prompt"` field.

Using `$todo_prompt` as the prompt, create or overwrite `$topic_path/todo.xml`.

### Phase 6: Convert todo.xml to todo.json

Run:

```bash
$spex_skill_dir/scripts/spex todo xml2json --append --rm $topic_path/todo.xml
```

This converts `todo.xml` to JSON and appends the new steps to the
existing `todo.json`, preserving completed steps. If the script exits
with an error, read the error message, fix the XML format in
`todo.xml`, and re-run until conversion succeeds.

### Phase 7: Output

Display the following summary to the user:

```text
**Topic**: `$topic_name`

- Spec: `$topic_path/spec.md`
- Todo: `$topic_path/todo.json`
- Meta: `$topic_path/meta.json`
```

### Phase 8: STOP — Do NOT Implement

**This is a hard stop. Do NOT write any application code, modify any
project files, or begin implementing the updated plan.**

The `/spex modify` command's sole responsibility was to update the spec
documents. Implementation is handled by `/spex apply` or
`/spex apply-one-step`. Wait for the user to review the updated spec and
invoke those commands when ready.
