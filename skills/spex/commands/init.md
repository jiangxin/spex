# spex init

Initialize the spex environment for the current project.

## Usage

```text
/spex init
```

## Phase 1: Run Initialization

Load and follow `references/cli-contract.md`. Ignore the remaining
`$user_prompt` and invoke the CLI without arguments:

```bash
$spex_skill_dir/scripts/spex init
```

## Phase 2: Report Results

On non-zero exit, report stderr and stop. On exit 0, report completion
and summarize any diagnostics about an existing layout, a non-Git
directory, or installation warnings. Include manual fixes when the
diagnostics call for them. Stop after reporting.
