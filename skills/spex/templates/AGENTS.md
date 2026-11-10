# Spex prompt templates

Markdown files in this directory are rendered by the **Spex template
engine** (`skills/spex/scripts/template.py`) — a stdlib-only dialect.
They are **not** Jinja2 templates. Custom copies under a project's
`spex_root/templates/` must stay within this dialect.

When changing syntax: update **this file**, `template.py`, and the
template/engine tests in the **same change**.

This file (`AGENTS.md`) is documentation only and is **not** rendered
as a prompt template.

## Delimiters

| Form | Meaning |
|------|---------|
| double-brace `expr` | Interpolate the expression as text |
| percent-brace tags | Control tags: `if` / `elif` / `else` / `endif` |
| `{%-` / `-%}` style | Same tags with whitespace control (see below) |

Write interpolations as `{{` + expression + `}}` and tags as
`{%` + body + `%}` (no space required inside the braces in real
templates). Examples below use a word description so this doc file is
not itself a valid Spex template.

Literal `|` in Markdown prose (for example `status | next`) is **not**
a filter. The `|` filter operator applies only inside interpolations
or control tags.

A single trailing newline on the source file is stripped from the
output (Jinja-compatible `keep_trailing_newline=False`).

## Expressions

Allowed in interpolations and in `if` / `elif` conditions:

- **Names**: `[A-Za-z_][A-Za-z0-9_]*` looked up in the render context
- **String literals**: single or double quotes
- **Integer literals**: optional leading `-`
- **Operators** (precedence low → high): `or`, `and`, `not`,
  comparisons (`== != >= > <= <`), then filters (`|`)
- **Parentheses**: for grouping (including nested filter args)

### Undefined names

Missing context keys are **undefined**: falsy in conditions, and print
as an empty string when interpolated. They are **not** an error unless
passed through `|int` (which requires a defined value).

### Filters

Only these filters exist:

| Filter | Behavior |
|--------|----------|
| `default(fallback)` | If the left value is undefined, use `fallback`; otherwise keep the value (including empty string) |
| `int` | Convert to int; empty/`None` → `0`; non-numeric defined values → `0`; **undefined raises** |

Filters may nest. Real-template examples (copy into `.md` prompt files):

- interpolate: `review_mode | default(mode | default('full'))`
- condition: `review_mode | default(mode | default('full')) == 'delta'`
- condition: `review_round|int >= 2`

## Control flow

Only branching is supported, using tags whose bodies are:

- `if <condition>`
- `elif <condition>` (optional)
- `else` (optional)
- `endif` (required)

- Conditions use the expression language above (`and`, `or`, `not`,
  comparisons, filters).
- Tags may appear mid-line; bodies may nest other tags and interpolations.

### Whitespace control

A `-` next to `%` strips whitespace (spaces, tabs, CR, LF) on that side
of the tag relative to surrounding template text:

| Form | Effect |
|------|--------|
| open with `{%-` | Strip whitespace **before** the tag |
| close with `-%}` | Strip whitespace **after** the tag |

Only tags on the **taken** branch (the matching `if`/`elif`/`else`, plus
`endif`) apply their strip flags.

## Forbidden constructs

Do **not** use (the engine rejects them):

- `for` / `endfor` loops
- `set`, `macro`, `call`, `filter`, `with`
- `include`, `extends`, `block`
- `raw`
- comment tags (`{#` … `#}`)
- Any filter other than `default` and `int`
- Dotted attribute access (`foo.bar`) or subscripting (`foo[0]`)

## Front matter

YAML front matter (`---` … `---`) is stripped **after** render by
`prompt.py` (`strip_front_matter`). Optional `required:` / `optional:`
lists document metadata keys; `validate_required_meta` enforces
`required` before render. Front matter is plain YAML for agents — it is
not evaluated as Spex template syntax.

## Files in this directory

| Template | Role |
|----------|------|
| `spec-template.md` | New spec body (no template tags today) |
| `modify-spec.md` / `modify-todo.md` | Modify-plan prompts |
| `apply-one-task.md` / `apply-commit.md` | Apply one step + commit |
| `apply-review.md` / `apply-fix.md` | Review / fix loop prompts |
| `AGENTS.md` | This dialect spec (not rendered) |
