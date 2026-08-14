# Changelog

## Unreleased

### Bug Fixes

- **W007 credential handling** — skill router instructions redact
  secrets before assigning `$prompt`, so user text is not passed
  through unchanged.
- **Local execution hardening** — confine remaining local execution:
  hooks must live under spex_root `hooks/` (executable, no outside
  symlinks, not world-writable); `open --run` and `show` start
  argv rather than `/bin/sh -c`; `init` installs only this skill's
  declared deps from the local skill dir plus official PyPI.

## 0.7.0

### Refactoring

- **pyproject.toml relocation** — move `pyproject.toml` from project root
  to `skills/spex/` for skill self-containment and npx distribution.

### Documentation

- **Agent-agnostic image handling** — update `spex create` and `spex
  modify` commands to use agent-agnostic image handling references.
- Update `README.md` and `README.zh.md` examples to list multiple coding
  agents supported by Spex.

## 0.5.0

### Refactoring

- **Skill layout restructure** — move all skill files to `skills/spex/`
  directory for npx distribution. Update all path references across
  scripts, tests, and configuration to match the new layout.

### Features

- **Target branch auto-detection** — add `resolve_default_branch()` for
  probing the repository's default branch instead of hardcoding `main`.
  The merge command now auto-detects the target branch.

### Bug Fixes

- **Dependency installation** — add multi-fallback strategy for `spex
  init` dependency installation when primary methods fail.
- **Makefile path fixes** — use `$(PYTHON) -m module` for pip and pytest
  to avoid path resolution issues.

### Documentation

- Update `README.md` and `README.zh.md` with `skills/spex/` structure
  and install guide.

### Testing

- Update test paths to reflect `skills/spex/` script location.

## 0.4.1

### Features

- **Python 3.9 compatibility** — lower `requires-python` from 3.11 to
  3.9. Use `tomli` backport as a conditional dependency for Python < 3.11,
  with graceful fallback when neither `tomllib` nor `tomli` is installed
  (prints a hint to run `spex init`).

### Testing

- **Speed up test suite** — mark subprocess-based tests as
  `@pytest.mark.slow` across test\_prompt, test\_common, test\_init,
  test\_branch, test\_hooks, test\_merge, and test\_cli. Add
  `pytest-xdist` for parallel execution (`-n auto`). Fast suite
  (`make check`) drops from ~51s to ~12s; full suite (`make check-all`)
  from ~115s to ~71s.

### Bug Fixes

- **Remote URL fallback** — `get_project_context()` now falls back to
  the first available git remote when `origin` does not exist, fixing
  empty `remote_url` in `meta.json` for repos with non-standard remote
  names.

## 0.4.0

### Features

- **Pre-action hooks** — add `run_pre_action` convenience wrapper and
  call pre-action hooks in `create`, `apply`, `merge`, and `modify`
  commands. Unify pre-action and post-action hook parameters. Add error
  handling to abort operations when pre-action hooks return non-zero.
- **`modify` pre-action** — add `--pre-action` flag to `meta-helper` so
  the modify command triggers a pre-action hook before writing changes.
- **Distinguish hook event types** — `merge` and `submit` now emit
  distinct event types in hook payloads.
- **Unborn branch support** — use `symbolic-ref` to detect unborn
  branches; create target branch if missing before merging.

### Bug Fixes

- Fix "Spec Roots" label in `spex config` output (was "Spec Roots",
  now "Spex Roots").
- Fix `create_branch` renamed to `create_and_switch_branch` using
  `git switch -c` for correctness.

### Documentation

- Rewrite `README.md` (English) and `README.zh.md` (Chinese) as a
  technical blog post covering the motivation and design of Spex.
- Make `merge` the primary command with `submit` as its alias in
  SKILL.md, CLI routing, and documentation.

### Testing

- Improve test coverage across the board: CLI (54% → 99%),
  meta\_helper (27% → 97%), version (31% → 96%), prompt (31% → 60%),
  init (71% → 87%), show/branch/merge (90–95%).
- Add `coverage-all` Makefile rule for full coverage reporting.

### Refactoring

- Delegate branch detection to `get_current_branch` in config module.

## 0.3.0

### Features

- **`todo-helper` subcommand** — full JSON CRUD (`prepare`, `show`,
  `edit`, `mark-done`/`edit`, `remove-undone`); XML format support with
  `xml2json`/`json2xml` converters; `--completed_at now` expansion.
- **`create-helper` subcommands** — `prepare-spec` replaces
  `create-topic`; auto-switch to main branch on mismatch; hint for
  `spex-prefix` error; `add-images` subcommand for multimodal support;
  post-action hook with JSON validation.
- **`modify` overhaul** — `todo-helper` replaces `xml2json` workflow;
  split todo prompt and step generation into separate phases;
  `--remove-undone` flag; concise task formatting.
- **`list` filters** — `--must-done`/`--must-undone` status filters;
  `--json` output; `--archives` and `--all-projects` replace `--all`;
  pattern matching filter.
- **`show` improvements** — optional topic argument with interactive
  selection; default verbose output with pager; `--archives` and
  `--all-projects` flags with archive fallback.
