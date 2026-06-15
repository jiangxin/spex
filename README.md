# Spex — Spec-Driven Development Skill

Spex is a skill that brings
spec-driven development to your projects. It can save specification documents
with progress tracking while keeping specs outside the repository — avoiding
two sources of truth (code and specs). Users can customize the storage directory
and prompt templates to match their team's conventions.

## Highlights

- **Full spec lifecycle** — create, modify, apply, submit, and archive specs
  with a single `/spex` command.
- **Harness for long-running tasks** — implementation is planned as JSON
  steps; each step commits on completion and stamps a timestamp in
  `todo.json`, enabling pause/resume and progress visibility.
- **Small batches** — each step is scoped to ~200 lines of change and
  must be committed before the next step begins, preventing oversized
  commits and keeping reviews manageable.
- **Customizable templates** — Jinja2 templates for spec documents, task
  prompts, and commit messages; override per-project or globally.
- **Flexible storage & hierarchical config** — specs live outside the repo
  by default (`~/.spex/`); `.spex.toml` config loads at project, user, and
  system levels with nearest-wins merging, and `SPEX_CONFIG_FILE` overrides
  all discovery. Each level can set its own `spex_root` to control where
  specs are stored.
- **Branch management** — optionally create and switch `spex/<name>` branches
  per spec, with auto-merge or PR submission.
- **Worktree & submodule aware** — specs are anchored to the main worktree,
  so all worktrees share a single spec store; submodules are also supported.
- **Fuzzy name matching** — all commands accept partial spec names with
  interactive disambiguation.
- **Hooks** — extensible `post-action` hooks receive JSON events on stdin
  for create, modify, apply, and submit actions — useful for telemetry,
  notifications, or automating pull request creation.
- **CLI + skill** — use `/spex` inside your coding agent or the standalone
  `spex` CLI for listing, showing, and managing specs.

## Usage

This skill is invoked manually — it does **not** auto-trigger via LLM detection.
Use the `/spex` slash command in two ways:

- **Free-form prompt** — let the LLM determine intent:

  ```
  /spex <natural language prompt>
  ```

- **Explicit subcommand** — directly load a specific skill template:

  ```
  /spex <command> [arguments...]
  ```

### Commands

| Command         | Aliases            | Description                              |
|-----------------|--------------------|------------------------------------------|
| `create`        | `new`              | Create a new spec document (no code changes) |
| `modify`        |                    | Modify a spec's requirements             |
| `apply`         | `run`, `do`, `go`  | Apply a spec to generate code            |
| `apply-one-step`| `step`             | Apply one step from a spec's todo list   |
| `submit`        | `merge`            | Submit completed work (merge or PR)      |
| `archive`       |                    | Archive a completed spec                 |
| `init`          |                    | Initialize spex environment              |

#### `/spex create <spec-name> [description]`

Creates a new spec file according to the configured template and standard
sections (Overview, Requirements, Design, Implementation Notes).

#### `/spex modify <spec-name>`

Modifies the requirements of an existing spec.

#### `/spex apply <spec-name>`

Applies a spec to drive implementation — translating requirements and
design into code changes.

#### `/spex apply-one-step <spec-name>`

Applies a single step from the spec's todo list, then stops.

#### `/spex submit <spec-name>`

Submits completed work by merging the branch or creating a pull request,
depending on the `submit_method` config option.

#### `/spex archive <spec-name>`

Marks a spec as `archived`, stamps the archive date, and moves it into an
`archived/` subdirectory.

#### `/spex init`

Initializes the spex environment — creates the config file, spec storage
directory, and default templates.

### CLI commands

Running `/spex init` inside your coding agent installs the standalone `spex`
CLI to `~/.local/bin`. The CLI provides commands that run without an
AI agent:

| Command          | Description                                      |
|------------------|--------------------------------------------------|
| `spex list`      | List specs with status and progress               |
| `spex show`      | Show summary info for a spec                      |
| `spex open`      | Open a spec directory in the system file browser  |
| `spex config`    | Display resolved configuration                   |
| `spex archive`   | Archive completed specs                           |
| `spex init`      | Initialize spex environment                       |

#### `spex list`

Lists all specs with status icons and progress ratios:

- `spex list` — compact view: spec name, status, and progress (e.g.,
  `3/5`).
- `spex list -v` — adds the spec description.
- `spex list -vv` — adds individual step listing with completion status.
- `spex list --all-projects` — includes specs from all repositories,
  not just the current one.

#### `spex show <name>`

