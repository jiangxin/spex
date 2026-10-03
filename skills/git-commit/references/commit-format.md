# Commit message format

Quality bar aligned with `spex/templates/apply-commit.md` and se-insight
`commit_message` (rules + why/how/impact).

## Conventional Commits

```text
<type>(<optional-scope>): <summary>

<body>
```

Common types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`,
`perf`, `style`, `ci`, `build`, `revert`.

Subject and body are English. Subject is ASCII (se-insight rule track
penalizes non-ASCII titles). Do not write Chinese or other non-English
prose in the title or body.

## Length and wrapping

| Part | Rule |
|------|------|
| Title (first line) | Aim ≤ 50 UTF-8 bytes; hard limit 72. Never wrap the title. |
| Blank line | Required between title and body. |
| Body lines | Wrap at 72 UTF-8 bytes. |
| Effective lines | Subject + blank + body; ignore trailing git trailers. Prefer ≥ 5 effective lines (se-insight base 100); never title-only (0–39 semantic band). |

## Semantic axes (why / how / impact)

Cover all three in **natural-language paragraphs** (se-insight 85–100
band). The table is a checklist for the writer, not a body template:

| Axis | Cover in prose |
|------|----------------|
| motivation | Problem / goal from conversation, spec, task, or bug |
| approach | Core technical reasoning — not every hunk |
| effect | Users, callers, tests, ops, or follow-ups |

Title states the change; body states the reason. Do not restate the
diff. Do not use `Why:` / `How:` / `Impact:` labels, markdown headings,
or a three-item list in the commit body.

## Git command

Pass the message via HereDoc. Do not use `-m` for multi-line bodies.

```bash
git commit -F- <<'EOF'
<commit message>
EOF
```

If author identity is known from spec `meta.json` (`user_name` /
`user_email`) or the user, set it for that commit only:

```bash
git -c user.name="Name" \
    -c user.email="email@example.com" \
    commit -F- <<'EOF'
<commit message>
EOF
```

Do not amend unless the user explicitly asked. Do not skip hooks.

## Examples

**Good (why + how + impact):**

```text
fix(auth): reject expired JWT before hitting the DB

Login was succeeding on tokens past exp because the filter only
checked the signature. Validate exp in the same middleware as the
signature so expired sessions fail closed.

Callers of /login see 401 instead of a user payload. Session
lookups no longer run for expired tokens.
```

**Bad (title-only / what-changed list):**

```text
fix: update auth.py and tests
```

**Bad (labeled axes — do not write this):**

```text
fix(auth): reject expired JWT before hitting the DB

Why: expired tokens still logged in
How: check exp in middleware
Impact: /login returns 401
```
