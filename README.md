# SDD — Spec-Driven Development Skill

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that brings spec-driven development to your projects. Manage specification documents with progress tracking while keeping specs outside the repository — avoiding two sources of truth (code and specs).

## Why

In many projects, keeping specification documents alongside code creates a maintenance burden: the code evolves but specs go stale, leaving two conflicting sources of truth. SDD solves this by storing specs in a sibling hidden directory (e.g., `.my-app.spec/`) outside the git repository, so specs serve as living planning artifacts without polluting the codebase.

## Usage

This skill is invoked manually — it does **not** auto-trigger via LLM detection. Use the `/sdd` slash command:

```
/sdd <command> [arguments...]
```

## Commands

| Command   | Description                              |
|-----------|------------------------------------------|
| `create`  | Create a new spec document               |
| `list`    | List specs with status and metadata      |
| `apply`   | Apply a spec to generate implementation  |
| `archive` | Archive a completed spec                 |

### `/sdd create <spec-name> [description]`

Creates a new spec file with structured frontmatter (title, status, created date) and standard sections (Overview, Requirements, Design, Implementation Notes).

### `/sdd list [--status <status>]`

Lists all specs in a formatted table showing name, status (`draft` / `active` / `completed` / `archived`), and created date. Supports filtering by status.

### `/sdd apply <spec-name>`

Applies a spec to drive implementation — translating requirements and design into code changes.

### `/sdd archive <spec-name>`

Marks a spec as `archived`, stamps the archive date, and moves it into an `archived/` subdirectory.

## Spec Storage

Specs are stored **outside** the project repository in a sibling hidden directory:

```
/Users/alice/projects/
├── my-app/              ← your project (git repo)
└── .my-app.spec/        ← spec directory (not in git)
    ├── feature-auth.md
    ├── api-redesign.md
    └── archived/
        └── old-feature.md
```

This convention ensures specs never conflict with your codebase and won't appear in pull requests or CI pipelines.

## Installation

Clone or copy this skill into your Claude Code skills directory:

```bash
# Global installation
cp -r sdd-skill ~/.claude/skills/sdd

# Or project-local installation
cp -r sdd-skill .claude/skills/sdd
```

## License

MIT
