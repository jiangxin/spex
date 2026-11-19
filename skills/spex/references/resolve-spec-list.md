# Resolve Spec via `list --json`

## Parse

Check the caller's `list --json` result per the
[CLI contract](cli-contract.md). For `[]`, run the caller's
recovery if specified. Otherwise report no match and stop. For a
non-empty array of entries, follow [Candidate selection](#candidate-selection).

## Candidate selection

Use the sole entry or show numbered `spec_name` values in result order
and wait for a pick. Set `$spec_name` and `$spec_path` from that entry.
Use the matches returned by `list`. A leading `^` selects regex,
`*` or `?` selects glob otherwise, and other patterns match substrings.
For exact-name semantics, compare `spec_name` to the requested name.

## List completion lookup

`list --json --must-done --include-unfinished-on-miss -- "<probe>"`
requires one pattern, which may be empty. Omit `--details`.

On exit 0, require a JSON object with a `status` from the table and a
`specs` array. Each entry requires non-empty strings for `spec_name`
and `spec_path`. Report a protocol error and stop on invalid JSON,
wrong types, unknown status, or invalid entry fields or counts.

| Status | Required `specs` content |
|--------|--------------------------|
| `completed` | Non-empty array of completed matches |
| `unfinished` | Non-empty array of unfinished matches for a non-empty probe, with integer `done` and `total` satisfying `0 <= done <= total` |
| `no_match` | Empty array |

Completed matches take precedence. Unfinished matches are returned only
for a non-empty probe with no completed matches.
