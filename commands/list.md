# spex list

List specifications. By default shows only active (incomplete) specs.
Use `--all` to include archived specs.

## Usage

```text
/spex list [--all]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Step 1: Run List Script

Run:

```bash
$spex_skill_path/scripts/spex list $args
```

Where `$args` is `--all` if the user requested all specs, or empty
otherwise.

### Step 2: Report Results

Show the script output to the user. If no specs are found, suggest
using `/spex create` to create one.
