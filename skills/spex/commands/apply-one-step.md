# spex apply-one-step

Apply a single step from a specification's todo list.

## Usage

```text
/spex apply-one-step [spec_name]
```

## Inputs

- OPT: `$spec_name`

## Preconditions

- Follow phases in order. Do not skip or reorder.
- Exactly one step then STOP

## Execution

### Phase 1: Resolve Spec

- CMD:

```bash
$spex_skill_dir/scripts/spex list --json --must-undone "$spec_name"
```

- Parse stdout as JSON array:
  - IF single element -> set `$spec_name` / `$spec_path` from entry
  - IF multiple -> numbered `spec_name` list -> user chooses -> set
    `$spec_name` / `$spec_path` from selected entry
  - IF script exits error -> report error -> STOP

### Phase 2: Validate Branch

- CMD:

```bash
$spex_skill_dir/scripts/spex apply-helper precheck --name $spec_name
```

- IF non-zero exit -> error already on stderr -> STOP
- ELSE -> continue
- Bind `$spex_root`:

```bash
$spex_skill_dir/scripts/spex config
```

  - `$spex_root` ← **Paths** section `spex_root` (absolute path
    only). Do **not** use Config section's relative `spex_root`
  - Reuse for dirty filter + commit staging exclude

### Phase 3: Build Prompt / Resume Gate

- CMD:

```bash
$spex_skill_dir/scripts/spex prompt apply-one-task --json --name $spec_name
```

- Parse JSON stdout:
  - IF `"all_done": true` -> report completion -> run post-action
    (covers last step finished but Phase 8 interrupted) and
    **STOP**:

    ```bash
    $spex_skill_dir/scripts/spex apply-helper post-action --name $spec_name
    ```

    Display output to user. Do not implement further steps
  - IF non-zero exit -> report stderr -> STOP
  - ELSE save:
    - `$prompt` ← `"prompt"`
    - `$current_task_id` ← `"task_id"`
    - `$resume_phase` ← `"resume_phase"` (`implement` or `review`)
    - `$commit_title` ← `"commit_title"` (may be empty)
    - `$skip_commit` ← `"skip_commit"` (`false` | `auto` | `true`;
      missing → `false`)

- **Single render:** Call `prompt apply-one-task` **once** per task
  iteration. Reuse `$prompt` for Phase 4. Do **not** re-run unless
  `$prompt` was lost (e.g. new session).

- Step incomplete until `completed_at` set. IF `commit_title` set
  AND `completed_at` empty -> `$resume_phase` is `review` (skip
  implement/commit)

