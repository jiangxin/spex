# Resolve Spec Name from `$user_prompt`

Shared name recognition for `modify`, `apply`, `apply-one-step`,
and `merge`. This file decides **which text to look up**;
`resolve-spec-list.md` decides **what to do with 0/1/N results**.
Caller supplies the exact `list --json` CMD (flags such as
`--must-undone` / `--must-done`).

## Steps

1. `$first_word` ← first whitespace-separated word of `$user_prompt`
   after trim (may be empty)
2. IF `$first_word` is non-empty → unconditionally run the caller's
   `list --json "$first_word"` (with caller flags). Load and follow
   `resolve-spec-list.md` to parse:
   - Exactly one hit → lock `$spec_name` / `$spec_path` from that
     entry; `$request` ← remainder of `$user_prompt` after the first
     word (may be empty; commands without `$request` ignore it)
   - Multiple → numbered choice; `$request` as above
   - `[]` → `$spec_name` ← `$first_word` (**recovery candidate**);
     `$request` ← remainder. IF the caller CMD uses `--must-undone`
     or `--must-done` → **do not** clear the name and **do not**
     empty-re-list; yield `[]` so the caller's Phase 1 empty-`[]`
     recovery can run with this candidate. ELSE → step 3
   - Script error → STOP per `resolve-spec-list.md`
3. `$spec_name` ← empty; `$request` ← whole `$user_prompt`; re-run
   the caller's `list --json` with an empty name (caller flags).
   Only when `$first_word` was empty, or an **unfiltered** first-word
   probe missed — never wipe a filtered recovery candidate before
   the caller has run completed/unfinished recovery
4. After locking (single hit or user pick), echo once
   `spec=<X> / request=<Y>` and wait for confirmation. Merge with
   "selecting a spec does **not** confirm `$request`" into one
   round trip (do not ask separately for spec lock and request)
5. `list` matches **substrings**. A single hit is **not** proof of
   an exact match — callers that need exact semantics must compare
   `spec_name` themselves

## Notes

- Commands that recognize Usage flags (`--all`, `--dry-run`, …)
  strip or bind those flags **before** this algorithm; the
  remainder is `$user_prompt` here
- Empty / missing `$first_word` skips step 2 and goes to step 3
- Named completed-spec / unfinished-spec recovery stays reachable
  under first-word probing: a filtered `[]` leaves `$spec_name`
  set to the probed word for the caller's empty-`[]` handling
