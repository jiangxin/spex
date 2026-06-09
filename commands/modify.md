# spex modify

Modify an existing specification's requirements and regenerate the
development plan.

## Usage

```text
/spex modify [topic_name] [request]
```

## Procedure

- **Role**: Act as a senior software architect. Focus on incremental
  specification evolution while preserving completed work.

**SCOPE: This command updates spec documents only — `spec.md`,
`todo.json`, `meta.json` inside the topic directory. NO application
code is written. NO existing project files are modified.
Implementation is handled by `/spex apply` or `/spex apply-one-step`.**

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

If `$request` is not provided or empty, ask the user to describe what
changes they want to make to the spec. The user's full input becomes
`$request`.

Read the current specification at `$topic_path/spec.md` to understand
the existing requirements and design. Then explore the workspace **only
enough to understand where the relevant code lives and what existing
patterns are referenced in the spec**. Do NOT dig into full
implementation details or start modifying any files.

The user's `$request` is a modification or addition to the existing
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
- Limit to 2–4 questions maximum. Prioritize the questions whose answers
  most affect the design.

After clarification (or if none was needed), the finalized `$request`
becomes the modification request.

### Phase 3: Save Request

Record the modification request in `meta.json`:

```bash
$spex_skill_dir/scripts/spex meta-helper $topic_name prompts --stdin <<'EOF'
$request
EOF
```

Check for images from either of the following sources (supported
extensions: `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.bmp`):

- **Pasted images (primary)**: Scan the conversation context for
  `[Image: source: <path>]` markers. These are images the user pasted
  into the chat, cached at `.claude/image-cache/<uuid>/<n>.png`.
  Extract the absolute file path from each marker.
- **Explicit file paths (secondary)**: Check if `$request` text
  contains local image file paths with a supported extension.

If images are found from either source:

1. Create the assets directory: `mkdir -p $topic_path/assets/`
2. Copy each discovered image file into `$topic_path/assets/`, keeping
   the original filename.
3. Register the images in `meta.json` (example):

   ```bash
   $spex_skill_dir/scripts/spex meta-helper $topic_name prompts \
     --add-images assets/file1.png assets/file2.png
   ```

4. When updating `spec.md` in Phase 5, reference the images using
   Markdown syntax `![description](assets/filename.png)` in the
   appropriate sections.

### Phase 4: Build Prompt

Run:

```bash
$spex_skill_dir/scripts/spex prompt modify-spec \
  --json --topic $topic_name --stdin --remove-undone <<'EOF'
$request
EOF
```

Parse the JSON output from stdout:

- If the command exits with a non-zero exit code, report the stderr
  message and stop.
- Otherwise, save `$modify_prompt` from the `"prompt"` field.

The `--remove-undone` flag removes incomplete steps from `todo.json`
before rendering, so the prompt only includes completed step context.

### Phase 5: Modify spec.md

Using `$modify_prompt` as the prompt, update `$topic_path/spec.md`
according to the instructions rendered in the prompt.

Before writing, review the current codebase structure to ensure the
updated design integrates properly with existing code.

### Phase 6: Build Todo Prompt

Run:

```bash
$spex_skill_dir/scripts/spex prompt modify-todo --json --topic $topic_name
```

Parse the JSON output from stdout:

- If the command exits with a non-zero exit code, report the stderr
  message and stop.
- Otherwise, save `$todo_prompt` from the `"prompt"` field.

### Phase 7: Regenerate Development Steps

Using `$todo_prompt` as the prompt, follow its instructions to design
and add new development steps to `todo.json` via `spex todo-helper`.
The prompt already contains the command syntax, planning principles,
and step numbering rules.

### Phase 8: Post-Action

Run:

```bash
$spex_skill_dir/scripts/spex create-helper post-action \
  --topic $topic_name --event-type modify
```

If the script exits with an error, report the error and stop.

### Phase 9: Output

Display the following summary to the user:

```text
**Topic**: `$topic_name`

- Spec: `$topic_path/spec.md`
- Todo: `$topic_path/todo.json`
- Meta: `$topic_path/meta.json`
```

### Phase 10: STOP — Do NOT Implement

**This is a hard stop. Do NOT write any application code, modify any
project files, or begin implementing the updated plan.**

The `/spex modify` command's sole responsibility was to update the spec
documents. Implementation is handled by `/spex apply` or
`/spex apply-one-step`. Wait for the user to review the updated spec and
invoke those commands when ready.
