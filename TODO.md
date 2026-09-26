# TODO

- [ ] hk drift check for python script dependencies: a step that fails when a PEP 723 header in a `scripts` unit no longer matches the root pyproject's `scripts` dependency group. Today only `tmpl sync` regenerates the group, so drift between syncs goes unnoticed. Needs `tmpl` (or a standalone check) available inside generated repos.
