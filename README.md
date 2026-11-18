# Spex — A Skill & CLI for Spec-Driven Development

## What is Spex?

Spex, pronounced /speks/, is a coding agent skill and command-line tool for spec-driven software development, independent documentation, research, and other local deliverables.

Its core goal is to drive development through specs — first define what to build (create), then implement step by step (apply), and finally merge the result (merge).

### Key Terms

- **SDD (Spec-Driven Development)**: A methodology centered on "think first, then code" — capture requirements, design decisions, and implementation steps in a spec document before writing any code.
- **Spec**: The complete design artifact for a feature or requirement, including its description, technical approach, and development steps.
- **Coding Agent**: An AI programming assistant that can generate code from natural language descriptions. Examples include Claude Code, Cursor, Windsurf, Cline, etc.

### Three-Step Workflow

```bash
/spex create [requirement]  →  Create a spec (spec.md + todo.json)
/spex apply [spec]          →  Implement step by step
/spex merge [spec]          →  Merge the dev branch (auto-archive)
```

---

## 5-Minute Quick Start

Suppose you want to add a "user login" feature to your project. Here's how to build it with Spex.

### Step 1: Create a Spec

In your coding agent, type:

```bash
/spex create Add user login with email and password, return a JWT token on success
```

Spex generates three files:

- `spec.md` — The spec document, including requirements analysis, technical design, and file change plan.
- `todo.json` — A list of development steps, each with a step ID, name, and detailed description.
- `meta.json` — Spec metadata (original prompt, spec name, branches, author identity, etc.). Author name and email are used for commit attribution.

Use `spex show` to review the generated spec.

### Step 2: Develop

In your coding agent, type:

```bash
/spex apply
```

Spex will:

1. Automatically create a `spex/add-user-login` development branch.
2. Execute steps from `todo.json` one by one.
3. Automatically create a git commit after each step.
4. If interrupted (network loss, token throttling, task switch), the next `/spex apply` run automatically resumes from where it left off.

### Step 3: Merge

In your coding agent, type:

```bash
/spex merge
```

Spex merges the completed development branch into the main branch and archives the spec.

That's the core workflow: **create → apply → merge**.

---

## Installation

### Install via skills.sh