- **Route:**
  - IF `$resume_phase` is `review` -> `$did_commit` ← `true`
    (commit already happened; durable: non-empty `commit_title`
    + empty `completed_at`); skip Phases 4–5 -> Phase 6.
    Do NOT set `$commit_sha` from `HEAD` here — Phase 6
    **6-entry** resolves it (prefer review file's `commit_sha`)
  - IF `$resume_phase` is `implement` -> Phase 4 (then Phase 5
    only when `$skip_commit` requires a commit; after Phases 4–5,
    IF `$did_commit` -> Phase 6; ELSE -> Phase 7). Phase 4
    intentional STOP (`false`+clean, `true`+dirty) ends the
    command — do **not** Phase 7 (`completed_at` stays unset).
    Only Phase 4 skip arms (`$did_commit=false`) continue to
    Phase 7

### Phase 4: Execute Task

- Using `$prompt` as guide (from Phase 3 — do **not** re-run
  `prompt apply-one-task`), implement current task. Follow rendered
  prompt precisely (spec, completed steps, task description,
  guidelines)
- Deliver production code + tests together when the step changes
  code; docs-only / no-op steps may leave the tree clean
- Do NOT create git commit here — Phase 5 handles commit when
  required
- `$dirty` = **whole working tree** after implementation (not
  this-step delta). Pre-existing dirty paths outside `$spex_root`
  count. Prefer a clean tree before `skip_commit=true`
- Compute `$dirty`:
  1. `git status --porcelain`
  2. Each line: path(s) after status (rename: both sides of
     ` -> `; strip surrounding quotes)
  3. Resolve each path to absolute (join with
     `git rev-parse --show-toplevel` when relative). Compare
     against Paths absolute `$spex_root` only
  4. Path is under `$spex_root` iff it equals `$spex_root` or
     starts with `$spex_root` + `/` (directory boundary — never
     bare string prefix; avoids treating `.spex.toml` as under
     `.spex`)
  5. Drop a line only if **every** path on that line is under
     `$spex_root`
  6. `$dirty` ← true iff any line remains
- Clean skip (`auto`/`true` + not `$dirty`) still must satisfy
  the task acceptance criteria
- Branch on `$skip_commit` + `$dirty`:
  - `$skip_commit=false` and not `$dirty` -> report issue ->
    **FAIL/STOP** (not a skip path; no Phase 7)
  - `$skip_commit=true` and `$dirty` -> report issue (must be
    clean) -> **FAIL/STOP** (no Phase 7)
  - `$skip_commit=false` and `$dirty` -> continue Phase 5
  - `$skip_commit=auto` and `$dirty` -> continue Phase 5
  - `$skip_commit=true` and not `$dirty` -> `$did_commit=false`;
    skip Phase 5–6 -> Phase 7
  - `$skip_commit=auto` and not `$dirty` -> `$did_commit=false`;
    skip Phase 5–6 -> Phase 7

### Phase 5: Commit (record commit_title only)

- Enter only when Phase 4 routed here (`$skip_commit=false`, or
  `$skip_commit=auto` with `$dirty`)
- CMD:

```bash
$spex_skill_dir/scripts/spex prompt apply-commit --name $spec_name
```

- **Single render:** Call `prompt apply-commit` **once** per commit.
  Save output as `$commit_prompt` and reuse for staging/commit. Do
  **not** re-run unless `$commit_prompt` was lost.

- `$commit_prompt` ← output. Using `$commit_prompt`, stage changes
  + commit:
  - Prefer staging **all** dirty paths outside `$spex_root` so the
    tree is clean after this commit. Leftover dirty paths poison
    later `skip_commit=true|auto` steps (false STOP / unwanted
    commits)
  - Do NOT stage any files under `$spex_root/`
  - Commit via heredoc: `git commit -F- <<-EOF ... EOF`
  - ON_FAIL (e.g. pre-commit hook): fix + retry **once**; IF still
    fails -> STOP + report

- After commit OK:

```bash
git log -1 --pretty="%h: %s"
```

- `$commit_title` ← output

```bash
git rev-parse --short HEAD
```

- `$commit_sha` ← output
- Recompute `$dirty` (same Phase 4 algorithm). IF `$dirty` ->
  report leftover paths excl. `$spex_root` -> STOP (do not
  persist `commit_title`; do not Phase 6/7)
- `$did_commit` ← `true`

- **Persist commit_title now — do NOT set `completed_at` yet**
  (review/fix may still be pending; enables interrupt resume):

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id "$current_task_id" --commit-title "$commit_title"
```

### Phase 6: Review Loop

- Enter only when this step produced a commit: `$did_commit` is
  true, **or** durable todo state (non-empty `commit_title` AND
  empty `completed_at`) — on durable entry set `$did_commit` ←
  `true`. IF neither -> skip to Phase 7
- Load and follow `references/apply-review-loop.md` exactly (includes
  single-prompt rules for `$review_prompt` / `$fix_prompt`;
  review-helper always needs `--name`; most subcommands need
  `--step`; prefer `status` / `next` / `show` — `list`/`get` are
  show aliases; reuse last status JSON — do not re-status right
  after 6b or after a successful `bump-round`)
- IF review loop **STOP**s due to abnormal failure (e.g. fix/amend
  verification fails after relaunch) -> end this invocation without
  Phase 7 or Phase 8. Step stays incomplete (`completed_at` unset)
  so later `/spex apply-one-step` can resume via Phase 3 → Phase 6.
  Round-3 open majors are **not** a reason to STOP — loop must
  enter 6c and fix them in this same invocation.
  `step_review=false` is **not** an abnormal STOP: `prompt
  apply-review` returns `"skipped": true`, the loop continues to
  Phase 7, and this STOP clause does not apply

### Phase 7: Mark Task Complete

- Only after Phase 6 finishes successfully, or when Phase 4/5
  skipped review because `$did_commit` is false. Set
  **`completed_at`** (step not done until this runs):
- IF `$did_commit`:
  - Refresh `$commit_title` if needed (from todo `commit_title`,
    or `git log -1 --pretty="%h: %s"`) before the edit below

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id "$current_task_id" --completed-at now \
  --commit-title "$commit_title"
```

- ELSE (`$did_commit` false — keep `commit_title` empty):

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id "$current_task_id" --completed-at now
```

- ON_FAIL: report error -> STOP

### Phase 8: Summary and Conditional Post Action

- Count remaining undone tasks in `$spec_path/todo.json` (items
  with empty/`null` `completed_at`) -> `$remaining`
- Display summary:
  - Completed step name and `$commit_title` (or
    `(skip_commit / no commit)` when empty)
  - `$remaining` (undone tasks left)
- IF `$remaining` is 0 -> run post-action (spec fully done):

  ```bash
  $spex_skill_dir/scripts/spex apply-helper post-action --name $spec_name
  ```

  Display output to user
- ELSE IF `$remaining` > 0 -> skip `post-action` (unfinished work
  remains)

- **This command implements exactly one step. STOP here.** Do NOT
  loop back to Phase 3 or implement additional steps. User must
  invoke `/spex apply-one-step` again to continue

## STOP / Outputs

- Exactly one step then STOP
- Conditional post-action only when `$remaining` == 0
- Abnormal Phase 6 STOP leaves step incomplete for resume
