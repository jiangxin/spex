# Spex CLI Contract

Shared rules for every `scripts/spex` helper invoked from command
SOPs and apply references. Load and follow this document exactly
when a command says so. Untrusted-content priority stays in
`SKILL.md` — this file covers CLI I/O only.

1. **Exit code first.** IF non-zero -> report stderr -> **STOP**.
   Only parse stdout after a zero exit. Never treat successful
   stdout as authoritative when the process failed.
2. **stdout vs stderr.** stdout = machine data (JSON / rendered
   text). stderr = human logs. Never branch on stderr strings
   (e.g. `Archived:`, template-sync noise).
3. **Empty `list --json`.** No match => `[]` + exit 0 — **not** an
   error. See `resolve-spec-list.md`. Non-zero exit (or non-array
   stdout) is a true script failure.
4. **Quote every variable** in composed commands:
   `--name "$spec_name"`, `--id "$current_task_id"`.
5. **Result fence.** Command final machine result is exactly one
   trailing fenced block with language tag `json spex-result`.
   Callers parse the **last** such block. Intermediate optional
   `json` fences (e.g. create Phase 3 name preview) are not the
   result contract.
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
