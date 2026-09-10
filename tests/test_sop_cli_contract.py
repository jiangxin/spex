"""SOP ↔ CLI contract gate (R3-F19 / S5).

Scan ``skills/spex/{SKILL.md,commands,references,templates}`` for
``scripts/spex …`` invocations in (1) fenced ``bash`` blocks, (2) inline
backticks, and (3) same-line ``CMD:`` bodies — then assert every subcommand
and flag exists on the real argparse parsers (reflection first; ``--help``
only as fallback). Templates are rendered with placeholder metadata first
so Jinja ``{{ var }}`` expands before scanning.
"""

from __future__ import annotations

import argparse
import importlib
import re
import shlex
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from common import strip_front_matter
from jinja2 import Template

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEX_ROOT = REPO_ROOT / "skills" / "spex"
SCRIPTS_DIR = SPEX_ROOT / "scripts"
SPEX_BIN = SCRIPTS_DIR / "spex"

# Illustrative-only snippets that are not real CLI invocations.
# Keyed by (posix relative path under skills/spex, normalised command tail).
ALLOWLIST: dict[tuple[str, str], str] = {
    # Style-guide ellipsis — documents the CMD shape, not a real call.
    (
        "references/compact-sop-style.md",
        "scripts/spex ...",
    ): "illustrative ellipsis in compact-sop-style guide",
}

FENCE_RE = re.compile(r"```bash\n(.*?)```", re.DOTALL | re.IGNORECASE)
# Inline `` `…scripts/spex…` `` (CMD: one-liners and prose hints).
INLINE_BACKTICK_RE = re.compile(r"`([^`]*scripts/spex[^`]*)`")
# Same-line ``CMD: …`` bodies (compact SOP style; may or may not be backticked).
CMD_INLINE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?CMD:\s+(.+)$", re.MULTILINE | re.IGNORECASE
)
# Match the literal ``scripts/spex`` token (ignore any ``$var/`` prefix).
SPEX_CORE_RE = re.compile(r"scripts/spex\b")
BRACKET_RE = re.compile(r"\[([^\]]+)\]")
HEREDOC_RE = re.compile(r"""<<\s*['"]?\w+['"]?""")
PLACEHOLDER_RE = re.compile(
    r"""^(?:\$[\w]+|"\$[\w]+"|'\$[\w]+'|<[^>]+>|\.\.\.)$"""
)
# Harvest options from --help; lookarounds use [\w-] (not [\\w-]).
_HELP_OPTION_RE = re.compile(r"(?<![\w-])(-\w|--[\w-]+)(?![\w-])")
_FRONT_MATTER_KEY_RE = re.compile(r"^  - (\w+)\s*$")
_UNQUOTED_NAME_RE = re.compile(r"""--name\s+\$spec_name\b""")

# Top-level commands that expose a nested subcommand (second positional).
NESTED_COMMANDS = frozenset({
    "apply-helper",
    "create-helper",
    "todo-helper",
    "review-helper",
    "prompt",
})


