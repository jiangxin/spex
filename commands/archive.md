# sdd archive

Archive a completed specification document.

## Usage

```
/sdd archive <spec-name>
```

## Behavior

1. Resolve the spec directory by running `scripts/_shared/common.py`
2. Locate the spec file `<spec-name>.md` in the spec directory
3. Update the spec's frontmatter status to `archived`
4. Add an `archived: <YYYY-MM-DD>` field to the frontmatter
5. Move the file into an `archived/` subdirectory within the spec directory

## Directory Structure After Archive

```
.project.specs/
├── active-spec.md
├── archived/
│   └── old-spec.md
```

## Error Handling

- If `<spec-name>` is not provided, show available specs and prompt the user to choose
- If the spec does not exist, inform the user and suggest running `/sdd list`
- If the spec is already archived, inform the user (no action needed)
