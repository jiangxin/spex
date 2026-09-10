# Resolve Spec via `list --json`

Shared parsing for commands that resolve `$spec_name` /
`$spec_path` from `spex list --json` (e.g. apply, apply-one-step,
modify, merge). Caller supplies the exact CMD (flags such as
`--must-undone` / `--must-done` and whether `$spec_name` is
passed).

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
- An empty result (`[]`) is **not** a script error. Never assume
  that zero matches require exit 1; with `--json`, empty match
  prints `[]` and exits 0. Only treat a non-zero exit (or
  non-array stdout) as a true script failure
- Without `--json`, empty match may still print
  `No specs found.` on stderr and exit 1 — callers that need a
  programmable empty result must use `--json`
