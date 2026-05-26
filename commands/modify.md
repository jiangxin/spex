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
$spex_skill_dir/scripts/spex get-topic --json "$topic_name"
```

Read the command output and parse it as a JSON array:

- If the array contains a single element, set `$topic` to its
  `topic_name` and `$topic_path` to its `topic_path`.
- If the array contains multiple elements, present a numbered list of
  `topic_name` values to the user and ask them to choose. Set `$topic`
  and `$topic_path` from the selected entry.
- If the script exits with an error, report the error and stop.

### Step 3: Build Prompt

Run:

```bash
echo "$prompt" | $spex_skill_dir/scripts/spex prompt modify-spec --json --topic $topic --stdin
```

Parse the JSON output from stdout:

- If the command exits with a non-zero exit code, report the stderr
  message and stop.
- Otherwise, save `$modify_prompt` from the `"prompt"` field.

### Step 4: Modify spec.md

Using `$modify_prompt` as the prompt, update `$topic_path/spec.md`
according to the instructions rendered in the prompt.

### Step 5: Generate todo.json

Regenerate `$topic_path/todo.json` by first producing `todo.xml` via a
prompt, then converting it:

1. Run:

   ```bash
   $spex_skill_dir/scripts/spex prompt modify-todo --topic $topic
   ```

   This command internally:
   - Removes incomplete steps from `todo.json` (preserving completed ones)
   - Updates `todo.xml` to reflect only completed steps
   - Renders a prompt with the updated spec and completed steps context

2. Use the rendered prompt as context to write new `todo.xml`, appending
   development steps after any preserved completed ones. Follow these rules:
   - **Preserve completed steps**: Keep all completed items unchanged at the
     start of the list.
   - **Corrective steps**: If completed step implementations conflict with
     the new spec, add corrective steps after them (do NOT modify existing
     completed step descriptions).
   - **Add new steps**: Append remaining development steps needed.
   - **Discard old incomplete steps**: Do NOT carry forward previously
     incomplete steps from the old `todo.json`.

3. Run:

   ```bash
   $spex_skill_dir/scripts/spex todo xml2json $topic_path/todo.xml
   ```

   If the script exits with an error, read the error message, fix the XML
   format in `todo.xml`, and re-run until conversion succeeds.

### Step 6: Validate todo.json

Run:

```bash
$spex_skill_dir/scripts/spex todo validate $topic_path/todo.json
```

If the script exits with an error, read the error message, fix the JSON
format in `todo.json`, and re-run until validation passes.

### Step 7: Output

Display the following summary to the user:

```text
**Topic**: `$topic`

- Spec: `$topic_path/spec.md`
- Todo: `$topic_path/todo.json`
```
