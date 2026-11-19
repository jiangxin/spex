# Resolve Spec Name from `$user_prompt`

The caller supplies the lookup command and any recovery override.

## Probe and request

Bind and remove recognized Usage flags first. Trim the remaining
`$user_prompt`. Set `$first_word` to its first whitespace-separated word
and `$request` to the text after that word. Either may be empty.

## Array lookup

Run the caller's `list --json` with `$first_word`. For an empty probe,
start with empty `$spec_name` and the whole `$user_prompt` as `$request`.
Follow [Parse](resolve-spec-list.md#parse). For a non-empty probe that
returns `[]`:

- With `--must-undone` or `--must-done`, preserve `$first_word` as the
  `$spec_name` recovery candidate and return `[]` to the caller.
- Otherwise clear `$spec_name`, restore the whole `$user_prompt` as
  `$request`, and re-run the caller's lookup with an empty name.

## After selection

Echo `spec=<X> / request=<Y>` once after locking the spec. Proceed
immediately after a unique named hit (S1), a unique empty-name hit (S2),
or a numbered user pick (S3). Adopt a non-empty `$request`. Wait only
while a multi-hit choice is pending.
