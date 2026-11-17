"""Minimal Spex template engine (stdlib-only; Jinja-subset for skill templates).

Dialect is documented in ``skills/spex/templates/AGENTS.md``. Keep that file,
this module, and on-disk templates in sync.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


class TemplateError(Exception):
    """Raised when a Spex template cannot be parsed or rendered."""


class _Undefined:
    """Sentinel for missing context keys (falsy; prints as empty)."""

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return ""


_UNDEFINED = _Undefined()

_TAG_RE = re.compile(r"(\{\{.*?\}\}|\{%-?\s*.*?\s*-?%\})", re.DOTALL)
_INTERP_RE = re.compile(r"^\{\{\s*(.*?)\s*\}\}$", re.DOTALL)
_TAG_OPEN_RE = re.compile(r"^\{%-?\s*(.*?)\s*-?%\}$", re.DOTALL)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

ALLOWED_FILTERS = frozenset({"default", "int"})
FORBIDDEN_TAG_WORDS = frozenset({
    "for", "endfor", "set", "macro", "endmacro", "include", "extends",
    "block", "endblock", "raw", "endraw", "call", "filter", "with",
})


# ---------------------------------------------------------------------------
# Template AST
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Text:
    value: str


@dataclass(frozen=True)
class _Interp:
    expr: str


@dataclass(frozen=True)
class _IfBranch:
    condition: Optional[str]  # None => else; "__endif__" => endif marker
    body: list
    strip_before: bool
    strip_after: bool


@dataclass(frozen=True)
class _IfBlock:
    branches: list  # conditional/else branches + trailing __endif__ marker


# ---------------------------------------------------------------------------
# Expression AST
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _EName:
    name: str


@dataclass(frozen=True)
class _EConst:
    value: Any


@dataclass(frozen=True)
class _EUnary:
    op: str
    expr: Any


@dataclass(frozen=True)
class _EBin:
    op: str
    left: Any
    right: Any


@dataclass(frozen=True)
class _EFilter:
    expr: Any
    name: str
    args: tuple


# ---------------------------------------------------------------------------
# Lex / parse template structure
# ---------------------------------------------------------------------------


def _split_tokens(source: str) -> list:
    parts: list = []
    pos = 0
    for match in _TAG_RE.finditer(source):
        if match.start() > pos:
            parts.append(_Text(source[pos:match.start()]))
        raw = match.group(0)
        if raw.startswith("{{"):
            inner = _INTERP_RE.match(raw)
            if not inner:
                raise TemplateError(f"Invalid interpolation: {raw!r}")
            parts.append(_Interp(inner.group(1).strip()))
        else:
            strip_left = raw.startswith("{%-")
            strip_right = raw.endswith("-%}")
            inner = _TAG_OPEN_RE.match(raw)
            if not inner:
                raise TemplateError(f"Invalid tag: {raw!r}")
            body = inner.group(1).strip()
            parts.append({
                "body": body,
                "strip_before": strip_left,
                "strip_after": strip_right,
            })
        pos = match.end()
    if pos < len(source):
        parts.append(_Text(source[pos:]))
    return parts


def _tag_word(body: str) -> str:
    return body.split(None, 1)[0] if body else ""


def _parse_nodes(
    tokens: list, start: int = 0, stop_words: frozenset = frozenset(),
) -> tuple[list, int]:
    nodes: list = []
    i = start
    while i < len(tokens):
        tok = tokens[i]
        if isinstance(tok, (_Text, _Interp)):
            nodes.append(tok)
            i += 1
            continue
        body = tok["body"]
        word = _tag_word(body)
        if word in stop_words:
            return nodes, i
        if word in FORBIDDEN_TAG_WORDS:
            raise TemplateError(f"Unsupported tag: {body!r}")
        if word == "if":
            block, i = _parse_if(tokens, i)
            nodes.append(block)
            continue
        if word in ("elif", "else", "endif"):
            raise TemplateError(f"Unexpected tag at this position: {body!r}")
        raise TemplateError(f"Unsupported tag: {body!r}")
    return nodes, i


def _parse_if(tokens: list, i: int) -> tuple[_IfBlock, int]:
    tok = tokens[i]
    body = tok["body"]
    if _tag_word(body) != "if":
        raise TemplateError(f"Expected if tag, got {body!r}")
    condition = body[2:].strip()
    if not condition:
        raise TemplateError("Empty if condition")
    branches: list = []
    i += 1
    while True:
        strip_before = tok["strip_before"]
        strip_after = tok["strip_after"]
        inner, i = _parse_nodes(tokens, i, frozenset({"elif", "else", "endif"}))
        branches.append(_IfBranch(condition, inner, strip_before, strip_after))
        if i >= len(tokens) or not isinstance(tokens[i], dict):
            raise TemplateError("Unclosed if block (missing endif)")
        tok = tokens[i]
        next_body = tok["body"]
        word = _tag_word(next_body)
        if word == "elif":
            condition = next_body[4:].strip()
            if not condition:
                raise TemplateError("Empty elif condition")
            i += 1
            continue
        if word == "else":
            if next_body.strip() != "else":
                raise TemplateError(f"Invalid else tag: {next_body!r}")
            i += 1
            strip_before = tok["strip_before"]
            strip_after = tok["strip_after"]
            inner, i = _parse_nodes(tokens, i, frozenset({"endif"}))
            branches.append(_IfBranch(None, inner, strip_before, strip_after))
            if i >= len(tokens) or not isinstance(tokens[i], dict):
                raise TemplateError("Unclosed if block (missing endif)")
            end = tokens[i]
            if _tag_word(end["body"]) != "endif" or end["body"].strip() != "endif":
                raise TemplateError("Expected endif after else")
            branches.append(_IfBranch(
                "__endif__", [], end["strip_before"], end["strip_after"],
            ))
            return _IfBlock(branches), i + 1
        if word == "endif":
            if next_body.strip() != "endif":
                raise TemplateError(f"Invalid endif tag: {next_body!r}")
            branches.append(_IfBranch(
                "__endif__", [], tok["strip_before"], tok["strip_after"],
            ))
            return _IfBlock(branches), i + 1
        raise TemplateError(f"Expected elif/else/endif, got {next_body!r}")


def _parse(source: str) -> list:
    tokens = _split_tokens(source)
    nodes, i = _parse_nodes(tokens, 0)
    if i != len(tokens):
        raise TemplateError("Unexpected trailing template tags")
    return nodes


# ---------------------------------------------------------------------------
# Expression parse / eval
# ---------------------------------------------------------------------------


def _skip_ws(src: str, pos: int) -> int:
    while pos < len(src) and src[pos].isspace():
        pos += 1
    return pos


def _is_keyword_at(src: str, pos: int, word: str) -> bool:
    n = len(word)
    if not src.startswith(word, pos):
        return False
    end = pos + n
    if end < len(src) and (src[end].isalnum() or src[end] == "_"):
        return False
    if pos > 0 and (src[pos - 1].isalnum() or src[pos - 1] == "_"):
        return False
    return True


def _parse_primary(src: str, pos: int) -> tuple[Any, int]:
    pos = _skip_ws(src, pos)
    if pos >= len(src):
        raise TemplateError("Unexpected end of expression")
    ch = src[pos]
    if ch in ("'", '"'):
        quote = ch
        pos += 1
        start = pos
        while pos < len(src) and src[pos] != quote:
            pos += 1
        if pos >= len(src):
            raise TemplateError("Unterminated string literal")
        return _EConst(src[start:pos]), pos + 1
    if ch.isdigit() or (ch == "-" and pos + 1 < len(src) and src[pos + 1].isdigit()):
        m = re.match(r"-?\d+", src[pos:])
        assert m is not None
        return _EConst(int(m.group(0))), pos + len(m.group(0))
    if ch == "(":
        expr, pos = _parse_or_expr(src, pos + 1)
        pos = _skip_ws(src, pos)
        if pos >= len(src) or src[pos] != ")":
            raise TemplateError("Expected ')'")
        return expr, pos + 1
    m = _IDENT.match(src, pos)
    if not m:
        raise TemplateError(
            f"Unexpected token in expression near {src[pos:pos + 20]!r}"
        )
    return _EName(m.group(0)), m.end()


def _parse_filtered(src: str, pos: int) -> tuple[Any, int]:
    expr, pos = _parse_primary(src, pos)
    while True:
        pos = _skip_ws(src, pos)
        if pos >= len(src) or src[pos] != "|":
            return expr, pos
        pos = _skip_ws(src, pos + 1)
        m = _IDENT.match(src, pos)
        if not m:
            raise TemplateError("Expected filter name after '|'")
        fname = m.group(0)
        if fname not in ALLOWED_FILTERS:
            raise TemplateError(f"Unsupported filter: {fname!r}")
        pos = _skip_ws(src, m.end())
        args: list = []
        if pos < len(src) and src[pos] == "(":
            pos += 1
            while True:
                pos = _skip_ws(src, pos)
                if pos < len(src) and src[pos] == ")":
                    pos += 1
                    break
                arg, pos = _parse_or_expr(src, pos)
                args.append(arg)
                pos = _skip_ws(src, pos)
                if pos < len(src) and src[pos] == ",":
                    pos += 1
                    continue
                if pos < len(src) and src[pos] == ")":
                    pos += 1
                    break
                raise TemplateError("Expected ',' or ')' in filter arguments")
        expr = _EFilter(expr, fname, tuple(args))


def _parse_not_expr(src: str, pos: int) -> tuple[Any, int]:
    pos = _skip_ws(src, pos)
    if _is_keyword_at(src, pos, "not"):
        inner, pos = _parse_not_expr(src, pos + 3)
        return _EUnary("not", inner), pos
    return _parse_filtered(src, pos)


def _parse_compare(src: str, pos: int) -> tuple[Any, int]:
    left, pos = _parse_not_expr(src, pos)
    pos = _skip_ws(src, pos)
    for op in ("==", "!=", ">=", "<=", ">", "<"):
        if src.startswith(op, pos):
            right, pos = _parse_not_expr(src, pos + len(op))
            return _EBin(op, left, right), pos
    return left, pos


def _parse_and_expr(src: str, pos: int) -> tuple[Any, int]:
    left, pos = _parse_compare(src, pos)
    while True:
        pos = _skip_ws(src, pos)
        if not _is_keyword_at(src, pos, "and"):
            return left, pos
        right, pos = _parse_compare(src, pos + 3)
        left = _EBin("and", left, right)


def _parse_or_expr(src: str, pos: int) -> tuple[Any, int]:
    left, pos = _parse_and_expr(src, pos)
    while True:
        pos = _skip_ws(src, pos)
        if not _is_keyword_at(src, pos, "or"):
            return left, pos
        right, pos = _parse_and_expr(src, pos + 2)
        left = _EBin("or", left, right)


def _parse_expression(src: str) -> Any:
    text = src.strip()
    if not text:
        raise TemplateError("Empty expression")
    tree, pos = _parse_or_expr(text, 0)
    pos = _skip_ws(text, pos)
    if pos != len(text):
        raise TemplateError(f"Unexpected trailing input in expression: {text[pos:]!r}")
    return tree


def _truthy(value: Any) -> bool:
    return bool(value)


def _stringify(value: Any) -> str:
    if value is _UNDEFINED or isinstance(value, _Undefined):
        return ""
    if value is None:
        return "None"
    return str(value)


def _cmp_norm(value: Any) -> Any:
    if value is _UNDEFINED or isinstance(value, _Undefined):
        return ""
    return value


def _num(value: Any) -> float:
    if value is _UNDEFINED or isinstance(value, _Undefined):
        raise TemplateError("Cannot compare undefined value")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if value == "" or value is None:
        return 0
    try:
        text = str(value)
        return float(text) if "." in text else int(text)
    except (TypeError, ValueError) as exc:
        raise TemplateError(f"Cannot compare non-numeric value {value!r}") from exc


def _apply_filter(name: str, value: Any, args: list) -> Any:
    if name == "default":
        if len(args) != 1:
            raise TemplateError("default filter requires exactly one argument")
        if value is _UNDEFINED or isinstance(value, _Undefined):
            return args[0]
        return value
    if name == "int":
        if args:
            raise TemplateError("int filter takes no arguments")
        # Match Jinja2: undefined raises; failed conversion returns 0.
        if value is _UNDEFINED or isinstance(value, _Undefined):
            raise TemplateError("int filter: value is undefined")
        if value == "" or value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    raise TemplateError(f"Unsupported filter: {name!r}")


def _eval_tree(tree: Any, ctx: dict) -> Any:
    if isinstance(tree, _EConst):
        return tree.value
    if isinstance(tree, _EName):
        if tree.name not in ctx:
            return _UNDEFINED
        return ctx[tree.name]
    if isinstance(tree, _EUnary):
        if tree.op == "not":
            return not _truthy(_eval_tree(tree.expr, ctx))
        raise TemplateError(f"Unknown unary op {tree.op}")
    if isinstance(tree, _EBin):
        if tree.op == "and":
            left = _eval_tree(tree.left, ctx)
            return _eval_tree(tree.right, ctx) if _truthy(left) else left
        if tree.op == "or":
            left = _eval_tree(tree.left, ctx)
            return left if _truthy(left) else _eval_tree(tree.right, ctx)
        left = _eval_tree(tree.left, ctx)
        right = _eval_tree(tree.right, ctx)
        if tree.op == "==":
            return _cmp_norm(left) == _cmp_norm(right)
        if tree.op == "!=":
            return _cmp_norm(left) != _cmp_norm(right)
        lv, rv = _num(left), _num(right)
        if tree.op == ">=":
            return lv >= rv
        if tree.op == ">":
            return lv > rv
        if tree.op == "<=":
            return lv <= rv
        if tree.op == "<":
            return lv < rv
        raise TemplateError(f"Unknown operator {tree.op}")
    if isinstance(tree, _EFilter):
        value = _eval_tree(tree.expr, ctx)
        args = [_eval_tree(arg, ctx) for arg in tree.args]
        return _apply_filter(tree.name, value, args)
    raise TemplateError(f"Invalid expression node: {tree!r}")


def _eval_expr(src: str, ctx: dict) -> Any:
    return _eval_tree(_parse_expression(src), ctx)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _rstrip_ws(text: str) -> str:
    return re.sub(r"[ \t\r\n]*$", "", text)


def _lstrip_ws(text: str) -> str:
    return re.sub(r"^[ \t\r\n]*", "", text)


def _render_nodes(nodes: list, ctx: dict) -> str:
    out = ""
    i = 0
    while i < len(nodes):
        node = nodes[i]
        if isinstance(node, _Text):
            out += node.value
            i += 1
            continue
        if isinstance(node, _Interp):
            out += _stringify(_eval_expr(node.expr, ctx))
            i += 1
            continue
        if isinstance(node, _IfBlock):
            endif = node.branches[-1]
            choices = node.branches[:-1]
            selected = None
            for branch in choices:
                if branch.condition is None:
                    selected = branch
                    break
                if _truthy(_eval_expr(branch.condition, ctx)):
                    selected = branch
                    break
            start_tag = selected if selected is not None else choices[0]
            if start_tag.strip_before:
                out = _rstrip_ws(out)
            body = (
                _render_nodes(selected.body, ctx) if selected is not None else ""
            )
            if start_tag.strip_after:
                body = _lstrip_ws(body)
            if endif.strip_before:
                body = _rstrip_ws(body)
            out += body
            i += 1
            if endif.strip_after and i < len(nodes) and isinstance(nodes[i], _Text):
                out += _lstrip_ws(nodes[i].value)
                i += 1
            continue
        raise TemplateError(f"Unknown node type: {type(node)}")
    return out


def render(source: str, context: Optional[dict] = None) -> str:
    """Render a Spex template string with the given context mapping.

    Matches Jinja2's default ``keep_trailing_newline=False``: a single
    trailing newline on the source, if present, is not part of the output.
    """
    if source.endswith("\n"):
        source = source[:-1]
    nodes = _parse(source)
    return _render_nodes(nodes, dict(context or {}))


def scan_template_constructs(source: str) -> list[str]:
    """Return raw tag/interpolation expression bodies for scanning tests."""
    found: list[str] = []
    for match in _TAG_RE.finditer(source):
        raw = match.group(0)
        if raw.startswith("{{"):
            inner = _INTERP_RE.match(raw)
            found.append(inner.group(1).strip() if inner else raw)
        else:
            inner = _TAG_OPEN_RE.match(raw)
            found.append(inner.group(1).strip() if inner else raw)
    return found
