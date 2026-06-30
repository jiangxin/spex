# Spex — A Skill & CLI for Spec-Driven Development

## What is Spex?

Spex, pronounced /speks/, is a coding agent skill and command-line tool that helps developers manage the full software development lifecycle using SDD (Spec-Driven Development).

Its core goal is to drive development through specs — first define what to build (create), then implement step by step (apply), and finally merge the result (merge).

### Key Terms

- **SDD (Spec-Driven Development)**: A methodology centered on "think first, then code" — capture requirements, design decisions, and implementation steps in a spec document before writing any code.
- **Spec**: The complete design artifact for a feature or requirement, including its description, technical approach, and development steps.
- **Coding Agent**: An AI programming assistant (such as Claude Code) that can generate code from natural language descriptions.

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
npx skills add https://github.com/jiangxin/spex
```

Once Spex reaches enough installations, it will be indexed on [skills.sh](https://www.skills.sh/) for direct search and installation.

### Post-Installation Setup

Open your coding agent tool and type `/spex init`. This will:

1. Install Python dependencies.
2. Create the `~/.spex.toml` configuration file.
3. Initialize the spec storage directory under `~/.spex/`.
4. Sync template files.
5. Install (symlink) the spex CLI to `~/.local/bin/`.

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

- **`/spex apply [spec-name]`** — Begin step-by-step implementation. Creates a local branch with the `spex/` prefix by default. Use `spex list` to monitor progress during development.

- **`/spex apply-one-step [spec-name]`** — Same as `/spex apply`, but executes only one step at a time. Useful when you want fine-grained control over each step.

- **`/spex merge [spec-name]`** — Merge the completed spec into the main branch and auto-archive.

---

## Using the spex CLI

After installing the skill, run `/spex init` in your coding agent to set up the configuration, install Python dependencies, and symlink the CLI to `~/.local/bin/` — make sure this path is in your PATH.

**Note**: The spex CLI requires Python 3.9+. Ensure it is installed on your system.

### spex init

In addition to performing the same setup as the `/spex init` skill command, it also accepts a path argument to create `.spex.toml` and a local `.spex/` directory at the root of the specified repository.

### spex config

Display spex configuration, including Git info, paths, config file list, and spex roots.

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

── Config Files ──────────────────────────────────
  /Users/jiangxin/work/ai-native/spex/.spex.toml
  /Users/jiangxin/.spex.toml

── Spex Roots ────────────────────────────────────
  /Users/jiangxin/work/.spex
  /Users/jiangxin/.spex
```

There can be multiple config files and spex root directories, listed in order from highest to lowest priority. Higher-priority configs override lower-priority values, and templates and hooks in higher-priority directories override same-named files in lower-priority directories.

### spex list

Show in-progress specs. When run inside a repository, it shows specs for that repository; when run outside or with `--all-projects`, it shows specs from all projects.

```bash
spex list                    # Specs for the current repository
spex list -v                 # Include spec descriptions
spex list -vv                # Include step completion details
spex list --archives         # Archived specs
spex list --all-projects     # Specs from all projects
spex list --json             # JSON format output
```

### spex show

Display the detailed requirements, design, and development step plan for a given spec.

```bash
spex show [spec-name]
```

### spex open

Open a specific spec directory, or the spex_root directory if no spec is specified.

### spex archive

Archive a completed spec.

### spex merge

Merge a spec into the main branch and archive it. Same functionality as the `/spex merge` skill command.

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
$ spex todo-helper --name $spec_name append \
  --id step-1 --step-name "Short description" --details-from-stdin <<'DETAILS'
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

- Create `src/auth.py` with login endpoint
- Add input validation for email and password
- Write unit tests in `tests/test_auth.py`