- `spex show <name>` — shows the full spec content and structured
  todo with step-level details.
- `spex show -l <name>` — brief list format (status, dates,
  branch, progress).

## Configuration

Spex uses `.spex.toml` files for configuration. On first run, a default
config and spec directory are created in the user's home directory:

- `~/.spex.toml` — global config
- `~/.spex/` — default spec storage (with `specs/`, `archives/`,
  `templates/` subdirectories)

### Config file discovery

Spex searches for `.spex.toml` from the git repository root **upward**
to the filesystem root, then falls back to `~/.spex.toml`. When
multiple files are found, they are merged with the nearest file taking
highest priority. Use `spex config` to inspect the resolved config
files, settings, and spec storage directories:

```bash
spex config
```

To override all discovery, set the `SPEX_CONFIG_FILE` environment
variable to an explicit path:

```bash
export SPEX_CONFIG_FILE=/path/to/custom.toml
```

### Config options

All options live under the `[spex]` section:

```toml
[spex]
# Root directory for spec storage
# spex_root = ".spex"

# Create and manage branches for specs
# branch_management = true

# Restrict spec creation to this branch
# main_branch_name = ""

# How to submit completed work: merge or pr
# submit_method = "merge"
```

| Key                 | Type   | Default    | Description                                                                |
|---------------------|--------|------------|----------------------------------------------------------------------------|
| `spex_root`         | string | `".spex"`  | Spec storage directory (relative to the `.spex.toml` location, or absolute)|
| `branch_management` | bool   | `true`     | Automatically create/switch branches per spec                              |
| `main_branch_name`  | string | `""`       | Only allow spec creation on this branch (empty = any)                      |
| `submit_method`     | string | `"merge"`  | How to submit completed work: `merge` or `pr`                              |

### Scoping with `spex_root`

When a `.spex.toml` sets `spex_root`, it governs the directory where
that file lives **and all child directories**. This lets you use
different spec roots at different levels:

```
/home/alice/
├── .spex.toml              ← spex_root = ".spex" (global default)
├── .spex/                  ← global specs
└── projects/
    └── my-app/             ← git repo
        ├── .spex.toml      ← spex_root = "specifications" (project-level)
        └── specifications/ ← project-local specs
```

**Common setups:**

- **Global only** (default): specs stored in `~/.spex/`, shared across
  all projects.
- **Per-project**: can create `.spex/` in the repo root to keep specs
  alongside the project, and optionally add `.spex.toml` to override
  defaults.
- **CI/build override**: set `SPEX_CONFIG_FILE` to point at a
  build-specific config, bypassing all `.spex.toml` discovery.

## Installation

Install via [skills.sh](https://www.skills.sh/) (for Claude Code):

```bash
npm install -g skills@latest
npx skills add jiangxin/spex
```

Or clone the repository manually:

```bash
git clone https://github.com/jiangxin/spex ~/.agents/skills/spex

# For Claude Code
ln -s ~/.agents/skills/spex ~/.claude/skills/spex
```

## Development

### Prerequisites

- Python 3.11+
- Node.js (for markdownlint and husky)

### Setup

```bash
make setup
```

This installs Python dev dependencies (ruff, pytest, pytest-cov) in
editable mode, creates the `package.json` symlink, and runs `npm install`
to set up [husky](https://typicode.github.io/husky/) git hooks. The npm
config file is named `package.dev.json` (symlinked to `package.json`) to
avoid conflicts with the Alibaba internal skill publishing platform.
These tools are used for quality assurance — linting, testing, and
pre-commit checks.

### Available Make Targets

| Command          | Description                                  |
|------------------|----------------------------------------------|
| `make setup`     | Create package.json symlink and npm install   |
| `make lint`      | Run ruff linter on Python files               |
| `make lint-md`   | Run markdownlint on Markdown files            |
| `make format`    | Auto-format Python files with ruff            |
| `make test`      | Run pytest unit tests (fast tier)             |
| `make test-all`  | Run all tests including slow tests            |
| `make check`     | Run all checks (lint + lint-md + test)        |
| `make check-all` | Run all checks including slow tests           |
| `make coverage`  | Run tests with coverage report                |

### Pre-commit Hooks

This project uses husky to enforce quality checks before each commit:

- **pre-commit**: Runs `make check` (ruff lint, markdownlint, pytest)
  — commits are blocked if any check fails.
- **commit-msg**: Injects a co-developed-by trailer for AI-assisted
  commits.

These hooks are installed automatically via `make setup`.

## License

MIT