- **`merge` (submit)** — auto-select topic when none provided;
  `-n/--dry-run` flag; auto-archive after successful merge.
- **`init` dry-run** — `-n/--dry-run` flag to preview operations;
  template sync results always shown; spex_root creation in verbose output.
- **`archive` restore** — `--not` flag to restore topics from archives;
  `--all-projects` for cross-project archival.
- **`open --run`** — execute commands in topic directory.
- **`get-topic` archives** — `--with-archives` flag to search archives;
  default to no status filtering.
- **ProjectContext** — new `ProjectContext` dataclass with
  `is_related_to()`, `in_git_workdir()`, unified config resolution.
- **Topic dataclass** — display-oriented `Topic` and `TopicMeta`
  dataclasses with `from_dir()` factory.
- **Logging migration** — all scripts migrate to `logger.info/warning/error`;
  stdout reserved for programmatic data; `-d/--debug` replaces `-v/--verbose`.
- **Argparse migration** — all subcommands use `ArgumentParser` with
  `add_subparsers`; unified `-h/--help` across all commands.
- **Sub-agent boundaries** — removed in `create`, `modify`, `apply-one-step`;
  consolidated into single phase in `apply`.
- **User identity in commits** — conditional author/committer in apply-commit.
- **Prompt improvements** — `_trim_spec_content` for concise spec extraction;
  HTML section markers in spec template; verbose formatting for task context.
- **`meta` CLI** — `get` mode to display `meta.json`; fuzzy matching via
  `resolve_topic_dir`.
- **Concise spec content** — `_trim_spec_content` with dual
  include/exclude strategy; marker preservation.

### Bug Fixes

- Fix `apply --all` listing cross-project specs instead of project specs.
- Fix variable name `$name` from parsed JSON in `create` command.
- Fix `todo-helper --name` conflict with `spec --name` by renaming to
  `--step-name`.
- Fix literal backslash-n handling in `wrap_text`.
- Fix `create` to require single-line description.
- Fix image detection for pasted images in `create` and `modify`.
- Fix `show` auto-fallback to archives without `--archives` flag.
- Fix subcommand help flags (`-h/--help`) before topic resolution.
- Fix `todo-helper` showing subcommand-specific help.
- Fix description formatting in `meta.json` at 68 chars.
- Fix redundant git author in apply-commit template.
- Fix `init` template sync: duplicate calls, dry-run output, spex_root resolution.
- Exit code 1 when no topics found.
- Print "No specs found." to stderr instead of stdout.
- Isolate `TestCliRouting` tests from real working directory.
- Prevent `GIT_CONFIG_PARAMETERS` leak in test_hooks.
- Allow `user_name`/`user_email` from global git config.

### Refactoring

- **topic → spec rename** — comprehensive rename of all topic-related
  variables, functions, CLI flags (`--topic` → `--name`), JSON fields,
  and documentation to use "spec" terminology.
- **Script renaming** — single-word scripts renamed to match subcommands.
- **`cli.py`** — normalize subcommand names to accept hyphens/underscores;
  `spex` main entry to argparse with grouped help; `submit` renamed to `merge`.
- **Remove deprecated code** — `spex todo` command, `remove-undone`
  subcommand, `SpexContext`/`get_context`/`get_git_info`;
  `check_help_flag` from `common.py`.
- **Consolidate shared utilities** — `find_completed_specs`,
  `has_active_branch`, `same_path`, topic selection functions from `show.py`.
- **`config.py` defaults** — `branch_management` default changed to `true`;
  comment-out TOML values matching defaults.
- **`prompt.py`** — router pattern with extracted handlers for
  `modify-spec`, `apply-commit`, `apply-one-task`, `create-helper`.
- **`archive.py`** — generalized `move_topic` for bidirectional use;
  `--not` flag renamed to `--restore`; `--all` renamed to `--all-topics`.
- **`branch.py`** — extract `submit/merge` CLI logic to `merge.py`;
  replace `--topic` with positional argument.
- **`open` rewrite** — use shared topic selection functions.
- **`create` SOP** — use `todo-helper` CLI for `todo.json` generation;
  direct JSON output instead of XML conversion.

## 0.2.1

### Bug Fixes

- Fix dead code in `branch.py` (`check=True` with unreachable returncode
  check) and `config.py` (`safe_update_toml` missing file existence guard).
- Fix `check_help_flag` calls missing `argv` parameter in 4 todo scripts.
- Remove dead `try/except` in `show_topic.py`; differentiate `--details`
  vs default output in `parse_todo.py`.
- Replace `sys.exit(0)` in `render_prompt` with return value, making it
  safe to call as a library function.
- Use `atomic_write_json` in `create_topic_dir.py` for consistent writes.
- Refuse to archive incomplete topics without `--force`.
- Match topics by `main_worktree` in addition to `workdir`.

### Features

- `spex init` accepts a target directory argument.
- `spex init -v/--verbose` shows detailed operations.
- `spex init` safe-updates `~/.spex.toml` with latest config schema.
- Record `main_worktree` from SpexContext in `meta.json`.

### Refactoring

