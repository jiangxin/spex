---
name: sdd
disable-model-invocation: true
description: "Spec-Driven Development (SDD) skill for managing specification documents, and generating code. Invoked manually via /sdd <command>. Supports commands: create, list, apply, archive."
arguments:
  - name: command
    required: true
    description: "Sub-command to execute. Must be one of: create, list, apply, archive. Show usage help and exit if missing or unrecognized."
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

| Command   | Description            |
|-----------|------------------------|
| `create`  | Create a new spec      |
| `list`    | List existing specs    |
| `apply`   | Apply a spec to generate code |
| `archive` | Archive a completed spec |

## Command Routing

Parse the first argument as `<command>` and route to the corresponding command file:

- `create` → Read and follow `commands/create.md`
- `list` → Read and follow `commands/list.md`
- `apply` → Read and follow `commands/apply.md`
- `archive` → Read and follow `commands/archive.md`

If no command is given or the command is unrecognized, show this usage information to the user.

## Spec Directory

**Before executing any command, resolve the spec root path first.** Run:

```bash
python <skill-path>/scripts/_shared/common.py
```

The script prints the spec root path to stdout. Store this value as `$spec_root` — all subsequent operations reference paths relative to `$spec_root`.

The default location is `<parent-of-cwd>/.<workdir-name>.specs`. For example, if working in `/Users/alice/projects/my-app`, then `$spec_root` is `/Users/alice/projects/.my-app.specs`.
