"""Read the TOML subset used by Spex on Python without tomllib."""

import re

_KEY = r"[A-Za-z0-9_-]+"
_TABLE = re.compile(rf"\[[ \t]*({_KEY})[ \t]*\][ \t]*(?:#.*)?")
_ASSIGNMENT = re.compile(rf"({_KEY})[ \t]*=[ \t]*(.*)")
_VALUE = re.compile(r"""("(?:[^"\\]|\\.)*"|'[^']*'|[^"'# \t]+)[ \t]*(?:#.*)?""")
_INTEGER = re.compile(r"[+-]?(?:0|[1-9](?:_?[0-9])*)")
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_ESCAPE = re.compile(r"\\(?:u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)")
_BASIC_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "b": "\b",
    "t": "\t",
    "n": "\n",
    "f": "\f",
    "r": "\r",
}


class ParseError(ValueError):
    """An invalid or unsupported TOML statement."""

    def __init__(self, line, reason):
        super().__init__(f"line {line}: {reason}")


def _unescape(match):
    escape = match[0][1:]
    if escape in _BASIC_ESCAPES:
        return _BASIC_ESCAPES[escape]
    if len(escape) in (5, 9):
        codepoint = int(escape[1:], 16)
        if codepoint <= 0x10FFFF and not 0xD800 <= codepoint <= 0xDFFF:
            return chr(codepoint)
        raise ValueError("invalid Unicode escape")
    raise ValueError(f"invalid string escape: {match[0]}")


def _parse_value(text):
    if text.startswith(('"""', "'''")):
        raise ValueError("multiline strings are unsupported")
    match = _VALUE.fullmatch(text)
    if not match:
        raise ValueError("expected a single value followed by an optional comment")
    token = match[1]
    if token.startswith('"'):
        return _ESCAPE.sub(_unescape, token[1:-1])
    if token.startswith("'"):
        return token[1:-1]
    if token in ("true", "false"):
        return token == "true"
    if _INTEGER.fullmatch(token):
        return int(token.replace("_", ""))
    raise ValueError("expected a single-line string, boolean, or decimal integer")


def loads(text):
    """Parse a document containing bare keys, scalar values, and single-level tables."""
    result = {}
    current = result
    for line_number, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if _CONTROL.search(raw):
            raise ParseError(line_number, "invalid control character")
        line = raw.strip(" \t")
        if not line or line.startswith("#"):
            continue
        table = _TABLE.fullmatch(line)
        if table:
            name = table[1]
            if name in result:
                raise ParseError(line_number, f"duplicate table or key: {name}")
            current = result[name] = {}
            continue
        assignment = _ASSIGNMENT.fullmatch(line)
        if not assignment:
            raise ParseError(line_number, "expected a single-level table or bare key assignment")
        key, value = assignment.groups()
        if key in current:
            raise ParseError(line_number, f"duplicate key: {key}")
        try:
            current[key] = _parse_value(value)
        except ValueError as exc:
            raise ParseError(line_number, str(exc)) from exc
    return result
