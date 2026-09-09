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
| Single element | Set `$spec_name` / `$spec_path` from that entry |
| Multiple | Numbered `spec_name` list -> user chooses -> set `$spec_name` / `$spec_path` from selected entry |
| Script exits error | Report stderr -> **STOP** |

## Notes

- Empty / missing `$spec_name` behavior depends on CLI flags and
  whether the name arg is omitted — follow the caller's CMD
- Do not invent a second match algorithm; trust `list` output
