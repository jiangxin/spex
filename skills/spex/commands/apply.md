# spex apply

Apply a specification to implement code step by step.

## Usage

```text
/spex apply [spec_name | --all]
```

## Inputs

- OPT: `$spec_name` or `--all`

## Preconditions

- Follow phases in order. Do not skip or reorder.
- Debug timeline: when debug is enabled, scripts append APPLY
  anchors to `$spec_path/debug.log` automatically (task begin,
  committed, review begin/round, task done, post-action). Do not
  call `mark-phase`.

## Execution

### Phase 1: Resolve Spec

- IF `$spec_name` is `--all`:
  - CMD: `$spex_skill_dir/scripts/spex list --json --must-undone`
  - Parse stdout as JSON array `$specs` of objects (`spec_name`,
    `spec_path`)
  - For each entry in `$specs` (outer loop): set `$spec_name` /
    `$spec_path` -> Phases 2–9 (Phase 9 when that spec's tasks all
    done)
  - After Phase 9 for one spec -> next `$specs` entry at Phase 2.
    IF none remain -> **STOP**
- ELSE -> CMD:

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
  - Reuse for dirty filter + commit staging exclude; pass to
    Phases 4–5 sub-agent

### Phase 3: Build Prompt / Resume Gate

- CMD:

```bash
$spex_skill_dir/scripts/spex prompt apply-one-task --json --name $spec_name
```

- Parse JSON stdout:
  - IF `"all_done": true` -> Phase 9 (skip Phase 8). In `--all`
    mode, after Phase 9 continue Phase 1 outer loop next `$specs`
    entry at Phase 2, or **STOP** if none remain
  - IF non-zero exit -> report stderr -> STOP
  - ELSE save:
    - `$prompt` ← `"prompt"`
    - `$current_task_id` ← `"task_id"`
    - `$resume_phase` ← `"resume_phase"` (`implement` or `review`)
    - `$commit_title` ← `"commit_title"` (may be empty)
    - `$skip_commit` ← `"skip_commit"` (`false` | `auto` | `true`;
      missing → `false`)

- **Single render:** Call `prompt apply-one-task` **once** per task
  iteration. Reuse `$prompt` for Phase 4 and sub-agent handoff. Do
  **not** re-run unless `$prompt` was lost (e.g. new session).

- Step incomplete until `completed_at` set. IF `commit_title` set
  AND `completed_at` empty -> `$resume_phase` is `review` (skip
  implement/commit)

