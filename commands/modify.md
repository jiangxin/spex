# spex modify

Modify an existing specification's requirements and regenerate the
development plan.

## Usage

```text
/spex modify [topic_name] [prompt]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Resolve Topic

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

### Phase 2: Understand Context and Clarify

If `$prompt` is not provided or empty, ask the user to describe what
changes they want to make to the spec. The user's full input becomes
`$prompt`.

Read the current specification at `$topic_path/spec.md` to understand
the existing requirements and design. Then explore the workspace **only
enough to understand where the relevant code lives and what existing
patterns are referenced in the spec**. Do NOT dig into full
implementation details or start modifying any files.

The user's `$prompt` is a modification or addition to the existing
specification. Evaluate whether it is clear enough to proceed:

**When to clarify** — ask the user if any of these apply:

- The scope of the change is unclear (e.g., which sections of the spec
  are affected, whether existing steps should be replaced or extended).
- Multiple viable implementation paths exist and the choice affects the
  design.
- The relationship to completed work is not obvious (e.g., whether to
  preserve or redo completed steps).
- Ambiguous terminology is used that could be interpreted differently
  in the context of the existing specification.

**When NOT to clarify** — if the modification request is already specific
and unambiguous in the context of the current spec, skip clarification
entirely and proceed directly to Phase 3. Do not ask questions just to
be thorough; only ask when the answer would materially change the spec.

**How to clarify**:

- Ask all clarification questions at once in a single message (not one
  by one in a back-and-forth).
- Limit to 2–3 questions maximum. Prioritize the questions whose answers
  most affect the design.

After clarification (or if none was needed), the finalized `$prompt`
becomes the modification request.

### Phase 3: Build Prompt

Run:

```bash
$spex_skill_dir/scripts/spex meta $topic_name prompts "$prompt"
```

Then run:

```bash
echo "$prompt" | $spex_skill_dir/scripts/spex prompt modify-spec \
  --json --topic $topic_name --stdin --remove-undone
```

Parse the JSON output from stdout:

- If the command exits with a non-zero exit code, report the stderr
  message and stop.
- Otherwise, save `$modify_prompt` from the `"prompt"` field.

The `--remove-undone` flag removes incomplete steps from `todo.json`
before rendering, so the prompt only includes completed step context.

### Phase 4: Modify spec.md

Check if `$prompt` or the conversation context includes local image
file paths (extensions: `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`,
`.bmp`). If image files are found:

1. Create the assets directory: `mkdir -p $topic_path/assets/`
2. Copy each image file into `$topic_path/assets/`, keeping the original
   filename.
3. When updating `spec.md` below, reference the images using Markdown
   syntax `![description](assets/filename.png)` in the appropriate
   sections.
4. After updating `spec.md`, register the images in `meta.json` by
   running:

   ```bash
   $spex_skill_dir/scripts/spex meta $topic_name prompts \
     --add-images assets/file1.png assets/file2.png
   ```

Using `$modify_prompt` as the prompt, update `$topic_path/spec.md`
according to the instructions rendered in the prompt.

### Phase 5: Build Todo Prompt

Run:

```bash
$spex_skill_dir/scripts/spex prompt modify-todo --json --topic $topic_name
```

Parse the JSON output from stdout:

- If the command exits with a non-zero exit code, report the stderr
  message and stop.
- Otherwise, save `$todo_prompt` from the `"prompt"` field.

### Phase 6: Regenerate Development Steps

Using `$todo_prompt` as the prompt, add new development steps to
`todo.json` via `spex todo-helper` commands (`append`, `edit`, `remove`,
`show`) as described in the rendered prompt.

### Phase 7: Post-Action

Run:

```bash
$spex_skill_dir/scripts/spex create-helper post-action \
  --topic $topic_name --event-type modify
```

If the script exits with an error, report the error and stop.

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
project files, or begin implementing the updated plan.**

The `/spex modify` command's sole responsibility was to update the spec
documents. Implementation is handled by `/spex apply` or
`/spex apply-one-step`. Wait for the user to review the updated spec and
invoke those commands when ready.
