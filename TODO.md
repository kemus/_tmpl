# TODO

- [ ] License choices beyond MIT: the retired Copier template offered MIT, Apache-2.0, LGPL-3.0-only, GPL-3.0-only (via copyleft/patent questions), or any SPDX id, fetching the text with `gh-license`. `root` only bundles `licenses/MIT.jinja`.

## Mise Backends

- [ ] Relock hk on the registry default backend: `.config/mise/config.toml` already says
      `hk = "2.1.0"`, but `.config/mise/mise.lock` still records `backend = "aqua:jdx/hk"`, which
      `mise lock` keeps. Delete the hk sections from the lock, then
      `mise lock hk -p <platforms already in the lock>` and confirm the diff only touches hk
- [ ] `tests/fixtures/kupdate/.config/mise/config.toml`: `"aqua:jdx/hk" = "2.0.1"` →
      `hk = "2.0.1"` (the kupdate repo itself made this change in 0922172)