- **Route:**
  - IF `$resume_phase` is `review` -> `$did_commit` ← `true`
    (commit already happened; durable: non-empty `commit_title`
    + empty `completed_at`); skip Phases 4–5 -> Phase 6 in
    main context. Do NOT set `$commit_sha` from `HEAD` here —
    Phase 6 **6-entry** resolves it (prefer review file's
    `commit_sha`)
  - IF `$resume_phase` is `implement` -> launch sub-agent for
    Phases 4–5 only (implement + optional first commit per
    `$skip_commit`). Instruct it to follow Phases 4–5 of this
    command exactly. Pass `$prompt` as Phase 4 guide, plus
    `$current_task_id`, `$spec_name`, `$skip_commit`, and
    `$spex_root`. Implementation prompt must NOT create the
    commit — when a commit is required, sub-agent runs Phase 5
    (`apply-commit`) after implementation.
    Sub-agent final report MUST state one OK outcome:
    - `outcome=committed` (Phase 5 wrote `commit_title`), or
    - `outcome=skip_commit` (`$did_commit=false`; tree clean
      excl. `$spex_root`; Phase 4 skip arms only)
    Phase 4 intentional STOP (`false`+clean, `true`+dirty) is
    **FAIL** (not OK): leave `completed_at` unset; main must
    **STOP** — do **not** enter Phase 7. Do **not** retry
    intentional STOP as a success path.
    ON_FAIL (implement/commit execution errors only — not
    intentional STOP): report + retry **once**; IF still fails
    -> STOP.
    After OK -> in **main** context, re-read the current task
    (e.g. `todo-helper show --id "$current_task_id"`):
    - IF non-empty `commit_title` AND empty `completed_at` ->
      `$did_commit` ← `true`; `$commit_title` ← task's `commit_title`
      -> Phase 6
    - ELSE IF sub-agent reported `outcome=skip_commit` AND
      empty `commit_title` AND empty `completed_at` ->
      recompute `$dirty` in **main** (same Phase 4 algorithm);
      IF `$dirty` -> report unexpected handoff (skip claimed
      but tree dirty excl. `$spex_root`) -> STOP (do **not**
      Phase 7); ELSE `$did_commit` ← `false` -> Phase 7
    - ELSE -> report unexpected handoff -> STOP (do **not**
      Phase 7)
    Do **not** treat empty `commit_title` alone as skip OK.
    Do **not** rely on sub-agent `$did_commit` / `$commit_title`
    / `$dirty` shell vars (they do not cross the boundary).
    Phase 4/5 still set `$did_commit` inside the sub-agent for
    local routing

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
    **FAIL/STOP** (not `outcome=skip_commit`; no Phase 7)
  - `$skip_commit=true` and `$dirty` -> report issue (must be
    clean) -> **FAIL/STOP** (not OK; no Phase 7)
  - `$skip_commit=false` and `$dirty` -> continue Phase 5
  - `$skip_commit=auto` and `$dirty` -> continue Phase 5
  - `$skip_commit=true` and not `$dirty` -> `$did_commit=false`;
    skip Phase 5; return to main with `outcome=skip_commit`
    (do not run Phase 7 inside this Phases 4–5 sub-agent)
  - `$skip_commit=auto` and not `$dirty` -> `$did_commit=false`;
    skip Phase 5; return to main with `outcome=skip_commit`
    (do not run Phase 7 inside this Phases 4–5 sub-agent)

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
- When returning to main from Phases 4–5 sub-agent: report
  `outcome=committed`

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
  verification fails after relaunch) -> end entire `/spex apply`
  immediately — do **not** run Phase 7, Phase 8, or Phase 9; do
  **not** start next task or next `--all` spec. Step stays
  incomplete so later `/spex apply` can resume via Phase 3 →
  Phase 6. Round-3 open majors are **not** a reason to STOP —
  loop must enter 6c and fix them in this same invocation.
  `step_review=false` is **not** an abnormal STOP: `prompt
  apply-review` returns `"skipped": true`, the loop continues to
  Phase 7, and this STOP clause does not apply

### Phase 7: Mark Task Complete

- Only after Phase 6 finishes successfully, or when Phase 4/5
  skipped review because `$did_commit` is false. Set
  **`completed_at`** (step not done until this runs):
- IF `$did_commit`:
  - Refresh `$commit_title` if needed (from todo `commit_title`,
    or `git log -1 --pretty="%h: %s"`) before the edit below —
    main's `$commit_title` may still be empty after a Phases 4–5
    sub-agent

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

### Phase 8: Next Task

- Go back to Phase 3 for next undone task. Each iteration uses
  fresh sub-agent for Phases 4–5 when `resume_phase` is `implement`
- When Phase 3 reports `"all_done": true`, Phase 3 routes to
  Phase 9 (do not loop further for this spec)

### Phase 9: Post Action

- Run for **current** `$spec_name` (once per completed spec,
  including each `--all` entry):

```bash
$spex_skill_dir/scripts/spex apply-helper post-action --name $spec_name
```

- Display output to user
- IF `--all` mode -> continue Phase 1 outer loop next `$specs`
  entry at Phase 2, or **STOP** if none remain
- ELSE -> **STOP.** Do NOT implement additional steps or modify
  project files beyond what was already committed

## STOP / Outputs

- Phases 1–9 including `--all` outer loop, Phase 8 next-task loop,
  Phase 9 post-action
- Abnormal Phase 6 STOP leaves step incomplete for resume
