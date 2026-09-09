# Apply Task Phases (Phase 2–7)

Shared orchestration core for `/spex apply` and
`/spex apply-one-step`. Load and follow this document for Phases
2–7 unless the command wraps a phase (e.g. apply Phase 3
sub-agent handoff — see `apply-subagent-handoff.md`).

**Semantic conservation:** preserve full `skip_commit` /
`$did_commit` / `outcome=` behavior. Do not weaken intentional
FAIL/STOP, residual-dirty STOP, or `commit_title` before
`completed_at`.

Command-specific wrappers (not duplicated here): Phase 1 resolve,
`--all` / multi-task loops, apply Phases 4–5 sub-agent launch,
apply-one-step single-step STOP + conditional post-action.

## Phase 2: Validate Branch

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
- Reuse for dirty filter + commit staging exclude; apply
  passes `$spex_root` to Phases 4–5 sub-agent

## Phase 3: Build Prompt / Resume Gate

Caller runs `prompt apply-one-task` (and handles `"all_done"` /
command-specific post-action routing). Then parse JSON stdout and
route as below.

- Save:
  - `$task_prompt` ← `"prompt"` (never call this `$prompt`)
  - `$current_task_id` ← `"task_id"`
  - `$resume_phase` ← `"resume_phase"` (`implement` or `review`)
  - `$commit_title` ← `"commit_title"` (may be empty)
  - `$skip_commit` ← `"skip_commit"` (`false` | `auto` | `true`;
    missing → `false`)

- **Single render:** Call `prompt apply-one-task` **once** per task
  iteration. Reuse `$task_prompt` for Phase 4 and sub-agent
  handoff. Do **not** re-run unless `$task_prompt` was lost
  (e.g. new session).

- Step incomplete until `completed_at` set. IF `commit_title` set
  AND `completed_at` empty -> `$resume_phase` is `review` (skip
  implement/commit)

- **Route (shared):**
  - IF `$resume_phase` is `review` -> `$did_commit` ← `true`
    (commit already happened; durable: non-empty `commit_title`
    and empty `completed_at`); skip Phases 4–5 -> Phase 6. Do
    NOT set `$commit_sha` from `HEAD` here — Phase 6
    **6-entry** resolves it (prefer review file's `commit_sha`)
  - IF `$resume_phase` is `implement` -> Phase 4 (then Phase 5
    only when `$skip_commit` requires a commit). Caller may wrap
    Phases 4–5 in a sub-agent (`apply` — see
    `apply-subagent-handoff.md`) or run them in-session
    (`apply-one-step`)
  - Phase 4 intentional STOP (`false`+clean, `true`+dirty) is
    **FAIL** — leave `completed_at` unset; do **not** enter
    Phase 7. Do **not** treat intentional STOP as
    `outcome=skip_commit`

## Phase 4: Execute Task

- Using `$task_prompt` as guide (from Phase 3 — do **not** re-run
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

### Dirty check (CLI)

```bash
$spex_skill_dir/scripts/spex apply-helper dirty --json
```

- Parse stdout JSON: `$dirty` ← `"dirty"` (bool). Optional:
  `"paths"`, `"spex_root"` (absolute). IF non-zero exit -> report
  stderr -> STOP
- Prefer `--spex-root "$spex_root"` when the Paths bind must be
  forced; otherwise CLI uses Paths absolute `spex_root`
- Clean skip (`auto`/`true` + not `$dirty`) still must satisfy
  the task acceptance criteria

**Debug only** — equivalent porcelain semantics (encoded by the
CLI; do **not** re-implement by hand in normal apply):

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

### skip_commit six-arm matrix

Branch on `$skip_commit` + `$dirty`:

| `$skip_commit` | `$dirty` | Action |
|----------------|----------|--------|
| `false` | no | report issue -> **FAIL/STOP** (not `outcome=skip_commit`; no Phase 7) |
| `true` | yes | report issue (must be clean) -> **FAIL/STOP** (not OK; no Phase 7) |
| `false` | yes | continue Phase 5 |
| `auto` | yes | continue Phase 5 |
| `true` | no | `$did_commit=false`; skip Phase 5–6; caller continues without review |
| `auto` | no | `$did_commit=false`; skip Phase 5–6; caller continues without review |

Skip arms (`true`/`auto` + not `$dirty`):

- **apply** Phases 4–5 sub-agent: return to main with
  `outcome=skip_commit` (do **not** run Phase 7 inside the
  sub-agent)
- **apply-one-step** (in-session): continue to Phase 7

Intentional FAIL/STOP arms must **not** be reported or retried as
OK skip paths.

## Phase 5: Commit (record commit_title only)

- Enter only when Phase 4 routed here (`$skip_commit=false`, or
  `$skip_commit=auto` with `$dirty`)
- CMD:

```bash
$spex_skill_dir/scripts/spex prompt apply-commit --name $spec_name
```

- **Single render:** Call `prompt apply-commit` **once** per commit.
  Save output as `$commit_prompt` and reuse for staging/commit. Do
  **not** re-run unless `$commit_prompt` was lost.

- `$commit_prompt` ← output. Using `$commit_prompt`, stage and
  commit:
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
- Recompute `$dirty` via the same Phase 4 dirty CLI
  (`apply-helper dirty --json`). IF `$dirty` -> report leftover
  paths excl. `$spex_root` -> STOP (do not persist `commit_title`;
  do not Phase 6/7)
- `$did_commit` ← `true`
- When returning to main from Phases 4–5 sub-agent: report
  `outcome=committed`

- **Persist commit_title now — do NOT set `completed_at` yet**
  (review/fix may still be pending; enables interrupt resume):

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id "$current_task_id" --commit-title "$commit_title"
```

## Phase 6: Review Loop

- Load and follow `references/apply-review-loop.md` exactly

## Phase 7: Mark Task Complete

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
