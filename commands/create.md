# spex create

**PLAN only** — this command produces spec documents and a todo list.
It does NOT write any application code.

Create a new spec with requirement analysis, detailed design,
and test plan.

## Usage

```text
/spex create [input]
```

## Procedure

- **Role**: Act as a senior software architect. Focus on requirement
  completeness, edge cases, and testability.

**SCOPE: This command creates documents only — `spec.md`, `todo.json`,
`meta.json` inside the spec directory. NO application code is written.
NO existing project files are modified. Implementation happens later
via `/spex apply` or `/spex apply-one-step`.**

Follow these steps in order. Do not skip or reorder.

### Phase 1: Validate Branch

Run:

```bash
$spex_skill_dir/scripts/spex create-helper precheck
```

If the script exits with an error (non-zero), the error message is already
printed to stderr. Stop execution. On success, continue to the next phase.

### Phase 2: Clarify Requirement

If `$input` is not provided or empty, ask the user to describe the requirement.

Once you have `$input`, explore the workspace **only enough to understand
where the relevant code lives and what existing patterns to reference in the
spec**. Limit exploration to identifying: (1) relevant source files and
their location, (2) existing patterns or conventions the spec should
reference, (3) dependencies the requirement touches. Do NOT read full
file contents unless necessary for the spec, dig into implementation
details, or start modifying any files (those are handled by `/spex apply`).

**When to clarify** — ask the user if any of these apply:

- Multiple viable implementation paths exist and the choice affects the
  design (e.g., REST vs. GraphQL, polling vs. WebSocket).
- Scope or boundaries are unclear (e.g., which modules are in/out,
  whether backward compatibility is required).
- Dependencies on other systems or features are not specified.
- Ambiguous terminology is used that could be interpreted differently.

**When NOT to clarify** — if the requirement is already specific and
unambiguous, skip clarification entirely and proceed directly to Phase 3.
Do not ask questions just to be thorough; only ask when the answer would
materially change the spec.

**How to clarify**:

- Ask all clarification questions at once in a single message (not one
  by one in a back-and-forth).
- Limit to 2–4 questions maximum. Prioritize the questions whose answers
  most affect the design.

After clarification (or if none was needed), record the complete,
unambiguous requirement as `$requirement`.

### Phase 3: Generate Name and Description

Based on `$requirement`, generate a JSON object with two fields:

- `name`: a short English name (<32 bytes) using only `[a-z0-9-]`,
  replacing spaces with `-`. Do NOT prepend any date prefix.
- `description`: a brief English summary of the requirement, used as
  merge commit message and PR description. Keep it as a single line
  (do NOT embed newlines) — line wrapping is handled automatically.

Example: `{"name": "add-login-api", "description": "Add user login API with JWT authentication"}`

Parse this JSON and save the values as `$name` and `$description`.

### Phase 4: Prepare Spec Directory

Run:

```bash
$spex_skill_dir/scripts/spex create-helper prepare-spec --description "$description" --name "$name" <<'EOF'
$requirement
EOF
```

The script creates the spec directory and `meta.json` (with the
requirement saved to its `prompts` field and the description saved to
its `description` field). Parse the JSON output and
save these variables:

- `$spec_name` ← `spec_name` (spec with date prefix,
  e.g., `2026-05-24-10-30-add-login-api`)
- `$spec_path` ← `spec_path`
- `$spec_template` ← `spec_template`

If the script exits with an error, return to Phase 3 and retry with a
different name.

Example JSON output:

```json
{
  "spec_name": "2026-05-24-10-30-add-login-api",
  "spec_path": "/path/to/.spex/specs/2026-05-24-10-30-add-login-api",
  "spec_template": "# [Title]\n..."
}
```

### Phase 5: Design Specification

Check for images from either of the following sources (supported
extensions: `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.bmp`):

- **Pasted images (primary)**: Scan the conversation context for
  `[Image: source: <path>]` markers. These are images the user pasted
  into the chat, cached at `.claude/image-cache/<uuid>/<n>.png`.
  Extract the absolute file path from each marker.
- **Explicit file paths (secondary)**: Check if `$requirement` text
  contains local image file paths with a supported extension.

If images are found from either source:

1. Create the assets directory: `mkdir -p $spec_path/assets/`
2. Copy each discovered image file into `$spec_path/assets/`, keeping
   the original filename.
3. When writing `spec.md` below, reference the images using Markdown
   syntax `![description](assets/filename.png)` in the appropriate
   sections.
4. After writing `spec.md`, register the images in `meta.json`
   (example):

   ```bash
   $spex_skill_dir/scripts/spex meta-helper $spec_name prompts \
     --add-images assets/file1.png assets/file2.png
   ```

Perform detailed requirement analysis and solution design based on
`$requirement`. Consider functional requirements, non-functional requirements,
data models, API contracts, error handling, and edge cases.

Using `$spec_template` as the template, create `$spec_path/spec.md`
in the same language as the user's requirement (e.g., English or Chinese).
Replace the placeholder sections (HTML comments like
`<!-- Replace this section with ... -->`) with the analysis and design
results. Fill the "User Clarification" section with clarifications
gathered in Phase 2. Keep the Constraints section as-is.
Do not remove or modify `<!-- spex:begin:* -->` comment lines.

### Phase 6: Plan Implementation Steps

Based on the design in `$spec_path/spec.md`, break down the work into
incremental development steps. Each step should be independently
committable and verifiable.

Principles:

- **Small batches**: each step delivers a minimal, working increment.
- **Self-contained**: group production code and its tests in the same
  step — never split them into separate steps.
- **Ordered by dependency**: list steps so that each builds on the
  previous one; no forward references.

Use `spex todo-helper` to build `todo.json` step by step.
Number steps sequentially: `step-1`, `step-2`, etc.

**Append** a step — use `--details-from-stdin` with a heredoc for
multi-line Markdown details:

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name append \
  --id step-1 --name "Short name" --details-from-stdin <<'DETAILS'
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

- Create `src/auth.py` with login endpoint
- Add input validation for email and password
- Write unit tests in `tests/test_auth.py`

**Acceptance criteria**: all tests pass, endpoint returns JWT
DETAILS
```

**Show** current steps (to review before adding more):

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name show \
  --format markdown
```

**Edit** a step (only specified fields are updated):

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id step-1 --details-from-stdin <<'DETAILS'
Updated multi-line details for this step.

- Revised implementation approach
- Added error handling requirements
DETAILS
```

**Remove** a step:

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name remove \
  --id step-1
```

The `details` field supports multi-line Markdown:

- Including file changes, logic, and acceptance criteria, etc.
- Use lists, bold, and inline code.
- Do not use headings (`#`, `##`, etc.)

### Phase 7: Post-Action

Run:

```bash
$spex_skill_dir/scripts/spex create-helper post-action --name $spec_name
```

If the script exits with an error, read the error message, fix the
JSON format in `todo.json`, and re-run until validation succeeds.

### Phase 8: Output

Display the following summary to the user:

```text
**Spec**: `$spec_name`

- Spec: `$spec_path/spec.md`
- Todo: `$spec_path/todo.json`
- Meta: `$spec_path/meta.json`
```

### Phase 9: STOP — Do NOT Implement

**This is a hard stop. Do NOT write any application code, modify any
project files, or begin implementing the steps planned in `todo.json`.**

Planning is complete. The `/spex create` command's sole responsibility
was to produce the spec documents (`spec.md`, `todo.json`, `meta.json`)
inside the spec directory.

Wait for the user to review the spec and invoke `/spex apply` or
`/spex apply-one-step` when ready.
