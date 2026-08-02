# spex archive

Archive completed specs.

## Usage

```text
/spex archive [--name <name>] [--dry-run | -n] [--force | -f] [--restore] [--all-projects]
```

## Inputs

| Flag | Description |
|------|-------------|
| `--name` | Archive a single spec by name |
| `--dry-run, -n` | Preview without moving |
| `--force, -f` | Bypass spex_branch existence check |
| `--restore` | Restore a spec from archives to specs |
| `--all-projects` | Archive specs from all projects |

## Preconditions

- Archive only if all `todo.json` tasks completed
- IF `spex_branch` in `meta.json` AND that git branch still exists ->
  skip + warn UNLESS `--force`
- `--restore` + `--name <name>` -> reverse op: fuzzy substring search in
  `archives_dir`
  - IF exactly 1 match -> move back to `specs_dir`
  - ELSE (0 or many) -> FAIL

## Execution

Follow phases in order. Do not skip or reorder.

### Phase 1: Run Archive Script

- Forward any agent-supplied Usage flags unchanged.
- CMD:

```bash
$spex_skill_dir/scripts/spex archive [--name <name>] [-n|--dry-run] [-f|--force] [--restore] [--all-projects]
```

### Phase 2: Report Results

- IF output matches `Archived:` / `Would archive` -> report that list
- ELSE IF output matches `Restored:` / `Would restore` -> report restore result
- ELSE IF output is `No completed specs to archive.` -> inform none
- ELSE -> surface script output / errors as-is

## STOP / Outputs

- Report archive / restore result -> STOP
