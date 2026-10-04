# TODO

- [ ] Cross-release check as `scripts/` plus a mise task: `init` with the previous tag, `update` to the new one, `sync --check`, then `update --to` the previous tag, with isolated uv caches, XDG dirs and `GIT_CONFIG_GLOBAL`. Each release has so far run this by hand.
- [ ] CI: there is no `.github/workflows/`. Run ruff check, ruff format --check, basedpyright, mypy and pytest on PRs, with actions pinned to commit SHAs.
