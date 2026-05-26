---
name: spex
disable-model-invocation: true
description: "Spec-Driven Development (Spex) skill for managing specification documents, and generating code. Invoked manually via /spex <command>. Supports commands: create (new), list, modify, apply (run, do, go), archive, init, install-cli (install)."
metadata:
  version: 0.0.1
arguments:
  - name: command
    required: true
    description: "Sub-command to execute. Must be one of: create (alias: new), list, modify, apply (aliases: run, do, go), archive, init, install-cli (alias: install). Show usage help and exit if missing or unrecognized."
  - name: prompt
    required: false
    description: "Optional context passed to the command. For 'create', this is the requirement describing the spec to generate."
---

# Spex — Spec-Driven Development

A skill for managing specification documents in a structured spec directory.

## Usage

```
/spex <command> [arguments...]
```

## Supported Commands

| Command    | Aliases          | Description                       |
|------------|------------------|-----------------------------------|
| `create`   | `new`            | Create a new spec                 |
| `list`     |                  | List specs (use `--all` to include archived) |
| `modify`   |                  | Modify a spec's requirements      |
| `apply`    | `run`, `do`, `go`| Apply a spec to generate code     |
| `archive`  |                  | Archive a completed spec          |
| `init`     |                  | Initialize spex environment       |
| `install-cli` | `install`     | Install spex CLI to ~/.local/bin  |

## Command Routing

`$spex_skill_dir` refers to the directory where this SKILL.md resides.

Parse the first argument as `<command>` and route to the corresponding
command file:

- `create` / `new` → `commands/create.md`
- `list` → `commands/list.md`
- `modify` → `commands/modify.md`
- `apply` / `run` / `do` / `go` → `commands/apply.md`
- `archive` → `commands/archive.md`
- `init` → `commands/init.md`
- `install-cli` / `install` → `commands/install-cli.md`

### Constraints

1. If the first argument matches a route above, you MUST load the
   corresponding command markdown file and follow its procedure
   step-by-step exactly as written. Do NOT interpret the user's prompt
   directly or skip loading the command file.
2. If the first argument does not match any route (or is missing), show
   the usage information above and stop. Do NOT attempt to infer intent
   or execute any other action.
