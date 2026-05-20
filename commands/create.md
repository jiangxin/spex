# sdd create

Create a new specification document in the spec directory.

## Usage

```
/sdd create <spec-name> [description]
```

## Behavior

1. Resolve the spec directory by running `scripts/_shared/common.py`
2. Create the spec directory if it does not exist
3. Create a new spec file named `<spec-name>.md` inside the spec directory
4. Initialize the spec with a template containing:
   - Title (from spec-name)
   - Description (from argument or prompt the user)
   - Status: `draft`
   - Created date: today
   - Sections: Overview, Requirements, Design, Implementation Notes

## Template

```markdown
---
title: <spec-name>
status: draft
created: <YYYY-MM-DD>
---

# <spec-name>

## Overview

<description>

## Requirements

- [ ] TODO

## Design

TODO

## Implementation Notes

TODO
```

## Error Handling

- If a spec with the same name already exists, warn the user and ask whether to overwrite
- If `<spec-name>` is not provided, prompt the user for a name
