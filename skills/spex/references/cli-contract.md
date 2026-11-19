# Spex CLI Contract

Shared rules for every `scripts/spex` helper invoked from command
SOPs and apply references. Load and follow this document exactly
when a command says so. Untrusted-content priority stays in
`SKILL.md` — this file covers CLI I/O only.

1. **Exit code first.** Parse stdout only after exit 0. On failure,
   report stderr and stop unless the calling SOP specifies recovery.
2. **stdout vs stderr.** stdout = machine data (JSON / rendered
   text). stderr = human diagnostics. Route by exit code and
   structured results. Use diagnostics to correct input or follow an
   explicit recovery command where the calling SOP directs it.
3. **`list --json`.** Expect an array, with `[]` and exit 0 for no
   match. With `--include-unfinished-on-miss`, expect the
   [completion lookup object](resolve-spec-list.md#list-completion-lookup).
   Follow `resolve-spec-list.md` for candidate selection. Stop on non-zero
   exit or a response that fails the applicable contract.
4. **Quote every variable** in composed commands:
   `"$spec_name"`, `--id "$current_task_id"`.
5. **Result fence.** Command final machine result is exactly one
   trailing fenced block with language tag `json spex-result`.
   Callers parse the **last** such block.
6. **One helper per shell.** Run each helper / `prompt` /
   `review-helper` as its own shell invocation. Do not chain
   init + prompt + python one-liners in a single command.

## Prompt output files

For prompt subcommands that accept `--json`, combining it with
`--output PATH` writes the complete JSON result to PATH and leaves
stdout empty. Without `--output`, JSON goes to stdout. This includes
all-done and skipped-review results. Output failures exit non-zero.
`apply-commit` also accepts JSON output; its default remains text.

```bash
$spex_skill_dir/scripts/spex prompt apply-one-task --json \
  "$spec_name" --output "$result_path"
```

Check the exit code before reading the JSON file. Non-JSON output
keeps its existing text format.

## Read-only plan review prompt

Run from the invoking project to use its template override. Pass the
exact absolute `spec_path` from `list --read-only --json` and send focus
as plain text with `--stdin`. The read-only helper outputs the prompt
on stdout and accepts no output-file option. On failure it reports
stderr with empty stdout. A blank render names the template in stderr.
