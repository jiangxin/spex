# Changelog

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