[skills.sh](https://www.skills.sh/) provides one-click skill installation. Install Spex using the `skills` CLI:

```bash
npx skills add jiangxin/spex
```

Or via full repository URL:

```bash
npx skills add https://github.com/jiangxin/spex
```

Once Spex reaches enough installations, it will be indexed on [skills.sh](https://www.skills.sh/) for direct search and installation.

### Project Structure

After installation, the skill files are organized under `skills/spex/`:

```
spex/
├── skills/
│   └── spex/
│       ├── SKILL.md          ← skill entry point
│       ├── commands/         ← sub-commands
│       ├── scripts/          ← executable scripts
│       ├── templates/        ← template files
│       └── references/       ← reference docs
├── README.md
├── README.zh.md
├── pyproject.toml
├── tests/
└── ...
```

### Post-Installation Setup

Open your coding agent tool and type `/spex init`. This will:

1. Create the `~/.spex.toml` configuration file.
2. Initialize the spec storage directory under `~/.spex/`.
3. Sync template files.
4. Install (symlink) the spex CLI to `~/.local/bin/`.

---

## Using the /spex Skill

In your coding agent, invoke the spex skill by typing commands that start with `/spex`.

The YAML front-matter in the skill file specifies that spex can only be triggered explicitly by the user — the model will never invoke it on its own, ensuring zero impact on the coding agent. For example:

```yaml
---
name: spex
disable-model-invocation: true
...
---
```

### Main Commands

- **`/spex create [requirement]`** — Convert your requirement into a spec document. Spex analyzes the requirement and generates `spec.md` (spec document) and `todo.json` (development step list). Use `spex show` to review after creation.

- **`/spex modify [spec-name] [changes]`** — Modify an existing spec. Updates the `todo.json` development steps, preserving completed steps while regenerating unfinished tasks.

- **`/spex review-plan [spec-name] [focus]`** — Review the spec and its development plan for gaps in coverage, dependency order, step size, and acceptance criteria. The review is read-only. Run the suggested `/spex modify` command manually to adopt the findings.

- **`/spex apply [spec-name]`** — Begin step-by-step implementation. Creates a local `spex/` branch from `meta.branch` (the project base recorded at create time), not from whatever HEAD you happen to be on. Use `spex list` to monitor progress during development.

- **`/spex apply-one-step [spec-name]`** — Same as `/spex apply`, but executes only one step at a time. Useful when you want fine-grained control over each step.

- **`/spex merge [spec-name]`** — Merge the completed spec into the main branch and auto-archive.

- **`/spex create`** refuses to switch away from a dirty working tree. If you are not on the recorded base branch and have uncommitted changes, Spex reports the dirty paths and stops instead of silently leaving work behind.

- **`/spex merge`** prints failure reasons to stderr as well as the JSON stdout, so the agent can report the cause without parsing machine output.

---

## Using the spex CLI

After installing the skill, run `/spex init` in your coding agent to set up the configuration and symlink the CLI to `~/.local/bin/` — make sure this path is in your PATH.

**Note**: The Spex CLI runs on Python 3.9+ using the standard library. Python 3.11+ is recommended for full TOML support.

### spex init

In addition to performing the same setup as the `/spex init` skill command, it also accepts a path argument to create `.spex.toml` and a local `.spex/` directory at the root of the specified repository.

### spex config

Display Spex configuration, including Git info, paths, config files, and the selected storage root.

```
── Git ───────────────────────────────────────────
  branch     = master
  remote_url =
  user_name  = Jiang Xin
  user_email = zhiyou.jx@alibaba-inc.com

── Paths ─────────────────────────────────────────
  cwd           = /Users/jiangxin/work/ai-native/spex
  top_workdir   = /Users/jiangxin/work/ai-native/spex
  main_worktree = /Users/jiangxin/work/ai-native/spex
  spex_root     = /Users/jiangxin/work/.spex

── Config ────────────────────────────────────────
  spex_root         = .spex
  branch_management = true
  main_branch_name  =
  submit_method     = merge
  step_review       = true
  use_git_worktree  = false

── Config Files ──────────────────────────────────
  /Users/jiangxin/work/ai-native/spex/.spex.toml
  /Users/jiangxin/.spex.toml
```

Config files are listed from highest to lowest priority. Spex uses one storage root for specs, custom templates, and hooks.

### spex list

Show in-progress specs. When run inside a repository, it shows specs for that repository; when run outside or with `--all-projects`, it shows specs from all projects.

```bash
spex list                    # Specs for the current repository
spex list -v                 # Include spec descriptions
spex list -vv                # Include step completion details
spex list --archives         # Archived specs
spex list --all-projects     # Specs from all projects
spex list --json             # JSON array on stdout (no matches → [] + exit 0)
```

### spex show

Display the detailed requirements, design, and development step plan for a given spec.

```bash
spex show [spec-name]
```

When stdout is a TTY, `spex show` pages the output by starting `$PAGER` as argv (default `less -R`), not via `/bin/sh -c`. Set `PAGER=cat` to disable paging. Shell metacharacters in `PAGER` are not interpreted.

### spex open

Open a specific spec directory, or the spex_root directory if no spec is specified.

```bash
spex open [spec-name]
spex open [spec-name] --run "ls -la"
```

`--run COMMAND` executes `COMMAND` as argv in the spec directory, not via `/bin/sh -c`. Pipelines and `&&` are not implicit; use `sh -c '...'` if you need a shell.

### spex archive

Archive completed specs (or restore from archives). Prefer `--json` for
machine-readable stdout (`dry_run` + `results[]`); human logs stay on
stderr. When a spec has `meta.spex_worktree`, archive removes that
linked worktree before moving the directory (it does not delete the
`spex/*` branch).

```bash
spex archive --json                     # Archive completed specs
spex archive <spec> --json              # Archive one spec by name
spex archive --json --dry-run           # Preview without moving
spex archive <spec> --json --restore
```

### spex merge

Merge a spec into the main branch and archive it. Same functionality as the `/spex merge` skill command. Merge runs in the worktree that already has the target trunk checked out, so a feature locked in a linked spex worktree does not block the trunk branch.

---

## Why Spex?

The community already had several spec-driven development tools before Spex, such as OpenSpec and spec-kit. So why build another one? Because in practice, adopting the SDD paradigm exposes pain points that existing tools don't address.

### 1. Resumable Long-Running Tasks

A complex requirement may need dozens of development steps. Interruptions happen frequently: network loss, token throttling, agent context overflow, etc. You need the ability to stop at any time and resume from where you left off.

Spex itself is developed using the SDD pattern. The output below from `spex list --archives` shows archived specs. Some requirements had 10 or more development steps:

```
📦   (8/8) 2026-06-16-17-16-improve-test-coverage  Improve test coverage by a...
📦 (10/10) 2026-06-15-11-47-rename-topic-to-spec   Normalize terminology: ren...
📦   (4/4) 2026-06-15-17-45-support-unborn-branch  Support unborn branch stat...
```

Here `(10/10)` means 10 steps total, all completed. Spex records each step's progress in `todo.json`, so you can pause and resume at any time.

As Anthropic's blog post ([Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)) points out, models are less likely to inappropriately change or overwrite JSON files compared to Markdown, making JSON a better format for tracking development steps. However, a problem emerged: when models directly modify `todo.json`, they tend to collapse step descriptions into terse single-line summaries instead of the rich multi-line Markdown needed for context, leading to a lack of detail and inconsistent code generation.

During development, other intermediate file formats were explored, such as XML. While XML can contain multi-line Markdown text for step descriptions, XML character escaping adds complexity. The final solution was the `spex todo-helper` utility, which uses heredoc input to provide detailed multi-line descriptions when adding new steps to `todo.json`. For example, the model invokes the following command to add a step:

```bash
$ spex todo-helper append "$spec_name" \
  --step-name "Short description" --details-from-stdin <<'DETAILS'
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

- Create `src/auth.py` with login endpoint
- Add input validation for email and password
- Write unit tests in `tests/test_auth.py`

**Acceptance criteria**: all tests pass, endpoint returns JWT
DETAILS
```

Pass spec names positionally after the command for direct CLI entries, after
the subcommand for `todo-helper`, `review-helper`, and `prompt`, or after
the template name for generic prompt rendering. For `run-hook`, pass the
optional spec name after the hook name. `todo-helper` accepts exactly one
locator, either a spec name or `--todo-file <path>`. The `create-helper`
and `apply-helper` lifecycle commands use `--name` for spec selection.

### 2. Atomic Commits: Small Steps, Fast Progress

Small batches (breaking a feature into multiple small development steps) are a cornerstone of high-quality development. This isn't just formalism — it's a well-established finding backed by both open-source practice and DevOps research:

- The author has contributed to the [Git project](https://github.com/git/git) for over 10 years, guided by the community's rigorous code review standards. The consensus: each commit should change one thing and stay under 100 lines.
- The [DORA 2025 Report](https://dora.dev/research/2025/) found that after introducing coding agents, developers tend to let AI generate large changes all at once, abandoning the small-batch practice. The result: coding speed increased, but overall software delivery efficiency actually declined.

Comparing two development processes (same 1500 lines of changes):

| | Good Process | Poor Process |
|---|---|---|
| Commit count | 20 commits, each under 100 lines | 1 commit, 1500 lines |
| Commit message examples | refactor: extract password validator<br>refactor: decouple user auth from session<br>feat: add email login endpoint<br>... | Complete user login feature |
| Review time | Refactoring commits reviewed in 2 min, logic commits reviewed individually | Reviewer spent 30 min and still couldn't follow the logic |

When using coding agents, models rarely follow the "one commit per step" practice on their own. Even when explicitly instructed to do so, they still tend to produce a single massive commit with hundreds or thousands of lines of changes.

Spex's solution: each development step in `todo.json` has two required
fields — `completed_at` (completion timestamp) and `commit_title`
(commit message title). For coding steps (default), the commit title is
filled in after a git commit is created, then the step is marked
complete after optional code review.

Optional per-step field `skip_commit` (`false` | `auto` | `true`;
default `false` / omit) covers non-coding work:

| `skip_commit` | Behavior |
|---------------|----------|
| `false` (default) | Must change the repo and commit; then review if `step_review` allows |
| `auto` | Commit only if the tree is dirty (excluding `$spex_root`); review only if a commit was created |
| `true` | Must leave the tree clean; no commit, empty `commit_title`, skip review; only set `completed_at` |

There is no per-step review flag. Global `step_review` in `.spex.toml`
still skips review for steps that did create a commit. Dirty checks use
the **whole working tree** (`git status --porcelain`), excluding paths
under `$spex_root` — not only files touched in the step. Start
`skip_commit=true` steps with a clean tree (excluding `$spex_root`).
After a coding-step commit, the tree (excluding `$spex_root`) must be
clean — leftover unstaged files poison later `true`/`auto` steps, so
apply SOPs STOP if residue remains. Values accept JSON bool
`true`/`false` or lowercase strings `"false"` | `"auto"` | `"true"`
(not `"True"` / `"AUTO"`).

When `step_review` is enabled and a step produced a commit, apply runs
an optimized Phase 6 review loop:

1. **Round 1 is always a full review** of the step commit.
2. **Batch fix**: all open findings from that pass are fixed by one
   sub-agent, one related lint/test check set, and one `git commit
   --amend` — not one agent/amend per finding.
3. **Minor-only**: after a successful batch fix, the step completes
   (Phase 7). No delta review and no second full review round.
4. **Any major**: after batch fix, Spex runs one **delta review** of
   the fix range. No new major → complete; new major → next full
   round (capped at three full rounds; never a fourth).
5. Findings are marked complete only after amend succeeds and HEAD
   verification passes. `step_review=false` with open majors is an
   abnormal STOP (not a silent skip).

Transaction commit assigns integer IDs in list order starting at 1.
Spex reads legacy string IDs by position and displays steps as
`step-<num>/<count>`. Use the current number with `--id` for edits and removals.

Example `todo.json` content:

```json
[
  {
    "id": 1,
    "name": "Update SKILL.md command routing and tables",
    "details": "Update SKILL.md to make `merge` the primary command...",
    "completed_at": "2026-06-17T12:08:42+08:00",
    "commit_title": "fae3c7c: docs: make merge the primary command..."
  },
  {
    "id": 2,
    "name": "Confirm docs-only checklist",
    "details": "Verify README wording without touching the repo.",
    "completed_at": "2026-06-17T12:20:00+08:00",
    "commit_title": "",
    "skip_commit": "true"
  }
]
```

### 3. Continuous Modification

Requirements change, and models may drift during requirements analysis, requiring human correction. For specs that have already been generated or are partially completed, Spex supports iterative modification via `/spex modify`. Each modification updates the `spec.md` design document while preserving completed steps in `todo.json`, regenerating only the unfinished portion.

### 4. Template Customization

Every team has its own standards: spec document format, commit message style, code review checklist, etc. Spex supports customizable templates — Markdown files rendered by the stdlib Spex template engine (`skills/spex/scripts/template.py`; dialect in `skills/spex/templates/AGENTS.md`). For example, the following snippet from `templates/apply-commit.md` shows how the `user_name` and `user_email` variables control the git commit command: when provided, the `-c` flag sets the commit author to match the spec's specified identity.

```markdown
{% if user_name and user_email -%}
- Use HereDoc to pass the commit message, and set the author identity
  to `{{ user_name }} <{{ user_email }}>`:

      git -c user.name="{{ user_name }}" \
          -c user.email="{{ user_email }}" \
          commit -F- <<'EOF'
      <commit message>
      EOF
{% else -%}
- Use HereDoc to pass the commit message:

      git commit -F- <<'EOF'
      <commit message>
      EOF
{% endif -%}
```

Create uses separate templates for writing the spec, providing its skeleton,
and planning tasks. The existing software skeleton remains compatible.

| Software | General | Purpose |
|---|---|---|
| `create-spec.md` | `general-create-spec.md` | Spec writing guidance with `prompt_context` and `spec_name` |
| `spec-template.md` | `general-spec-template.md` | Spec document skeleton |
| `create-todo.md` | `general-create-todo.md` | Task planning guidance with the saved `spec_content` and `spec_name` |

Spex looks for the mode-specific filename in the selected `spex_root/templates/`,
then uses the built-in file of that name as the fallback. Copy built-in examples
from `templates/examples/`. The template guide lists the full mapping for create,
modify, apply, commit, review, and fix. [Template guide](skills/spex/templates/AGENTS.md)

#### Task Modes

`/spex create` classifies the final deliverable as `software` for software
changes and their accompanying docs, or `general` for independent docs,
research, and other local outputs. Spex saves the mode in `meta.json`.
Legacy specs default to `software`. A change to the primary deliverable
that would change the mode requires a new spec.

Resolve repository-relative outputs within the bound workspace. Agree on
absolute paths or a base directory for external local outputs. Repository
outputs can be committed and reviewed. Read-only and external-only steps
default to `skip_commit: true` and require a clean Git worktree.

General steps save successful acceptance evidence with their completion.
Evidence can describe a command that exited successfully or an inspection
of an actual output. On resume, verify the recorded commit against HEAD
before completing committed work. An amended commit requires evidence for
its final SHA. Missing or failed checks leave the step unfinished.

### 5. Multi-Project Support

If you use Spex across multiple projects, you can store specs from different projects in the same `spex_root` directory. Each spec's `meta.json` records which project it belongs to. A shared spec pool across projects enables a powerful workflow: a single coding agent can autonomously pick a spec from the pool, enter the corresponding workspace, and develop asynchronously. Multiple coding agents can even process specs from different projects in parallel.

### 6. Branch Management

Managing branches while developing multiple features simultaneously can be challenging. Spex handles this automatically by default: each spec gets its own development branch with a `spex/` prefix, and merging automatically archives the spec. Branch descriptions are also set (via `git config branch.<name>.description`), so the merge commit message includes a summary of the requirement.

New spex branches are created from `meta.branch` (the base branch recorded when the spec was created; typically `main` / `master`), not from the current HEAD. That keeps `/spex apply --all` and back-to-back applies from carrying commits from one spec onto the next. If the recorded base is missing locally, Spex falls back to the current HEAD and logs a warning.

During the apply review loop, `apply-helper ensure-branch` re-attaches to the spec branch after a review/fix sub-agent. If HEAD is detached on a commit that is **not** an ancestor of that branch, ensure-branch exits with an error and prints a `git branch -f` recovery hint — it does not silently discard the detached commit.

#### Optional linked git worktree (`use_git_worktree`)

By default (`use_git_worktree = false`), apply switches the main checkout in place onto `spex/<name>`. You can opt in so each spec gets an isolated linked worktree instead — useful when you want to keep the IDE on the main checkout while the agent codes on the feature branch.

Enable in `.spex.toml` (or `~/.spex.toml`):

```toml
[spex]
use_git_worktree = true
```

Behavior:

| Concern | Detail |
|---------|--------|
| Scope | Global config is snapshotted into `meta.use_git_worktree` at **create** only. Changing the global flag later does not affect existing specs. Apply / merge / archive read **meta**, not the live config. |
| Path | `~/.spex/worktree/<repo_basename>/<spec_name>/` (under the user home; directory name `worktree` is singular). Independent of project `spex_root`. |
| Meta | `use_git_worktree` (bool, always written on create; missing key on old specs → `false`). `spex_worktree` (absolute path) is filled on first apply precheck when enabled; omitted when unused. |
| Apply | Creates or reuses the worktree; agents use `$spex_worktree` as coding `working_directory`. Does **not** switch the user's IDE root or create a multi-root workspace. |
| Merge | Merges in the worktree that already has the target trunk checked out — never switches into a trunk branch locked by the feature worktree. |
| Archive | Removes the linked worktree when `meta.spex_worktree` is set; still does not delete the `spex/*` branch. |
| Requires | `branch_management = true`. With branch management off, no feature branch and no spex worktree path. |

Known limits (first release):

- Ignored files (`.env`, local secrets) and dependency installs are **not** auto-synced into the linked worktree — copy or reinstall manually if needed.
- The IDE may stay on the main checkout while the agent works in `$spex_worktree` (dual-root). That is intentional; Spex only constrains the Agent cwd.
- Repo basename collisions under `~/.spex/worktree/` and a configurable worktree root are out of scope for now.

Spex itself is developed using the spex skill. The following `git log --merges` output shows how branch descriptions appear in merge commits:

```
59c5929 Merge branch 'spex/merge-as-primary-command'
  * spex/merge-as-primary-command:
  : Make merge the primary command with submit as its alias, updating
  : CLI routing, help text, and documentation
  docs: update READMEs to make merge the primary command
  docs: rename commands/submit.md to commands/merge.md
  docs: make merge the primary command with submit as alias in SKILL.md
```

Lines starting with `:` are branch descriptions, pulled from the spec's requirement summary.

---

## More Use Cases

### Storing Specs in the Repository

By default, Spex stores specs outside the repository (`~/.spex/`). This is because specs become outdated as development completes — **code is the single source of truth**.
Traditional engineering practice calls for good commit messages that describe why changes were made (the requirements) and the design approach, capturing the rationale behind each code snapshot.
Models can use `git blame` to trace any line back to its originating commit and understand the reasoning behind each change.

However, if you still want to keep specs in the repository, Spex supports that. Create a `.spex.toml` file at the repository root and set `spex_root`:

```toml
[spex]
spex_root = ".spex"
```

Then run `spex init .` (`.` refers to the current path) to create a `.spex` directory in the repository for storing generated spec documents.

**Note**: The created `.spex` directory contains a `.gitignore` file that ignores spec files by default, saving only templates and similar files to the repository.

### Configuration Inheritance

Spex searches for `.spex.toml` from the current directory upward, starting
from the main checkout when run in a linked Git worktree. Settings inherit
from parent files and `~/.spex.toml` by default. Set `inherit_config = false`
under `[spex]` to stop inheriting settings above that file.

Spec storage (`spex_root`) is resolved independently. At each level,
Spex uses an explicit `spex_root` and creates the directory when needed.
Without an explicit setting, it prefers an existing local `.spex` before
continuing upward. The final fallback is `~/.spex.toml`, with `~/.spex`
as the default.

### Platform Integration: Managing Specs Across Repositories

When integrating Spex into a development platform, you typically need centralized control over spec generation and execution across multiple repositories, rather than letting each repository configure itself. Spex supports the `SPEX_CONFIG_FILE` environment variable to specify a config file, bypassing any `.spex.toml` in the repo:

```bash
export SPEX_CONFIG_FILE=/path/to/platform-spex.toml
```

This lets the platform control the `spex_root` location, templates, and hooks centrally, ensuring specs from all repositories are stored and managed in one place.

With debug logging enabled, set `SPEX_LOG_DIR` to write CLI `debug.log` and
`trace.jsonl` into one directory. A relative directory is resolved from the
current working directory. Workflow anchors and review state remain with each spec.

```bash
export SPEX_LOG_DIR=/path/to/trial-logs
```

`SPEX_TRACE_FILE` takes precedence over the `trace_file` config setting.
Both override only `trace.jsonl`. Absolute paths are used as given.
Relative paths resolve under `SPEX_LOG_DIR` when set. Otherwise,
`SPEX_TRACE_FILE` resolves from the working directory and `trace_file`
resolves from `spex_root`.

### Customizing spex Templates

Run `spex config get spex_root` to find the selected storage directory.
Put custom templates in its `templates/` directory. Spex falls back to
built-in templates, which you can copy from `templates/examples/`.

### Customizing Hooks

Spex supports pre-action and post-action hooks. They are project-local (equivalent to git hooks): Spex runs a user-provided script from the project's spex_root, not remote code.

- **pre-action** — Triggered before an operation. A non-zero exit code aborts the operation. Use for permission checks, environment validation, etc.
- **post-action** — Triggered after an operation. Failures do not affect already-completed operations. Useful for notifications, telemetry, syncing with third-party platforms, etc.

The following operations trigger hooks:

| Operation | Event Type | pre-action | post-action |
|---|---|---|---|
| `/spex create` | create | After creating spec dir, before writing design content | After creation completes |
| `/spex modify` | modify | Before modifying spec content | After modification completes |
| `/spex apply` | apply | Before executing development steps | After all steps complete |
| `/spex merge` | merge | Before merge execution | After merge completes |

Each hook receives JSON-formatted event data via stdin. Hook scripts must:

- Live under the `hooks/` directory of a spex_root (filename is the hook type, e.g. `pre-action` or `post-action`)
- Be executable
- Not be a symlink that resolves outside that `hooks/` directory
- Not be world-writable

Unsafe hooks are skipped (treated as missing) with a warning.

---

## FAQ

### Python Version Requirement

Spex supports Python 3.9 and newer. On Python 3.9–3.10, the built-in parser supports single-level tables such as `[spex]`, bare keys, single-line strings, booleans, decimal integers, and comments. Use Python 3.11+ for configuration that uses arrays, inline tables, dotted keys, or multiline strings.

Check your version with `python3 --version`. macOS users can install a newer version via `brew install python`.

### spex command not found

Check if `~/.local/bin/` is in your PATH:

```bash
echo $PATH
```

If not, add to `~/.zshrc` or `~/.bashrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload: `source ~/.zshrc`.

### Spec creation fails

Run `spex config` to verify your configuration. Make sure the `spex_root` path exists and is writable.

### Branch conflicts

If `/spex apply` reports a branch name conflict, it means a branch with that name already exists. You can:

1. Use `spex show` to check the spec's current status.
2. Use `/spex apply` to continue development.
3. If the old branch is no longer needed, delete it with `git branch -D <branch-name>`.

### ensure-branch refused to re-attach

If apply stops because `apply-helper ensure-branch` failed on a detached HEAD, Spex is protecting a commit that is not an ancestor of the spec branch (for example an amend done while detached). Recover with the printed `git branch -f <spex-branch> <sha>` hint (or cherry-pick / recreate the fix on the branch), then re-run `/spex apply`.

### How to interrupt and resume development

- **Interrupt**: Simply stop `/spex apply`. Progress is saved in `todo.json`.
- **Resume**: Run `/spex apply` again. Spex automatically finds the first incomplete step and continues.
- **Check progress**: `spex list [spec-name]` to see how many steps are done.

---

## Development

- **Repository**: [https://github.com/jiangxin/spex](https://github.com/jiangxin/spex)
- `SKILL.md` is a routing file; logic is split across `commands/*.md`.
- Templates are in `templates/*.md`.
- Scripts are in `skills/spex/scripts/`, written in Python 3.9+.
- Run `make` to list available targets and `make check` before every commit.
- Markdown lint requires Node.js and `npx`. On first use, `npx` downloads the pinned linter into the npm cache. Python lint and tests need only Python.
- Test, coverage, Python lint, and format targets automatically initialize `.venv` with `skills/spex/[dev]` and use its Python without manual activation.
- Use `make dev-env PYTHON=python3.13` to choose the Python interpreter when creating `.venv`. Delete `.venv` before switching interpreters. Dependency installation is repeated when `skills/spex/pyproject.toml` changes; remove `.venv/.dev-ready` to force a reinstall.
- Run tests: `make test` (fast), `make test-all` (full, including slow tests).
