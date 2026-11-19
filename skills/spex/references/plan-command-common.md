# Plan Command Common (create / modify)

Shared PLAN-only rules for `/spex create` and `/spex modify`.

## Write whitelist (SCOPE)

- Spec writes are limited to `$spec_path` (`spec.md`, `todo.json`,
  `meta.json`, the `todo.json.lock` backup and its temporary file
  managed by todo-helper, optional `assets/`).
- The modify helper also manages `versions/`,
  and `modify-pending.json` under `$spec_path`, including temporary
  files used for atomic writes.
- The modify post-action helper may update or restore
  `branch.<spex_branch>.description` in the spec's bound repository's local
  Git configuration. This is the only permitted Git configuration write.
- NO application code. Existing project files outside `$spec_path`
  are outside the write whitelist.
- Implementation later via `/spex apply` or `/spex apply-one-step`.

## Explore whitelist (read-only)

- Allowed: `Glob` / `Grep` / limited `Read`; read-only spex CLI.
- Forbidden: Write / ApplyPatch / tree-changing shell outside
  `$spec_path`; starting todo implementation.

## Clarification gate

- IF authoritative sources conflict, name the sources and the
  conflicting requirement and ask which source or requirement governs.
  Resolve the conflict with the user before preparing or updating the
  spec. Do not reconcile conflicting sources on your own.
- IF a necessary authoritative source is missing, unreadable, or
  incomplete, name the source and ask for the missing information or
  a usable replacement. Recheck any source supplied in the reply.
  Wait until the source issue is resolved before preparing or updating
  the spec.
- IF multiple viable implementation paths affect design -> ask
  at least one question (do not silently pick a path)
- ELSE IF the requirement/request is already specific/unambiguous
  (modify: in current-spec context) -> skip clarification.
  Do not ask just to be thorough; only when the answer would
  materially change the spec
- Also clarify when any apply:
  - scope/boundaries unclear (modify: which sections affected;
    replace vs extend)
  - dependencies on other systems/features unspecified
  - relationship to completed work unclear (modify: preserve vs
    redo)
  - ambiguous terminology with multiple interpretations (modify:
    in context of the existing specification)

## How to clarify

- Ask all questions in one message (not back-and-forth)
- Limit 2–4 questions; prioritize those most affecting design

## Out-of-whitelist write → STOP

- Any write **outside the whitelist** -> **immediate STOP**;
  roll back those out-of-scope
  changes if possible; do **not** continue later phases

## Todo transaction failure handling

- For create, `create-helper finalize` owns post-action and commit.
  Correct recoverable failures before the hook and retry finalize.
  If finalize reports a commit failure, keep the backup and run only
  `spex todo-helper transaction commit <spec-name>`. Do not rerun
  finalize. For modify, follow the exit-code branches in
  [Phase 8 of modify](../commands/modify.md#phase-8-post-action).

- Existing backup at entry: report its path and both recovery commands,
  then stop. Only the transaction owner chooses and runs a recovery command.
- Start failure: report stderr, apply the existing-backup rule if
  `$spec_path/todo.json.lock` exists, and stop before editing todo.

Recovery options for the transaction owner. Commit keeps the current list:

```bash
$spex_skill_dir/scripts/spex todo-helper transaction commit "$spec_name"
```

Rollback restores the backup:

```bash
$spex_skill_dir/scripts/spex todo-helper transaction rollback "$spec_name"
```

- After a successful start, roll back if the batch fails or is
  abandoned before attempting commit, including after an
  out-of-whitelist write.

- Commit or rollback failure: report stderr, the backup path, and the
  failed command for retry. Stop with the backup left in place.
- The transaction covers only `todo.json`. Other spec files and
  post-action side effects are outside its scope.

## Output format

- Display a human summary:

```text
**Spec**: `$spec_name`

- Spec: `$spec_path/spec.md`
- Todo: `$spec_path/todo.json`
- Meta: `$spec_path/meta.json`
```

- Append exactly one trailing fenced block with language tag
  `json spex-result` (fields `spec_name` and `spec_path` only):

```json spex-result
{
  "spec_name": "$spec_name",
  "spec_path": "$spec_path"
}
```

- `spec_path` MUST be the absolute spec directory
- Do NOT add other final-phase `json` / `json spex-result` fences
  or extra JSON fields
- Callers that need a machine result MUST parse the **last**
  fenced `json spex-result` block (create also accepts a last
  fenced `json` block for backward-compatible callers)

## Hard STOP — Do NOT Implement

- Hard STOP. Follow the write whitelist. Do NOT write application code
  or begin implementing steps in `todo.json`.
- Sole responsibility: produce or update the spec and its development plan.
- Wait for user review -> `/spex apply` or `/spex apply-one-step`.
