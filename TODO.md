# TODO

- [ ] Downgrade tolerance: `_render_base` (`src/tmpl/cli.py`) builds `RenderedFile(content, **meta)` from the base release's render index, so a `RenderedFile` field added in a later release makes an older tmpl fail with `TypeError` when it renders that release as its base. Keep only the known fields from `meta`; releases from the fix onward then stay downgradable when fields are added (0.7.0 used a new policy value instead of a field for this reason).
- [ ] Cross-release check as `scripts/` plus a mise task: `init` with the previous tag, `update` to the new one, `sync --check`, then `update --to` the previous tag, with isolated uv caches, XDG dirs and `GIT_CONFIG_GLOBAL`. Each release has so far run this by hand.
- [ ] CI: there is no `.github/workflows/`. Run ruff check, ruff format --check, basedpyright, mypy and pytest on PRs, with actions pinned to commit SHAs.
- [ ] Adopt with a `follow` file (`LICENSE`) keeps an existing file silently even when it doesn't match the `license` option; report it as a note, like the kept values adopt reports for structured files.
