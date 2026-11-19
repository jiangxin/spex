# Resolve Spec via `list --json`

Shared parsing for commands that resolve `$spec_name` /
`$spec_path` from `spex list --json` (e.g. apply, apply-one-step,
modify, merge). Caller supplies the exact CMD (flags such as
`--must-undone` / `--must-done` and whether `$spec_name` is
passed).

For `--include-unfinished-on-miss`, validate the response using the
[completion lookup contract](#list-completion-lookup).
Apply only the candidate selection rows below to a validated
`completed.specs` array. The caller handles the other statuses.

## Parse

1. Run the caller's `list --json` CMD
2. Parse stdout as a JSON array of objects (`spec_name`,
   `spec_path`, …)
3. Branch:

| Result | Action |
|--------|--------|
| `[]` / zero elements | Report no match; **default STOP**, unless the caller's Preconditions define recovery (e.g. modify: rebound `$request` then list again with empty name) |
| Single element | Set `$spec_name` / `$spec_path` from that entry |
| Multiple | Numbered `spec_name` list -> user chooses -> set `$spec_name` / `$spec_path` from selected entry |
| Script exits error | True error (not an empty result) → report stderr → **STOP** |

## Notes

- Empty / missing `$spec_name` behavior depends on CLI flags and
  whether the name arg is omitted — follow the caller's CMD
- Do not invent a second match algorithm; trust `list` output
- `list` patterns are **substring** matches (`pattern in name`).
  A leading `^` triggers regex; `*`/`?` trigger glob. A
  single-element result is **not** proof of an exact match —
  callers that need exact semantics must compare `spec_name`
  themselves
- An empty array (`[]`) is **not** a script error. Never assume
  that zero matches require exit 1; with ordinary `--json`, empty match
  prints `[]` and exits 0. Only treat a non-zero exit (or
  non-array stdout) as a true script failure
- Without `--json`, empty match may still print
  `No specs found.` on stderr and exit 1 — callers that need a
  programmable empty result must use `--json`

## List completion lookup

`list --json --must-done --include-unfinished-on-miss -- "<probe>"`
requires one pattern, which may be empty. Omit `--details`.

On exit 0, validate a JSON object with a known `status` and a `specs`
array. Every entry must have a non-empty string `spec_name` and
`spec_path`. Validate the fields and item counts for the reported status
before routing. Report invalid JSON, a top-level array, an unknown
status, or invalid fields or counts as a protocol error and stop.

| Status | Required `specs` content |
|--------|--------------------------|
| `completed` | Non-empty array of completed matches |
| `unfinished` | Non-empty array of unfinished matches for a non-empty probe, with integer `done` and `total` satisfying `0 <= done <= total` |
| `no_match` | Empty array |

Completed matches take precedence. Unfinished matches are returned only
for a non-empty probe with no completed matches.
