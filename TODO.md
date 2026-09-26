# TODO

- [ ] hk drift check for python script dependencies: a step that fails when a PEP 723 header in a `scripts` unit no longer matches the root pyproject's `scripts` dependency group. Today only `tmpl sync` regenerates the group, so drift between syncs goes unnoticed. Needs `tmpl` (or a standalone check) available inside generated repos.
- [ ] License choices beyond MIT: the retired Copier template offered MIT, Apache-2.0, LGPL-3.0-only, GPL-3.0-only (via copyleft/patent questions), or any SPDX id, fetching the text with `gh-license`. `root` only bundles `licenses/MIT.jinja`.
