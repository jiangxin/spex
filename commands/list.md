# sdd list

List all specification documents in the spec directory.

## Usage

```
/sdd list [--status <status>]
```

## Behavior

1. Resolve the spec directory by running `scripts/_shared/common.py`
2. Scan the spec directory for `.md` files
3. For each spec file, extract frontmatter metadata (title, status, created date)
4. Display a formatted table showing:
   - Name
   - Status (draft / active / completed / archived)
   - Created date

## Output Format

```
Spec Directory: /path/to/.project.spec

| Name          | Status    | Created    |
|---------------|-----------|------------|
| feature-auth  | active    | 2026-05-01 |
| api-redesign  | draft     | 2026-05-15 |
```

## Filtering

If `--status <status>` is provided, only show specs matching that status.

## Edge Cases

- If the spec directory does not exist or is empty, inform the user: "No specs found. Use `/sdd create` to create one."