def _front_matter_keys(content: str) -> set[str]:
    """Collect keys listed under front-matter ``required`` / ``optional``."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return set()
    keys: set[str] = set()
    in_list = False
    for line in match.group(1).splitlines():
        if re.match(r"^(required|optional):\s*$", line):
            in_list = True
            continue
        if in_list:
            m = _FRONT_MATTER_KEY_RE.match(line)
            if m:
                keys.add(m.group(1))
                continue
            if line and not line.startswith(" "):
                in_list = False
    return keys


def _render_template_for_scan(path: Path) -> str:
    """Render a skill template with placeholder metadata for CLI scanning."""
    raw = path.read_text(encoding="utf-8")
    keys = _front_matter_keys(raw)
    # Truthy placeholders so ``{% if var %}`` blocks (and their bash fences)
    # are included; values look like shell placeholders to PLACEHOLDER_RE.
    meta = {k: f"${k}" for k in keys}
    body = strip_front_matter(raw)
    return Template(body).render(**meta)


def _sop_files() -> list[Path]:
    files = [SPEX_ROOT / "SKILL.md"]
    files.extend(sorted((SPEX_ROOT / "commands").glob("*.md")))
    files.extend(sorted((SPEX_ROOT / "references").glob("*.md")))
    files.extend(sorted((SPEX_ROOT / "templates").glob("*.md")))
    return [p for p in files if p.is_file()]


def _text_for_scan(path: Path) -> str:
    """Return file text ready for invocation extraction.

    Templates under ``skills/spex/templates/`` are Jinja-rendered with
    placeholder metadata first. Paths outside the skill tree (e.g. test
    fixtures) are read as plain text.
    """
    try:
        rel = path.relative_to(SPEX_ROOT).as_posix()
    except ValueError:
        return path.read_text(encoding="utf-8")
    if rel.startswith("templates/"):
        return _render_template_for_scan(path)
    return path.read_text(encoding="utf-8")


def _expand_line_continuations(block: str) -> str:
    return re.sub(r"\\\n[ \t]*", " ", block)


def _strip_heredoc(line: str) -> str:
    return HEREDOC_RE.sub("", line).strip()


def _expand_brackets(line: str) -> tuple[str, list[str]]:
    """Remove ``[...]`` segments; return cleaned line + flags found inside.

    Handles:
    - ``[--name <name>]`` → flag ``--name``
    - ``[-n|--dry-run]`` → flags ``-n``, ``--dry-run``
    - ``[--restore]`` → flag ``--restore``
    """
    extra_flags: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        # Alternation of short/long flags: -n|--dry-run or --foo|--bar
        if "|" in inner and "<" not in inner:
            for part in inner.split("|"):
                part = part.strip()
                if part.startswith("-"):
                    extra_flags.append(part)
            return ""
        # Tokenise remaining optional segment
        try:
            tokens = shlex.split(inner)
        except ValueError:
            tokens = inner.split()
        for tok in tokens:
            if tok.startswith("-"):
                extra_flags.append(tok)
            # skip placeholders / values
        return ""

    cleaned = BRACKET_RE.sub(_repl, line)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, extra_flags


def _append_invocation(
    results: list[tuple[str, str]], raw_line: str,
) -> None:
    """Normalise one candidate line; append (raw, tail) if it is a real call."""
    line = raw_line.split("#", 1)[0].strip()
    if not line or not SPEX_CORE_RE.search(line):
        return
    # Drop leading markdown list markers
    line = re.sub(r"^[-*]\s+", "", line)
    # Strip a single surrounding backtick pair (CMD: `` `…` `` forms)
    if len(line) >= 2 and line.startswith("`") and line.endswith("`"):
        line = line[1:-1].strip()
    m = SPEX_CORE_RE.search(line)
    if m is None:
        return
    # Keep from scripts/spex onward (drop $spex_skill_dir/ prefix)
    tail = _strip_heredoc(line[m.start() :]).rstrip(".,;:")
    # Skip bare prose mentions like `` `scripts/spex` `` (no subcommand).
    if not tail[len("scripts/spex") :].strip():
        return
    results.append((raw_line.strip(), tail))


def _extract_invocations(path: Path) -> list[tuple[str, str]]:
    """Return list of (raw_line, normalised_tail) for each scripts/spex call.

    Sources (deduped later by tail in ``_all_errors``):
    - fenced ``bash`` blocks
    - inline backticks outside fences
    - same-line ``CMD:`` bodies outside fences (non-backtick forms)

    Templates under ``templates/`` are Jinja-rendered first.
    """
    text = _text_for_scan(path)
    results: list[tuple[str, str]] = []

    for block in FENCE_RE.findall(text):
        expanded = _expand_line_continuations(block)
        for raw_line in expanded.splitlines():
            _append_invocation(results, raw_line)

    # Unfenced sources: strip fences so we do not re-parse their contents.
    no_fence = FENCE_RE.sub("", text)
    for match in INLINE_BACKTICK_RE.finditer(no_fence):
        _append_invocation(results, match.group(1))

    for match in CMD_INLINE_RE.finditer(no_fence):
        body = match.group(1).strip()
        if "scripts/spex" not in body:
            continue
        # Backtick-wrapped CMD bodies are already covered above.
        if body.startswith("`") and body.endswith("`"):
            continue
        _append_invocation(results, body)

    return results


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    opts: set[str] = set()
    for action in parser._actions:
        for opt in action.option_strings:
            opts.add(opt)
    return opts


def _subparsers_map(
    parser: argparse.ArgumentParser,
) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


@lru_cache(maxsize=None)
def _load_module(name: str):
    return importlib.import_module(name)


@lru_cache(maxsize=None)
def _load_spex_entry():
    """Load the ``spex`` entry script (no ``.py`` suffix)."""
    import importlib.util
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("spex_entry", str(SPEX_BIN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@lru_cache(maxsize=None)
def _parser_for_command(command: str) -> argparse.ArgumentParser:
    """Return the argparse parser for a top-level spex command."""
    builders = {
        "list": lambda: _load_module("list")._build_parser(),
        "init": lambda: _load_module("init")._build_parser(),
        "open": lambda: _load_module("open")._build_parser(),
        "show": lambda: _load_module("show")._build_parser(),
        "archive": lambda: _load_module("archive")._build_parser(),
        "config": lambda: _load_spex_entry()._build_config_parser(),
        "merge": lambda: _load_module("merge")._build_submit_parser(),
        "submit": lambda: _load_module("merge")._build_submit_parser(),
        "apply-helper": lambda: _load_module("apply_helper")._build_parser(),
        "create-helper": lambda: _load_module("create_helper")._build_parser(),
        "todo-helper": lambda: _load_module("todo_helper")._build_parser(),
        "review-helper": lambda: _load_module("review_helper")._build_parser(),
        "prompt": lambda: _load_module("prompt")._build_parser(),
        "meta-helper": lambda: _load_module("meta_helper")._build_parser(),
    }
    if command in builders:
        return builders[command]()
    # Fallback: parse --help from the real CLI
    return _parser_from_help(command)


@lru_cache(maxsize=None)
def _parser_from_help(command: str) -> argparse.ArgumentParser:
    """Last-resort: harvest option strings from ``spex <cmd> --help``."""
    from cli import ArgumentParser

    result = subprocess.run(
        [sys.executable, str(SPEX_BIN), command, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (result.stdout or "") + (result.stderr or "")
    if result.returncode not in (0, 2) and not text:
        raise AssertionError(
            f"cannot load parser for {command!r}: help exit {result.returncode}"
        )
    parser = ArgumentParser(prog=f"spex {command}")
    # Match long and short options listed in help text
    for opt in re.findall(_HELP_OPTION_RE, text):
        if opt in ("-h", "--help"):
            continue
        # Avoid duplicate add_argument for aliases discovered separately
        existing = _option_strings(parser)
        if opt in existing:
            continue
        parser.add_argument(opt, action="store_true", default=argparse.SUPPRESS)
    return parser


@lru_cache(maxsize=None)
def _known_top_level_commands() -> frozenset[str]:
    """Top-level command names from the spex entry registry + helpers."""
    return frozenset(_load_spex_entry()._ALL_COMMANDS)


def _tokenize(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def _is_flag(token: str) -> bool:
    return token.startswith("-") and token != "-"


def _is_placeholder(token: str) -> bool:
    return bool(PLACEHOLDER_RE.match(token))


def _resolve_invocation(
    command: str, tokens: list[str],
) -> tuple[str | None, list[str]]:
    """Return (subcommand_or_None, flag_tokens)."""
    parent = _parser_for_command(command)
    subs = _subparsers_map(parent)
    flags: list[str] = []
    subcmd: str | None = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _is_flag(tok):
            flags.append(tok)
            # Consume optional value if next token is not a flag / subcmd
            if i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if (
                    not _is_flag(nxt)
                    and not (subs and nxt in subs and subcmd is None)
                ):
                    i += 2
                    continue
            i += 1
            continue
        if _is_placeholder(tok):
            i += 1
            continue
        if subcmd is None and tok in subs:
            subcmd = tok
            i += 1
            continue
        if subcmd is None and command in NESTED_COMMANDS and subs:
            if not _is_flag(tok):
                subcmd = tok
                i += 1
                continue
        # positional — skip
        i += 1

    return subcmd, flags


def _combined_option_strings(
    command: str, subcmd: str | None,
) -> set[str]:
    parent = _parser_for_command(command)
    opts = _option_strings(parent)
    if subcmd:
        subs = _subparsers_map(parent)
        if subcmd in subs:
            opts |= _option_strings(subs[subcmd])
    # help is always valid
    opts |= {"-h", "--help"}
    return opts


def _check_invocation(rel: str, raw: str, tail: str) -> list[str]:
    """Return a list of error messages (empty if OK)."""
    key = (rel, tail)
    if key in ALLOWLIST:
        return []
    # Allowlist by prefix match on ellipsis-only tails
    if tail.rstrip().endswith("...") and (rel, "scripts/spex ...") in ALLOWLIST:
        return []

    cleaned, bracket_flags = _expand_brackets(tail)
    tokens = _tokenize(cleaned)
    if not tokens or tokens[0] != "scripts/spex":
        return [f"{rel}: cannot parse invocation: {raw!r}"]
    rest = tokens[1:]
    if not rest:
        return [f"{rel}: missing command after scripts/spex: {raw!r}"]

    command = rest[0].replace("_", "-")
    known = _known_top_level_commands()
    if command not in known:
        return [
            f"{rel}: unknown spex command {command!r} in: {raw!r}"
        ]

    # LLM-only surface commands have no real flag parser beyond the stub
    if command in ("apply", "create", "modify", "new"):
        # SOPs should not invoke these via scripts/spex; if they do, only
        # the command name is checked above.
        extra = [t for t in rest[1:] if _is_flag(t)] + bracket_flags
        if extra:
            return [
                f"{rel}: LLM-only command {command!r} has no CLI flags; "
                f"found {extra} in: {raw!r}"
            ]
        return []

    subcmd, flags = _resolve_invocation(command, rest[1:])
    all_flags = flags + bracket_flags

    if command in NESTED_COMMANDS:
        subs = _subparsers_map(_parser_for_command(command))
        if subcmd is None:
            return [
                f"{rel}: missing subcommand for {command!r} in: {raw!r}"
            ]
        if subcmd not in subs:
            return [
                f"{rel}: unknown {command} subcommand {subcmd!r} in: {raw!r}"
            ]

    opts = _combined_option_strings(command, subcmd)
    errors: list[str] = []
    for flag in all_flags:
        # Flag may be --foo=bar
        base = flag.split("=", 1)[0]
        if base not in opts:
            errors.append(
                f"{rel}: unknown flag {flag!r} for "
                f"spex {command}"
                + (f" {subcmd}" if subcmd else "")
                + f" in: {raw!r}"
            )
    return errors


def _all_errors() -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for path in _sop_files():
        rel = path.relative_to(SPEX_ROOT).as_posix()
        for raw, tail in _extract_invocations(path):
            key = (rel, tail)
            if key in seen:
                continue
            seen.add(key)
            errors.extend(_check_invocation(rel, raw, tail))
    return errors


class TestSopCliContract:
    def test_sop_invocations_match_real_cli(self):
        errors = _all_errors()
        assert not errors, "SOP↔CLI drift detected:\n" + "\n".join(errors)

    def test_extractor_finds_invocations(self):
        """Sanity: the scanner must see a non-trivial set of calls."""
        total = sum(len(_extract_invocations(p)) for p in _sop_files())
        assert total >= 30, f"expected ≥30 scripts/spex calls, got {total}"

    def test_extractor_finds_inline_cmd_and_backticks(self, tmp_path: Path):
        """Unfenced CMD:/backtick invocations must be scanned (r1-f2)."""
        sample = tmp_path / "inline.md"
        sample.write_text(
            "- CMD: `$spex_skill_dir/scripts/spex list --json --must-undone`\n"
            "- hint: `$spex_skill_dir/scripts/spex apply-helper "
            'post-action --name "$spec_name"`\n'
            "- CMD: $spex_skill_dir/scripts/spex archive --json --dry-run\n"
            "- prose mentions `scripts/spex` alone\n"
            "```bash\n"
            "$spex_skill_dir/scripts/spex list --json\n"
            "```\n",
            encoding="utf-8",
        )
        tails = {t for _, t in _extract_invocations(sample)}
        assert "scripts/spex list --json --must-undone" in tails
        assert (
            'scripts/spex apply-helper post-action --name "$spec_name"'
            in tails
        )
        assert "scripts/spex archive --json --dry-run" in tails
        assert "scripts/spex list --json" in tails
        assert "scripts/spex" not in tails

    def test_inline_sop_cmd_without_spec_name_validated(self):
        """Real apply.md one-liner must be checked (no $spec_name)."""
        path = SPEX_ROOT / "commands" / "apply.md"
        tails = {t for _, t in _extract_invocations(path)}
        assert "scripts/spex list --json --must-undone" in tails
        errors = _check_invocation(
            "commands/apply.md",
            'CMD: `$spex_skill_dir/scripts/spex list --json --must-undone`',
            "scripts/spex list --json --must-undone",
        )
        assert errors == []

    def test_detects_bogus_flag(self, tmp_path: Path):
        """Inject a fake flag and confirm the gate fails (self-check)."""
        sample = tmp_path / "bogus.md"
        sample.write_text(
            "```bash\n"
            "$spex_skill_dir/scripts/spex list --json --not-a-real-flag\n"
            "```\n",
            encoding="utf-8",
        )
        raw, tail = _extract_invocations(sample)[0]
        errors = _check_invocation("bogus.md", raw, tail)
        assert errors, "expected bogus flag to be rejected"
        assert any("--not-a-real-flag" in e for e in errors)

    def test_detects_bogus_flag_in_inline_cmd(self, tmp_path: Path):
        sample = tmp_path / "bogus-inline.md"
        sample.write_text(
            "- CMD: `$spex_skill_dir/scripts/spex list "
            "--json --not-a-real-flag`\n",
            encoding="utf-8",
        )
        inv = _extract_invocations(sample)
        assert inv, "inline CMD must be extracted"
        raw, tail = inv[0]
        errors = _check_invocation("bogus-inline.md", raw, tail)
        assert errors, "expected bogus inline flag to be rejected"
        assert any("--not-a-real-flag" in e for e in errors)

    def test_detects_bogus_subcommand(self, tmp_path: Path):
        sample = tmp_path / "bogus.md"
        sample.write_text(
            "```bash\n"
            "$spex_skill_dir/scripts/spex apply-helper not-a-real-sub --name x\n"
            "```\n",
            encoding="utf-8",
        )
        raw, tail = _extract_invocations(sample)[0]
        errors = _check_invocation("bogus.md", raw, tail)
        assert errors, "expected bogus subcommand to be rejected"
        assert any("not-a-real-sub" in e for e in errors)

    def test_bracketed_optional_flags_validated(self):
        raw = (
            '$spex_skill_dir/scripts/spex archive --json '
            "[--name <name>] [-n|--dry-run] [-f|--force] "
            "[--restore] [--all-projects]"
        )
        tail = "scripts/spex archive --json [--name <name>] [-n|--dry-run] " \
            "[-f|--force] [--restore] [--all-projects]"
        errors = _check_invocation("commands/archive.md", raw, tail)
        assert errors == []

    def test_nested_parent_flags_before_subcmd(self):
        raw = (
            '$spex_skill_dir/scripts/spex todo-helper --name "$spec_name" '
            'edit --id "$current_task_id" --commit-title "$commit_title"'
        )
        tail = (
            'scripts/spex todo-helper --name "$spec_name" edit '
            '--id "$current_task_id" --commit-title "$commit_title"'
        )
        errors = _check_invocation("references/apply-task-phases.md", raw, tail)
        assert errors == []

    def test_reflected_parsers_match_module_builders(self):
        """Gate must use live ``_build_parser`` — not hand-mirrored copies."""
        cases = {
            "archive": lambda: _load_module("archive")._build_parser(),
            "show": lambda: _load_module("show")._build_parser(),
            "config": lambda: _load_spex_entry()._build_config_parser(),
            "list": lambda: _load_module("list")._build_parser(),
        }
        for command, builder in cases.items():
            reflected = _option_strings(_parser_for_command(command))
            live = _option_strings(builder())
            assert reflected == live, (
                f"{command}: gate parser drifted from module builder "
                f"(gate={sorted(reflected)} live={sorted(live)})"
            )

    def test_help_option_regex_respects_word_boundaries(self):
        """Lookahead [\\w-] (not [\\\\w-]) blocks short-opt prefix matches."""
        text = (
            "  -v, --verbose   verbose mode\n"
            "  --dry-run       dry run\n"
            "  x--nope         prose noise\n"
            "  -verbose        not a short opt run-on\n"
        )
        found = _HELP_OPTION_RE.findall(text)
        assert "-v" in found
        assert "--verbose" in found
        assert "--dry-run" in found
        assert "--nope" not in found
        # Broken [\\w-] lookahead would accept -v from -verbose
        assert found.count("-v") == 1

    def test_archive_hidden_alias_visible_via_reflection(self):
        """``--not`` is help-suppressed; reflection must still see it."""
        reflected = _option_strings(_parser_for_command("archive"))
        from_help = _option_strings(_parser_from_help("archive"))
        assert "--not" in reflected
        assert "--not" not in from_help
        # Help harvest must not invent flags beyond the live parser.
        assert from_help - {"-h", "--help"} <= reflected

    def test_templates_included_in_sop_files(self):
        """Templates are under the SOP↔CLI gate (R4-F15 / S4)."""
        rels = {p.relative_to(SPEX_ROOT).as_posix() for p in _sop_files()}
        assert any(r.startswith("templates/") for r in rels)
        assert "templates/apply-fix.md" in rels
        assert "templates/apply-review.md" in rels
        assert "templates/modify-todo.md" in rels

    def test_spec_name_required_in_review_templates(self):
        """apply-fix / apply-review list spec_name under required."""
        for name in ("apply-fix.md", "apply-review.md"):
            raw = (SPEX_ROOT / "templates" / name).read_text(encoding="utf-8")
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
            assert match, f"{name}: missing front-matter"
            fm = match.group(1)
            required_block = re.search(
                r"required:\n((?:  - .+\n)+)", fm,
            )
            assert required_block, f"{name}: missing required list"
            required = {
                line.strip()[2:].strip()
                for line in required_block.group(1).splitlines()
                if line.strip().startswith("- ")
            }
            assert "spec_name" in required, f"{name}: spec_name not required"
            optional_block = re.search(
                r"optional:\n((?:  - .+\n)+)", fm,
            )
            if optional_block:
                optional = {
                    line.strip()[2:].strip()
                    for line in optional_block.group(1).splitlines()
                    if line.strip().startswith("- ")
                }
                assert "spec_name" not in optional, (
                    f"{name}: spec_name still optional"
                )

    def test_apply_review_template_full_and_delta_modes(self):
        """apply-review supports explicit full/delta modes and evidence reuse."""
        raw = (SPEX_ROOT / "templates" / "apply-review.md").read_text(
            encoding="utf-8",
        )
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
        assert match, "apply-review.md: missing front-matter"
        fm = match.group(1)
        optional_block = re.search(r"optional:\n((?:  - .+\n)+)", fm)
        assert optional_block
        optional = {
            line.strip()[2:].strip()
            for line in optional_block.group(1).splitlines()
            if line.strip().startswith("- ")
        }
        assert "review_mode" in optional
        assert "fix_base_commit_sha" in optional
        assert "fixed_commit_sha" in optional
        assert "check_evidence_reusable" in optional

        body = strip_front_matter(raw)
        assert "review_mode | default(mode | default('full')) == 'delta'" in body
        assert "focused review of the fix delta" in body
        assert "**Lint and tests**" in body
        assert "**Commit message quality**" in body
        assert "No new major" in body
        assert "New major" in body
        assert "Reuse the persisted lint/test evidence" in body
        assert "No reusable check evidence" in body
        assert "Do NOT append minor issues" in body

    def test_apply_fix_template_is_batch_amend(self):
        """apply-fix SOP: one batch, one check set, one amend; no pre-mark."""
        raw = (SPEX_ROOT / "templates" / "apply-fix.md").read_text(
            encoding="utf-8",
        )
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
        assert match, "apply-fix.md: missing front-matter"
        fm = match.group(1)
        required_block = re.search(r"required:\n((?:  - .+\n)+)", fm)
        assert required_block
        required = {
            line.strip()[2:].strip()
            for line in required_block.group(1).splitlines()
            if line.strip().startswith("- ")
        }
        assert "finding_ids" in required
        assert "finding_id" not in required
        assert "open_findings" in required

        body = strip_front_matter(raw)
        collapsed = re.sub(r"\s+", " ", body.lower())
        assert "complete finding batch" in collapsed
        assert "n findings" in collapsed
        assert "Amend exactly once" in body
        assert "Prohibit" in body or "prohibit" in body
        assert "processed_ids" in body
        assert "check_evidence" in body
        assert "new_head" in body
        assert "Do **not** mark findings complete" in body
        assert "complete-batch" in body
        assert "--completed-at" not in body
        # check_evidence checks must match normalize_check_evidence keys.
        assert '"completed_at"' in body
        assert "duration_ms" in body
        assert "finished_at" not in body
        # if/else amend fences plus Constraints prose mention.
        assert body.count("commit --amend") == 3
        # No review-helper edit bash that marks findings before amend.
        assert "edit --step" not in body

    def test_apply_fix_rendered_template_cli_contract(self):
        """Rendered apply-fix has no bogus spex flags; expands skill dir."""
        from prompt import render_prompt

        rendered = render_prompt(
            "apply-fix",
            extra_vars={
                "spec_content_concise": "# Spec\n",
                "current_task_description": "Do the work",
                "current_task_id": "step-1",
                "step_id": "step-1",
                "commit_sha": "deadbeef",
                "review_round": 1,
                "review_file": "/tmp/review.json",
                "spex_skill_dir": "/tmp/fake-skill",
                "open_findings": "- r1-f1: nit",
                "finding_ids": "r1-f1, r1-f2",
                "spec_name": "demo-spec",
                "user_name": "Test",
                "user_email": "t@example.com",
            },
        )
        assert "$spex_skill_dir" not in rendered
        assert "r1-f1, r1-f2" in rendered
        collapsed = re.sub(r"\s+", " ", rendered.lower())
        assert "complete finding batch" in collapsed
        assert "--completed-at" not in rendered
        assert "commit --amend" in rendered
        assert "Do **not** mark findings complete" in rendered
        assert "complete-batch" in rendered
        # Rendered body must not invoke review-helper edit/complete-batch.
        for block in FENCE_RE.findall(rendered):
            if "scripts/spex" in block:
                assert "edit" not in block
                assert "complete-batch" not in block

    def test_rendered_templates_have_no_literal_spex_skill_dir(self):
        """Jinja must expand spex_skill_dir — no surviving $spex_skill_dir."""
        from prompt import render_prompt

        # modify-todo is the template that previously left $spex_skill_dir
        rendered = render_prompt(
            "modify-todo",
            extra_vars={
                "spec_content": "# Spec\n",
                "spec_name": "demo-spec",
                "spex_skill_dir": "/tmp/fake-skill",
                "completed_tasks": "",
            },
        )
        assert "$spex_skill_dir" not in rendered
        assert "/tmp/fake-skill/scripts/spex" in rendered
        assert '--name "demo-spec"' in rendered

    def test_no_unquoted_name_spec_name_in_sop_or_templates(self):
        """cli-contract rule 4: --name \"$spec_name\", never bare $spec_name."""
        offenders: list[str] = []
        for path in _sop_files():
            text = path.read_text(encoding="utf-8")
            if _UNQUOTED_NAME_RE.search(text):
                rel = path.relative_to(SPEX_ROOT).as_posix()
                offenders.append(rel)
        assert not offenders, (
            "unquoted --name $spec_name in:\n" + "\n".join(offenders)
        )

    def test_apply_one_task_wraps_future_steps(self):
        """future_tasks_concise must live inside <future-steps>."""
        text = (SPEX_ROOT / "templates" / "apply-one-task.md").read_text(
            encoding="utf-8",
        )
        assert "<future-steps>" in text
        assert "</future-steps>" in text
        assert re.search(
            r"<future-steps>\s*\{\{\s*future_tasks_concise\s*\}\}\s*"
            r"</future-steps>",
            text,
        )
        assert "untrusted data" in text.lower() or "Fenced content" in text

    def test_detects_bogus_flag_in_template(self, tmp_path: Path):
        """Inject a fake flag into a template and confirm the gate fails."""
        sample = tmp_path / "bogus-template.md"
        sample.write_text(
            "---\nversion: \"0.0.0\"\nrequired:\n  - spex_skill_dir\n---\n\n"
            "```bash\n"
            "{{ spex_skill_dir }}/scripts/spex list --json --not-a-real-flag\n"
            "```\n",
            encoding="utf-8",
        )
        rendered = _render_template_for_scan(sample)
        # Mimic _extract_invocations on rendered text
        results: list[tuple[str, str]] = []
        for block in FENCE_RE.findall(rendered):
            expanded = _expand_line_continuations(block)
            for raw_line in expanded.splitlines():
                _append_invocation(results, raw_line)
        assert results, "expected rendered template invocation"
        raw, tail = results[0]
        errors = _check_invocation("templates/bogus-template.md", raw, tail)
        assert errors, "expected bogus template flag to be rejected"
        assert any("--not-a-real-flag" in e for e in errors)
