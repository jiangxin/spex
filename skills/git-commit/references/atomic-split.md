# Atomic commits and when to split

Goal: each commit is one reviewable concern — small enough to revert,
cherry-pick, and review in minutes.

## Size heuristic (se-insight `commit_patch`)

Count added lines; ignore lockfiles (`package-lock.json`, `yarn.lock`,
`pnpm-lock.yaml`, `Cargo.lock`, `poetry.lock`, `uv.lock`, `go.sum`,
`composer.lock`, `Gemfile.lock`).

| Added lines | Quality | Split? |
|-------------|---------|--------|
| ≤ 50 | Best | Usually one commit |
| ≤ 100 | Git-community target | Prefer keep together if one concern |
| ≤ 200 | Acceptable | Split only if concerns mix |
| 250–350 | Weak | Split if more than one concern |
| > 350 | Poor | Strong split candidate |
| > 1000 | Fail band | Must propose a split (unless generated/lockfile-only) |

Spex / Git practice: one concern, keep around 100 lines when practical.

## One concern

Keep together when the pieces are the same change:

- Production code + tests that prove it
- A rename/move and call-site updates
- A bugfix and its regression test
- Tightly coupled interface + implementation

Split when concerns are independent:

- Feature work mixed with unrelated refactor
- Formatting / import-order churn mixed with logic
- Docs or changelog mixed with code (unless the task is docs)
- Unrelated bugfix riding along a feature
- Generated lockfile-only vs source (lockfile may follow the dep change
  in the same commit if it is the same concern)
- Multiple features or multiple bugfixes in one tree

Do not split a single logical Hunk across commits if that would leave
the tree uncompileable or tests red between commits. Each proposed
commit should leave a coherent snapshot.

## Staging

Prefer path-scoped `git add` (and `git add -p` only when one file
holds two concerns). Do not `git add -A` when splitting.

Do not stage secrets (`.env`, credentials, private keys). Warn and skip
those files.
