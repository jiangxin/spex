# spex archive

Archive completed specs.

## Usage

```text
/spex archive [--name <name>] [--dry-run | -n] [--force | -f] [--restore] [--all-projects]
```

## Options

| Flag           | Description                            |
|----------------|----------------------------------------|
| `--name`      | Archive a single spec by name         |
| `--dry-run, -n`| Preview without moving                 |
| `--force, -f`  | Bypass spex_branch existence check     |
| `--restore`    | Restore a spec from archives to specs |
| `--all-projects` | Archive specs from all projects     |

## Behavior

Specs are only archived if all tasks in `todo.json` are completed.
Additionally, if a spec has `spex_branch` in `meta.json` and the
referenced git branch still exists, the spec is skipped with a warning
unless `--force` is provided.

When `--restore` is used with `--name <name>`, the operation is reversed:
the spec is searched in `archives_dir` with fuzzy substring matching.
If exactly one spec matches, it is moved back to `specs_dir`. Errors
out if no match or multiple matches are found.

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Run Archive Script

Run:

```bash
$spex_skill_dir/scripts/spex archive
```

### Phase 2: Report Results

- If the script output indicates specs were archived, report the list of
  archived specs to the user.
- If no specs were archived, inform the user that there are no completed
  specs to archive.
