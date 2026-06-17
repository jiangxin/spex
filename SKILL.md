---
name: spex
disable-model-invocation: true
description: "Spec-Driven Development (Spex) skill that manages the full SDLC — from requirement analysis and design to incremental implementation and submission. Invoked manually via /spex <command>. Supports commands: create (new), modify, apply (run, do, go), apply-one-step (step), merge (submit), archive, init."
version: 0.3.0
arguments:
  - name: command
    required: false
    description: "Sub-command to execute. Must be one of: create (alias: new), modify, apply (aliases: run, do, go), apply-one-step (alias: step), merge (alias: submit), archive, init. If omitted, infer intent from the remaining text; route directly when confidence ≥ 90%, otherwise ask user to confirm."
  - name: prompt
    required: false
    description: "Optional context passed to the command. For 'create', this is the requirement describing the spec to generate."
---

# Spex — Spec-Driven Development

A spec-driven development skill that manages the full SDLC — from requirement
analysis and design to incremental implementation, and submission.

## Usage

```
/spex [command] [prompt]
```

1. **No arguments** (`/spex`) — display the Supported Commands table
   below and stop.
2. **Recognized command** (`/spex create ...`) — route to the
   corresponding command file per Command Routing and execute its SOP.
3. **Free-form prompt** (`/spex <arbitrary text>`) — infer intent using
   the heuristics in Command Routing. If confidence is ≥ 90%, route
   directly. Otherwise, ask the user to confirm intent before routing.

## Supported Commands

| Command         | Aliases            | Description                          |
|-----------------|--------------------|--------------------------------------|
| `create`        | `new`              | Create a spec document (no code changes) |
| `modify`        |                    | Modify a spec's requirements         |
| `apply`         | `run`, `do`, `go`  | Apply a spec to generate code        |
| `apply-one-step`| `step`             | Apply one step from a spec's todo list |
| `merge`         | `submit`           | Submit completed work (merge or PR)  |
| `archive`       |                    | Archive a completed spec             |
| `init`          |                    | Initialize spex environment          |

## Command Routing

All command file paths below are relative to the directory where this
SKILL.md resides.

| Match                              | Command file                  |
|------------------------------------|-------------------------------|
| `create` / `new`                   | `commands/create.md`          |
| `modify`                           | `commands/modify.md`          |
| `apply` / `run` / `do` / `go`     | `commands/apply.md`           |
| `apply-one-step` / `step`          | `commands/apply-one-step.md`  |
| `merge` / `submit`                 | `commands/merge.md`           |
| `archive`                          | `commands/archive.md`         |
| `init`                             | `commands/init.md`            |

### Routing Discipline

**You are a router, not an assistant.** After receiving a `/spex`
invocation, resolve a command and load the corresponding command file.
The user's prompt text is context to be forwarded as `$prompt` to the
command's SOP — never act on it directly.

- **NEVER** act on the user's prompt directly (no reading code, no
  writing files, no planning).
- **NEVER** skip or shortcut the SOP in the command file.
- **ALWAYS** load the full command markdown and follow every Phase
  exactly as written.

### Free-form Intent Inference

When the first argument does not match any route, infer intent using
these heuristics:

| If the user's text suggests...                      | Suggest command   |
|-----------------------------------------------------|-------------------|
| A new feature, requirement, or idea to implement    | `create`          |
| Changing requirements for an existing spec           | `modify`          |
| Starting implementation of a spec                    | `apply`           |
| Working through a spec one step at a time            | `apply-one-step`  |
| Finishing, merging, or submitting completed work     | `merge`           |
| Cleaning up completed specs                          | `archive`         |
| Setting up spex for the first time                   | `init`            |

- **Confidence ≥ 90%**: route directly with the free-form text as
  `$prompt`.
- **Confidence < 90%** or multiple commands plausible: use
  ask the user to confirm before routing.
- **Too vague** (e.g. just "help" or empty): show the Supported
  Commands table and stop.
