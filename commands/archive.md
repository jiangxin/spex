# spex archive

Archive completed specification topics.

## Usage

```text
/spex archive [--topic <topic>] [--dry-run | -n] [--force | -f]
```

## Options

| Flag           | Description                            |
|----------------|----------------------------------------|
| `--topic`      | Archive a single topic by name         |
| `--dry-run, -n`| Preview without moving                 |
| `--force, -f`  | Bypass spex_branch existence check     |

## Behavior

Topics are only archived if all tasks in `todo.json` are completed.
Additionally, if a topic has `spex_branch` in `meta.json` and the
referenced git branch still exists, the topic is skipped with a warning
unless `--force` is provided.

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Run Archive Script

Run:

```bash
$spex_skill_dir/scripts/spex archive
```

### Phase 2: Report Results

- If the script output indicates topics were archived, report the list of
  archived topics to the user.
- If no topics were archived, inform the user that there are no completed
  topics to archive.