- Consolidate `_get_git_info()` into `common.get_git_info()`.
- Consolidate `_escape_xml_text()` into `common.escape_xml_text()` and
  `common.escape_xml_preserving_entities()`.
- Add shared `load_and_validate_todo_json()` and `validate_unique_ids()`
  to `common.py`.
- Unify topic resolution with shared `find_matching_topics()` helper.
- Eliminate `sys.path.insert` boilerplate via package structure.
- Change `get_specs_dir()`/`get_archives_dir()` to return `Path` objects.
- Rename `create-topic-dir.py` to `create_topic_dir.py`; add
  `from __future__ import annotations` to all scripts.
- Standardize argument parsing with `cli.ArgumentParser`.

## 0.2.0

### Features

- **Dynamic default config** — `generate_default_toml()` produces the
  default `.spex.toml` from `_CONFIG_SCHEMA`, keeping comments and
  defaults in sync with the code.
- **Chinese README** — add `README.zh.md`; both language versions must
  be kept consistent per `AGENTS.md`.

### Changes

- Rename `create_branch` config key to `branch_management`.
- Add `[spex]` section header to config schema.
- Rename `package.json` to `package.dev.json` (symlinked via
  `make setup`) to avoid conflicts with Alibaba internal skill
  publishing platform. (Later reverted: skill moved to `skills/spex/`,
  no longer conflicts with root `package.json`.)
- Rewrite `README.md` with highlights, full command reference (skill
  and CLI), installation via skills.sh, and improved configuration
  docs.
- Add user-friendly progress messages to Makefile rules; include
  `pip install -e '.[dev]'` in `make setup`.
- Require Python 3.11+ (for `tomllib` stdlib support).

## 0.1.0

### Features

- **`config` command** — rename `get` to `config` with expanded variable
  display; add `--spex-roots`, `--spex-toml`, `--spex-tomls` flags;
  `SPEX_CONFIG_FILE` env var and `--spex-config-file` flag
- **Configuration system** — migrate from `.spex.yaml` to `.spex.toml`;
  hierarchical `.spex.toml` discovery with upward walk; `SpexContext` for
  centralized config resolution; per-level `spex_root` for multi-root lookup;
  user-level config at `~/.spex/config.toml`
- **Branch management** — branch utility module with create, validate, and
  post-action phases; `submit` command for merging feature branches with
  auto-archive; branch integration in `create`, `apply`, `apply-one-step`
- **Hooks system** — `hooks.py` module with resolution and execution logic;
  `run-hook` CLI subcommand; post-action hooks in `submit` and `xml2json todo`
- **`apply-one-step` command** — new command (alias: `step`) for single-task
  execution
- **`show` command** — detailed topic display with emoji, progress, and
  verbose mode
- **`archive` enhancements** — `--topic` flag for single-topic archival with
  partial name matching; `--force`/`-f` flag to bypass branch guard
- **`init` enhancements** — create `.spex.toml` during init; hooks directory
  setup
- **`list` enhancements** — `-v`/`--verbose` multi-level detail; show spec
  description; word-wrap and bracket formatting
- **`todo` enhancements** — `xml2json` converter; `json2xml` reverse
  conversion; `remove-undone` subcommand; `--rm` flag to delete XML after
  conversion
- **Prompt / template system** — Jinja2 template rendering via `prompt`
  command; `modify-spec`, `modify-todo`, `apply-one-task`, `apply-commit`
  templates; `--json` output mode; `--stdin` flag for raw prompt injection;
  future-tasks context and all-done detection
- **CLI enhancements** — `ArgumentParser` wrapper for consistent argument
  handling; `-h`/`--help` support across all subcommands; intent inference and
  routing discipline; `merge` alias for `submit`
- **Worktree support** — resolve main worktree for linked worktrees and
  submodules; `top_workdir` and `main_worktree` helpers
- **Template sync** — version-based comparison replacing mtime-based sync;
  layered template resolution order

### Bug Fixes

- Fix `main_worktree` resolution for shared repo state in config and branch
- Fix `--event-type` value parsing in `xml2json`
- Fix unescaped XML special characters in `xml2json` and `json2xml`
- Fix duplicate step ID guard in `xml2json` append mode
- Fix template sync with mtime/size pre-check before version comparison
- Fix `has_undone_tasks` check for exact topic match in `get-topic`
- Fix `--all` mode loop behavior and subagent workdir in `apply`

### Breaking Changes

- Remove `SPEX_ROOT` env var and `--spex-root` CLI option (use `.spex.toml`)
- Remove `install-cli` command (replaced by `spex init`)
- Remove `list` subskill command (use `spex list` CLI)
- Migrate config format from `.spex.yaml` to `.spex.toml`

## 0.0.1

Initial release.

- Core CLI (`spex`) with command dispatch
- Commands: `create`, `list`, `modify`, `apply`, `archive`, `open`, `install`
- Spec topic management: `create-topic`, `get-topic`, `meta`, `todo`
- Template system with built-in/custom template support
- `.spex.yaml` config file support (repo, XDG, home)
- `--spex-root` global option and `SPEX_ROOT` env override
- Relative and `~/` path resolution for `spex_root`
- `--version` / `spex version` support