**Acceptance criteria**: all tests pass, endpoint returns JWT
DETAILS
```

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

Spex's solution: each development step in `todo.json` has two required fields — `completed_at` (completion timestamp) and `commit_title` (commit message title). The commit title can only be filled in after a git commit is created, marking the step as complete. Example `todo.json` content:

```json
[
  {
    "id": "step-1",
    "name": "Update SKILL.md command routing and tables",
    "details": "Update SKILL.md to make `merge` the primary command...",
    "completed_at": "2026-06-17T12:08:42+08:00",
    "commit_title": "fae3c7c: docs: make merge the primary command..."
  }
]
```

### 3. Continuous Modification

Requirements change, and models may drift during requirements analysis, requiring human correction. For specs that have already been generated or are partially completed, Spex supports iterative modification via `/spex modify`. Each modification updates the `spec.md` design document while preserving completed steps in `todo.json`, regenerating only the unfinished portion.

### 4. Template Customization

Every team has its own standards: spec document format, commit message style, code review checklist, etc. Spex supports customizable templates — Markdown files rendered with the Jinja2 template engine. For example, the following snippet from `templates/apply-commit.md` shows how the `user_name` and `user_email` variables control the git commit command: when provided, the `-c` flag sets the commit author to match the spec's specified identity.

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

Templates are located in the `templates/` directory:

| Template File | Purpose |
|---|---|
| `spec-template.md` | Spec document template |
| `modify-spec.md` | Prompt template for modifying existing specs |
| `modify-todo.md` | Prompt template for modifying `todo.json` |
| `apply-one-task.md` | Prompt template aggregating spec and current task |
| `apply-commit.md` | Prompt template for generating commits |

You can create replacement templates in `~/.spex/templates/` to override the built-in templates.

### 5. Multi-Project Support

If you use Spex across multiple projects, you can store specs from different projects in the same `spex_root` directory. Each spec's `meta.json` records which project it belongs to. A shared spec pool across projects enables a powerful workflow: a single coding agent can autonomously pick a spec from the pool, enter the corresponding workspace, and develop asynchronously. Multiple coding agents can even process specs from different projects in parallel.

### 6. Branch Management

Managing branches while developing multiple features simultaneously can be challenging. Spex handles this automatically by default: each spec gets its own development branch with a `spex/` prefix, and merging automatically archives the spec. Branch descriptions are also set (via `git config branch.<name>.description`), so the merge commit message includes a summary of the requirement.

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

### Platform Integration: Managing Specs Across Repositories

When integrating Spex into a development platform, you typically need centralized control over spec generation and execution across multiple repositories, rather than letting each repository configure itself. Spex supports the `SPEX_CONFIG_FILE` environment variable to specify a config file, bypassing any `.spex.toml` in the repo:

```bash
export SPEX_CONFIG_FILE=/path/to/platform-spex.toml
```

This lets the platform control the `spex_root` location, templates, and hooks centrally, ensuring specs from all repositories are stored and managed in one place.

### Customizing spex Templates

Run `spex config` to see the `spex_roots` path list, pick a template directory (e.g., `~/.spex/templates/`), and create replacement template files. You can copy templates from `templates/examples/` as a starting point.

### Customizing Hooks

Spex supports pre-action and post-action hooks:

- **pre-action** — Triggered before an operation. A non-zero exit code aborts the operation. Use for permission checks, environment validation, etc.
- **post-action** — Triggered after an operation. Failures do not affect already-completed operations. Useful for notifications, telemetry, syncing with third-party platforms, etc.

The following operations trigger hooks:

| Operation | Event Type | pre-action | post-action |
|---|---|---|---|
| `/spex create` | create | After creating spec dir, before writing design content | After creation completes |
| `/spex modify` | modify | Before modifying spec content | After modification completes |
| `/spex apply` | apply | Before executing development steps | After all steps complete |
| `/spex merge` | merge | Before merge execution | After merge completes |

Each hook receives JSON-formatted event data via stdin. Hook scripts are placed in the `hooks/` directory under `spex_root`, with the filename matching the hook type. They must have execute permissions.

---

## FAQ

### Python Version Requirement

The Spex CLI requires Python 3.9+. Check with `python3 --version`. macOS users can install via `brew install python`.

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
- Run tests: `make test` (fast), `make test-all` (full, including slow tests).
