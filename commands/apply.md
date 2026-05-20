# sdd apply

Apply a specification to generate code implementation.

## Usage

```
/sdd apply <spec-name>
```

## Behavior

1. Resolve the spec directory by running `scripts/_shared/common.py`
2. Locate the spec file `<spec-name>.md` in the spec directory
3. Read and parse the spec (frontmatter + body sections)
4. Update the spec's frontmatter status to `active`
5. Read the Requirements and Design sections
6. Generate code implementation based on the spec content:
   - Create files/directories as described in Design
   - Implement features listed in Requirements
   - Mark completed requirement checkboxes in the spec
7. After implementation, update spec status to `completed`

## Error Handling

- If `<spec-name>` is not provided, show available specs and prompt the user to choose
- If the spec does not exist, inform the user and suggest running `/sdd list`
- If the spec is already archived, inform the user (no action needed)
