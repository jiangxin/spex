# Changelog

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
  publishing platform.
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
