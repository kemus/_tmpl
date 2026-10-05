# TODO

## Tool options

Evaluate offering each dev tool below as an optional addition, asked only when a selected template renders a file the
tool checks. Options are grouped by file type and role, and each group offers its tools plus `none`. For example, any
template with a YAML file asks:

- YAML linter: `yamllint`, `none`
- YAML formatter: `yamlfmt`, `prettier`

The defaults are `yamllint` and `yamlfmt`, or `yamllint` and `prettier` when a JS/TS template is selected.

- [ ] Multi-select tool options with a stage per tool: `pre-commit`, `pre-push`, or CI only (the `check` hook alone),
      e.g. `basedpyright` at pre-commit plus `mypy` at pre-push and in CI. This generalizes `type_checker_fast` and
      `type_checker_thorough`, which are single choices fixed to pre-commit and pre-push. Covers the manifest format,
      `set`/`--opt` syntax, and migrating existing manifests.
- [ ] Ask a tool group only when the selected layers render a file it checks, with defaults that can depend on other
      layers (`prettier` as the formatter when a JS/TS layer is present).

### Python (`lang/python`)

- [ ] ruff: Python linter and formatter, always on today; evaluate it as the default of a linter group and a formatter
      group that also offer `none`.
- [ ] mypy, basedpyright, pyright, ty: move the two existing type-checker options into one multi-select type-checker
      group.

### YAML (every repo: `.github/workflows/ci.yml`)

- [ ] yamllint: YAML linter; the default.
- [ ] ryl: a Rust YAML linter; evaluate as an alternative to yamllint.
- [ ] yamlfmt: YAML formatter; the default outside JS/TS templates.
- [ ] prettier: formatter for YAML, JSON and Markdown; the default formatter for those types with JS/TS templates.

### TOML (every repo: `.config/mise/config.toml`, `.config/tmpl.toml`; Python: `pyproject.toml`)

- [ ] taplo: TOML linter and formatter.

### Markdown (every repo: `AGENTS.md`; `kind/cli`: `README.md`)

- [ ] rumdl: Markdown linter and fixer.
- [ ] vale: prose style linter; needs `vale sync` and a cache path for downloaded styles.
- [ ] lychee: link checker; needs network, so likely pre-push or CI only.

### Pkl (every repo: `.config/hk.pkl`)

- [ ] pkl: hk's `pkl` and `pkl_format` builtins, to check and format the generated `hk.pkl`.

### Shell (no template renders shell scripts yet)

- [ ] shellcheck: shell linter.
- [ ] shfmt: shell formatter, which follows `.editorconfig`.

### GitHub Actions (every repo: `.github/workflows/ci.yml`)

- [ ] actionlint: workflow syntax, expressions, and shellcheck on `run:` steps.
- [ ] zizmor: workflow security linter.
- [ ] pinact: pins `uses:` references to commit SHAs with a version comment.
- [ ] ghalint: workflow and action policy checks, such as explicit job permissions.

### Any file (every repo)

- [ ] typos: spell checker for code and prose.
- [ ] editorconfig-checker: checks files against the generated `.editorconfig`.
- [ ] gitleaks: secret scanner.
- [ ] hk hygiene builtins beyond the enabled `check_merge_conflict`, `trailing_whitespace` and `newlines`:
      `byte_order_marker`, `check_added_large_files`, `check_executables_have_shebangs`, `check_symlinks`,
      `detect_private_key`, `fix_smart_quotes`, `mixed_line_ending`, `no_commit_to_branch`.
- [ ] Renovate: already the `deps-update` feature; decide whether it joins this option model or stays a feature.
