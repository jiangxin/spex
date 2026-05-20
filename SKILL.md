---
name: sdd
disable-model-invocation: true
description: "Spec-Driven Development (SDD) skill for managing specification documents, and generating code. Invoked manually via /sdd <command>. Supports commands: create (init, new), list, list-all, edit, modify, apply (run, do, go), archive, install."
arguments:
  - name: command
    required: true
    description: "Sub-command to execute. Must be one of: create (aliases: init, new), list, list-all, edit, modify, apply (aliases: run, do, go), archive, install. Show usage help and exit if missing or unrecognized."
  - name: prompt
    required: false
    description: "Optional context passed to the command. For 'create', this is the requirement describing the spec to generate."
---

# SDD — Spec-Driven Development

A skill for managing specification documents in a structured spec directory.

## Usage

```
/sdd <command> [arguments...]
```

## Supported Commands

| Command    | Aliases          | Description                       |
|------------|------------------|-----------------------------------|
| `create`   | `init`, `new`    | Create a new spec                 |
| `list`     |                  | List active (incomplete) specs    |
| `list-all` |                  | List all specs including archived |
| `modify`   |                  | Modify a spec's requirements      |
| `apply`    | `run`, `do`, `go`| Apply a spec to generate code     |
| `archive`  |                  | Archive a completed spec          |
| `install`  |                  | Install sdd CLI to ~/.local/bin   |

## Command Routing

Parse the first argument as `<command>` and route to the corresponding command file:

- `create` / `init` / `new` → Read and follow `commands/create.md`
- `list` → Read and follow `commands/list.md`
- `list-all` → Read and follow `commands/list-all.md`
- `modify` → Read and follow `commands/modify.md`
- `apply` / `run` / `do` / `go` → Read and follow `commands/apply.md`
- `archive` → Read and follow `commands/archive.md`
- `install` → Read and follow `commands/install.md`

If no command is given or the command is unrecognized, show this usage information to the user.

## Spec Directory

**Before executing any command, resolve the spec root path first.** Run:

```bash
<skill-path>/scripts/sdd get --spec-root
```

The script prints the spec root path to stdout. Store this value as `$spec_root` — all subsequent operations reference paths relative to `$spec_root`.

The default location is `<repo-root>/.specs`. For example, if working in `/Users/alice/projects/my-app`, then `$spec_root` is `/Users/alice/projects/my-app/.specs`.
