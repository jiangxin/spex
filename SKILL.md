---
name: spex
disable-model-invocation: true
description: "Spec-Driven Development (Spex) skill for creating and managing specification documents. Invoked manually via /spex <command>. Supports commands: create (new), modify, apply (run, do, go), apply-one-step (step), submit (merge), archive, init."
metadata:
  version: 0.1.0
arguments:
  - name: command
    required: false
    description: "Sub-command to execute. Must be one of: create (alias: new), modify, apply (aliases: run, do, go), apply-one-step (alias: step), submit (alias: merge), archive, init. If omitted, infer intent from the remaining text and ask user to confirm."
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
| `create`   | `new`            | Create a spec document (no code changes) |
| `modify`   |                  | Modify a spec's requirements      |
| `apply`    | `run`, `do`, `go`| Apply a spec to generate code     |
| `apply-one-step` | `step`    | Apply one step from a spec's todo list |
| `submit`   | `merge`          | Submit completed work (merge or PR) |
| `archive`  |                  | Archive a completed spec          |
| `init`     |                  | Initialize spex environment       |

## Command Routing

`$spex_skill_dir` refers to the directory where this SKILL.md resides.

Parse the first argument as `<command>` and route to the corresponding
command file:

- `create` / `new` → `commands/create.md`
- `modify` → `commands/modify.md`
- `apply` / `run` / `do` / `go` → `commands/apply.md`
- `apply-one-step` / `step` → `commands/apply-one-step.md`
- `submit` / `merge` → `commands/submit.md`
- `archive` → `commands/archive.md`
- `init` → `commands/init.md`

### ⚠️ CRITICAL — Routing Discipline

**You are a router, not an assistant.** Your ONLY job after receiving
a `/spex` invocation is to resolve a command and load the corresponding
command file. The user's prompt text (e.g. "I want to add a login
feature") is NOT an instruction for you to act on — it is merely
context to be forwarded as `$prompt` to the command's SOP.

- **NEVER** act on the user's prompt directly (no reading code, no
  writing files, no planning).
- **NEVER** skip or shortcut the SOP in the command file.
- **ALWAYS** load the full command markdown and follow every Phase
  exactly as written.

The only valid outputs are: (a) a command file's SOP execution,
(b) an AskUserQuestion for intent resolution, or (c) the usage table.
Anything else is a routing failure.

---

### Constraints

1. If the first argument matches a route above, you MUST load the
   corresponding command markdown file and follow its procedure
   step-by-step exactly as written. Do NOT interpret the user's prompt
   directly or skip loading the command file.

2. If the first argument does not match any route, treat the remaining
   text as a free-form prompt. Infer the user's intent and ask the user
   to confirm which command to run, then execute the selected command
   with the free-form text as the `$prompt` argument. Use the following
   intent-matching heuristics:

   | If the user's text suggests... | Suggest command |
   |---|---|
   | A new feature, requirement, or idea to implement | `create` |
   | Changing requirements for an existing spec | `modify` |
   | Starting implementation of a spec | `apply` |
   | Working through a spec one step at a time | `apply-one-step` |
   | Finishing, merging, or submitting completed work | `submit` |
   | Cleaning up completed specs | `archive` |
   | Setting up spex for the first time | `init` |

   If a single command is clearly implied, offer it as the recommended
   option with the user's text as context. If multiple commands are
   plausible, present 2-3 options for the user to choose from. If the
   text is too vague (e.g. just "help" or empty), show the usage table
   and stop.

3. The user MUST confirm or select a command before execution. Never
   auto-execute on inferred intent.
