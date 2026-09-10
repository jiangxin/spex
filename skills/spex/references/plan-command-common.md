# Plan Command Common (create / modify)

Shared PLAN-only rules for `/spex create` and `/spex modify`.
Load and follow this document exactly when a command says so.
Command-specific binding, phases, and recovery stay in the
command file — this file is deduplication, not a relaxation of
PLAN-only guards.

## Write whitelist (SCOPE)

- Write **only** under `$spec_path` (`spec.md`, `todo.json`,
  `meta.json`, optional `assets/`).
- NO application code. NO existing project file modifications
  outside `$spec_path`.
- Implementation later via `/spex apply` or `/spex apply-one-step`.

## Explore whitelist (read-only)

- Allowed: `Glob` / `Grep` / limited `Read`; read-only spex CLI.
- Forbidden: Write / ApplyPatch / tree-changing shell outside
  `$spec_path`; starting todo implementation.

## Clarification gate

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

- Any Write / ApplyPatch / tree-changing shell **outside**
  `$spec_path` -> **immediate STOP**; roll back those out-of-scope
  changes if possible; do **not** continue later phases

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

- Hard STOP. Do NOT write application code, modify project files
  outside `$spec_path`, or begin implementing steps in `todo.json`.
  Any write outside `$spec_path` is a Preconditions violation.
- Sole responsibility: produce or update `spec.md`, `todo.json`,
  `meta.json` inside the spec directory.
- Wait for user review -> `/spex apply` or `/spex apply-one-step`.
