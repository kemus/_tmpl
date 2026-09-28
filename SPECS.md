# tmpl — Composable, Updatable Project Templates

Design spec for replacing the Copier-based `_tmpl` repo with `tmpl`, a custom CLI plus templates that scaffolds, adopts, updates, and removes pieces of git repos across languages and repo shapes.

Status: draft. All design decisions are recorded in §13.

## 1. Goals

### 1.1 Must support

1. Repo shapes: single-language single-package, cross-language single-package (e.g., Python + a bash `scripts/` dir), single-language monorepo (e.g., TS frontend + backend), cross-language monorepo (e.g., TS + Python, Python + Rust + bash).
2. Languages: python, go, rust, bash, zsh, sh (POSIX), lua, js/ts.
3. Kinds: cli, lib, scripts, plugin, service, webapp, tui, mcp-server, github-action, vscode-extension, browser-extension (§4.2).
4. Features: cross-cutting add-ons attached to a unit or the root, e.g. release, container, docs (§4.3).
5. **Adopting existing repos** as a top-priority feature.
6. **Updatable** repos: later template changes flow into existing repos through a 3-way merge.
7. Adding and removing components after creation as first-class operations. Remove must be safe when unit files were customized.
8. Git init + initial commit, and post-generation setup (toolchains, deps, hooks).

### 1.2 Non-goals

- Supporting CI other than GitHub Actions, or toolchain managers other than mise.
- Being a general-purpose templating engine for other people's templates.
- Managing source code after scaffolding (`src/…` is seeded once, then belongs to the repo).

## 2. Core model

### 2.1 Repo = root + units

- **Root:** repo-wide files every repo gets (§6.1).
- **Unit:** one `lang × kind` placed at a path, e.g. `python/cli @ .`, `rust/lib @ crates/core`, `bash/scripts @ scripts`.
- Repo shape falls out of the units; there is no separate "mode":

| Shape | Units |
|---|---|
| single-language, single-package | `python/cli @ .` |
| cross-language, single-package | `python/cli @ .`, `bash/scripts @ scripts` |
| single-language monorepo | `ts/webapp @ apps/web`, `ts/service @ apps/api` |
| cross-language monorepo | `ts/webapp @ apps/web`, `python/service @ services/api`, `rust/lib @ crates/core` |

### 2.2 Template layers

Each rendered repo combines these template layers:

| Layer | Applied | Contributes |
|---|---|---|
| `root` | once | baseline files, shared-file sinks (§5) |
| `lang/<lang>` | once per language present | toolchain, lint/format, ignore patterns, workspace root, CI setup |
| `lang/<lang>/unit` | per unit of that language | per-package manifest and test scaffold (e.g. `pyproject.toml`, `tests/`) |
| `kind/<kind>` | per unit of that kind | language-agnostic bits (e.g. README "Usage" section, release workflow shape) |
| `lang/<lang>/kind/<kind>` | per unit | the concrete scaffold (e.g. cyclopts app, `src/main.rs` with clap) |
| `feature/<feature>` | per root or unit the feature is attached to | language-agnostic parts (e.g. `renovate.json`, CONTRIBUTING.md, docs site) |
| `lang/<lang>/feature/<feature>` | per unit with that feature | language-specific parts (e.g. PyPI publish job, `divan` bench harness) |

The old base → language → type chain survives as layers 1–2–5 (`root`, `lang/<lang>`, `lang/<lang>/kind/<kind>`), but it is applied **per unit**, and layers never switch between each other with `if/elif`. They only *add* to shared files through fragments.

A kind whose units are not packages (python `scripts`) sets `package = false` on its `lang/<lang>/kind/<kind>` layer. Such a unit skips `lang/<lang>/unit`, so it gets no package manifest and no workspace membership.

### 2.3 Desired state and reconcile

Every mutating command follows the same two steps: **change the desired state** (manifest + template version), then **reconcile**.

```
base   = render(applied_manifest, old_version) # empty for adopt / new files
target = render(new_manifest, new_version)
ours   = working tree
for each path in base ∪ target: merge(base, ours, target) → write / delete / conflict
```

Live-sourced options (§3.2) are read once from `ours` and passed to both renders, so a hand-edited `requires-python` never shows up as template drift. Derived data whose source is another file (python script dependencies, §5.3) is the exception: the base reads it from the file it lands in, as the last reconcile wrote it, so a changed source reaches the merge as template drift.

`applied_manifest` is the manifest as the last reconcile wrote it, not the file as it stands, so a hand edit of an option reaches the merge as a desired-state change (§3.3 `applied`).

| Command | Desired-state change |
|---|---|
| `init` | ∅ → manifest; base = ∅ |
| `adopt` | ∅ → detected manifest; base = ∅ against a non-empty tree |
| `add` | manifest + unit |
| `remove` | manifest − unit |
| `feature add` / `feature remove` | manifest ± feature on the root or a unit |
| `update` | version → newer |
| `set` | manifest option value (`tmpl set KEY=VALUE`) |
| `sync` | none (re-apply after a hand-edited manifest) |

## 3. Manifest: `.config/tmpl.toml`

### 3.1 Why it is needed

Three facts can't be recovered reliably from the tree:
1. which template version produced the repo (needed for the merge base),
2. non-derivable choices (cli vs lib for a dual-purpose package, whether `scripts/` is a unit, test framework, …),
3. what the tool owns (so remove strips only its own fragments).

### 3.2 Keeping it minimal

- Store only answers that can't be derived. Options can declare a **live source** (e.g. `python_version ← pyproject.toml:project.requires-python`). These are read from the working tree before rendering and never stored, so they can't go stale.
- Store *resolved* values for everything else, including defaults. That way, changing a default in the templates never silently changes old repos; `update` reports new or changed defaults instead.
- Write it only through the tool (adopt writes it first). Hand edits are allowed and followed by `tmpl sync`, which finds the manifest it last applied through the `applied` hash (§3.3).

### 3.3 Schema

```toml
version = "0.4.0"                 # tmpl release that produced the last render
# source = "git+https://github.com/kemus/_tmpl"   # optional override (forks / local dev)
applied = "sha256:…"              # hash of this file, minus this line, as the last reconcile wrote it

[root]
description = "…"
license = "MIT"
indent = "2"
max_line_length = 120
sync_check = true                 # hk step running `tmpl sync --check` (§8.7)
features = ["deps-update", "security-scan"]

[lang.python]                     # lang-scoped options: once per repo per language
type_checker_fast = "basedpyright"
type_checker_thorough = "mypy"
# python_version: live-sourced, not stored

[lang.ts]
package_manager = "pnpm"
test = "vitest"

[lang.bash]
test = "bats"                     # chosen instead of the default (shellspec); all resolved values are stored (§3.2)

[[unit]]
path = "."
lang = "python"
kind = "cli"
features = ["release", "coverage", "cli-extras"]

[[unit]]
path = "scripts"
lang = "bash"
kind = "scripts"
```

### 3.4 Option scopes

| Scope | Examples | Rationale |
|---|---|---|
| `root` | description, license, indent, max line length | repo-wide files |
| `lang` | python version, type checker, JS package manager, JS test runner | one toolchain / workspace per language per repo; avoids conflicting fragments |
| `unit` | kind-specific choices, package name override | differs between packages |

## 4. Catalog

### 4.1 Languages and per-language options (answers with defaults)

| Lang | Toolchain (mise) | Lint / format | Test (default · alternatives) | Other options (default) | Workspace |
|---|---|---|---|---|---|
| python | python, uv | ruff, ruff format | pytest | version (live); type checkers: fast = basedpyright (check + pre-commit), thorough = mypy (pre-push + CI); either slot accepts basedpyright · pyright · ty · mypy · none | uv workspace |
| go | go | golangci-lint, gofmt | go test | — | go.work |
| rust | rust, cargo-nextest | clippy, rustfmt | nextest (+ `cargo test --doc`) · cargo test | — | cargo workspace |
| bash | bash, shellcheck, shfmt, shellspec | shellcheck, shfmt | shellspec · bats | — | none |
| zsh | zsh, shellspec | `zsh -n` | shellspec · zunit | — | none |
| sh | shellcheck, shfmt, shellspec | shellcheck (`-s sh`), shfmt (`-ln posix`) | shellspec | — | none |
| lua | luajit, luarocks, stylua, selene | stylua, selene | busted (plugins: busted via nlua) | runtime (luajit · lua 5.4; plugins always luajit) | none |
| ts | node + pnpm (or bun / npm) | oxlint + prettier · biome · eslint + prettier | vitest · node:test · bun test | package manager (pnpm · bun · npm) | pnpm-workspace.yaml / package.json `workspaces` |

Options are validated against each other (e.g. `test = "bun test"` requires `package_manager = "bun"`).

The two Python type-checker slots map to hk hooks: the fast slot runs in `check` and `pre-commit`; the thorough slot runs in `pre-push` and in CI (`mise run check` in CI enables it through an hk profile).

### 4.2 Support matrix (kind × lang)

Cells hold the kind-specific default (alternatives after `·`, all selectable as unit options). `–` means not offered. Every kind is in the initial implementation scope.

| kind \ lang | python | go | rust | bash | zsh | sh | lua | ts |
|---|---|---|---|---|---|---|---|---|
| cli | cyclopts | kong · cobra · urfave/cli · stdlib `flag` | clap (derive) | while/case parser (long opts, subcommands) | zparseopts script | while/case parser | – | commander |
| lib | ✓ | ✓ | ✓ | sourced lib | – | sourced lib | rockspec + luarocks | tsdown (ESM + .d.ts) |
| scripts | PEP 723 `uv run --script` files | – | – | ✓ | ✓ | ✓ | – | – |
| plugin | – | – | – | – | zsh plugin | – | nvim plugin | – |
| service | FastAPI | Huma on net/http | axum | – | – | – | – | Hono |
| webapp | – | – | – | – | – | – | – | Vite + React |
| tui | Textual | Bubble Tea | Ratatui | – | – | – | – | Ink |
| mcp-server | official `mcp` SDK | official Go SDK | rmcp | – | – | – | – | official TS SDK |
| github-action | composite running `uvx` | composite downloading release binary | composite downloading release binary | composite | – | composite | – | node action |
| vscode-extension | – | – | – | – | – | – | – | esbuild + @vscode/test-cli + vsce |
| browser-extension | – | – | – | – | – | – | – | WXT (MV3, cross-browser) |

Go/rust github-action units expect the `release` feature on the unit, because the composite action downloads the released binary.

`tmpl add` takes the same `LANG:KIND[@PATH]` spec as `init --unit` (`tmpl add rust:cli@crates/foo`), language first because it's usually the settled decision, and checks it against the matrix.

### 4.3 Features (cross-cutting add-ons)

A feature is attached to the root or to a unit (`tmpl feature add release crates/foo`) and follows the same reconcile rules as units. It contributes files and fragments through `feature/<f>/` plus `lang/<lang>/feature/<f>/`. Applicability is validated just like the kind × lang matrix. `feature/<f>/template.toml` declares the feature with `attaches` (`root` or `unit`) and, for a unit feature, `kinds` (all when unset). A unit feature needs `lang/<lang>/feature/<f>/` for the unit's language. A root feature also applies `lang/<lang>/feature/<f>/` for each language present, at the root.

A feature's layers declare options like any layer (§3.4). `root` options come from a root feature's `feature/<f>`, `unit` options from a unit feature's two layers, and `lang` options from `lang/<lang>/feature/<f>` of any feature attached to the root or to a unit of that language. They are stored with the other options of their scope.

Shipped so far: `deps-update` (Renovate). The rest of the table is planned.

| Feature | Attaches to | Contributes (per language where relevant) |
|---|---|---|
| `release` | unit | publish workflow: PyPI (trusted publishing), crates.io (libs) + cargo-dist (binaries, installers, GitHub releases), goreleaser, npm, luarocks, GitHub release tarball for shell; changelog via git-cliff |
| `container` | unit (service, cli, mcp-server, tui) | multi-stage Dockerfile with digest-pinned bases: distroless (static/cc) for go/rust, python-slim + uv for python, node-slim for ts; CI image build/push job |
| `docs` | root | docs site chosen by languages present (mkdocs-material if python, else vitepress if ts, else mdbook if rust; overridable), plus a CI build/deploy job |
| `deps-update` | root | Renovate config (`.github/renovate.json`) covering language deps, mise tools, and pinned action SHAs |
| `coverage` | unit | coverage.py, cargo-llvm-cov, `go test -cover`, vitest coverage; report in the CI job summary + artifact, optional failing threshold; no third-party service |
| `bench` | unit | pytest-benchmark, divan, `go test -bench`, vitest bench; `bench:<lang>` mise task |
| `fuzz` | unit | atheris, cargo-fuzz, go native fuzzing, Jazzer.js; `fuzz:<lang>` mise task |
| `community` | root | CONTRIBUTING.md, SECURITY.md, issue/PR templates (no code of conduct) |
| `cli-extras` | unit (cli, tui) | shell completions + man page generation (cyclopts, clap_complete + clap_mangen, kong completion, …) |
| `security-scan` | root + each language present | betterleaks (hk builtin) for secrets; pip-audit, cargo-deny, govulncheck, `<pm> audit` as hk/CI steps |

## 5. Shared files: sinks and fragments

### 5.1 Principle

Layers never template shared files directly. They declare **fragments** (data) addressed to a **sink**. Each sink has one renderer that merges fragments deterministically (sorted by `order` then source) and writes the file. This replaces every `if/elif` chain.

### 5.2 Sinks

| Sink | File | Fragment shape | Extension point for user additions |
|---|---|---|---|
| `mise.tools` / `mise.env` / `mise.tasks` | `.config/mise/config.toml` | key → value / task table | `.config/mise/conf.d/*.toml`, task files in `.config/mise/tasks/` |
| `hk.steps` | `.config/hk.pkl` | `{name, builtin?, glob?, check?, fix?, hooks, slow?}` | none: edit `hk.pkl` directly; updates arrive through 3-way text merge |
| `ci.steps` | `.github/workflows/ci.yml` | step objects | additional workflow files |
| `gitignore` | root `.gitignore` or `<unit>/.gitignore` | lines, grouped by heading | extra lines (line-set merge, §7.3) |
| `editorconfig` | `.editorconfig` | `{glob: {key: value}}` | extra sections (structured merge) |
| `workspace.<lang>` | root `pyproject.toml` / `Cargo.toml` / `go.work` / `pnpm-workspace.yaml` / `package.json` | member paths (python: also the non-package root's tables, and `tool` tables for any root) | extra members (set merge) |
| `readme.sections` | `README.md` | markdown section per unit or language | free text (seeded, §6.2) |
| `agents.sections` | `AGENTS.md` | markdown sections (languages, commands, layout) | free text (3-way merge) |

### 5.3 Fragment rules

- **Scope:** unit-level ignore patterns go to `<unit>/.gitignore` when the unit isn't at `.`. That keeps the root file small and makes removal trivial.
- **Dedup:** identical fragments from several units merge. Conflicting values for the same key (e.g. two `python` versions) are a catalog bug, which is why such options are lang-scoped.
- **Ordering:** hk steps and CI steps carry an `order` so fast checks run first (shellcheck → fmt → clippy → type check → tests).
- **Workspaces:** a language's workspace root is generated when that language has ≥ 2 units, or 1 unit not at `.`. For python this is a virtual root `pyproject.toml` with `[tool.uv.workspace]` only (or `[tool.uv.workspace]` deep-merged into the root package if a unit sits at `.`). With no python package at all (scripts alone), the root is instead a non-package `pyproject.toml`: `[dependency-groups] dev` with the lint, test, and checker tools, plus the checkers' config, so the venv and hk steps work. Each scripts unit seeds `<unit>/tests/`, whose test runs a script by path (`runpy`), so no import-path config is needed and `test:python` always has a test; a root package's `testpaths` gain those dirs. Members come from `lang/<lang>/unit`, so units with `package = false` (§2.2) are never members; a member's manifest omits `readme` unless the unit sits at `.`. The same pattern applies to cargo (virtual manifest vs `[workspace]` in the root package), `go.work`, and JS workspaces.
- **Script dependencies:** a python `scripts` unit sends its directory to `python.scripts`. Render collects the `dependencies` of each PEP 723 block there (the file on disk over the scaffold) into the root `pyproject.toml`'s `scripts` dependency group, which `dev` includes (`{include-group = "scripts"}`), so one project venv serves checkers, tests, and editors. Scripts pinning conflicting versions fail `uv lock`.
- **Importable scripts:** a python `scripts` unit's `importable` option (default `false`) lets tests `import` its scripts as top-level modules. It adds the unit's directory to pytest's `pythonpath` and to each chosen checker's search path (`extraPaths`, `mypy_path`, `environment.extra-paths`) in the root `pyproject.toml`, whatever its shape (virtual workspace root, root package, or non-package root), since pytest and the checkers run from the root. It is off by default because each script then shadows any module of the same name and importing one runs its top level.
- **Tasks contract:** every language contributes `lint`, `fmt`, and `test` tasks namespaced by language (`test:python`). The root defines `check` (`hk check --all`, depending on `test:*`) and `fix` (`hk fix --all`). CI runs `mise run check` in one job with `HK_PROFILE=slow`.
- **Tool resolution:** hk 2.1 builtins run structured argv and reject a shell `prefix`, so steps never wrap commands. Each language puts its tools on `PATH` through mise instead; python contributes `_.python.venv = {path = ".venv", create = true}` to `mise.env`, so ruff and the type checkers resolve from the project venv.
- **Hooks:** a step lists the hooks it joins. `pre-commit` and `fix` run with `fix = true`; a `slow` step joins `check` only under the `slow` profile (CI), while `pre-push` always runs it.

## 6. Files and policies

### 6.1 Root baseline (every repo)

| File | Policy | Notes |
|---|---|---|
| `README.md` | seed | sections from `readme.sections` at creation |
| `LICENSE` | seed | from the root `license` option (default MIT; the old template's picker is kept) |
| `.gitignore` | merge (line-set) | always contains `/third_party/` |
| `.editorconfig` | merge | |
| `.config/mise/config.toml` | merge | |
| `.config/hk.pkl` | merge (text) | pinned hk package version |
| `.github/workflows/ci.yml` | merge | actions pinned to full SHAs |
| `AGENTS.md` | merge (text) | |
| `third_party/.gitkeep` | seed | the tool stages it with `git add -f`, since `/third_party/` is ignored |
| `.config/tmpl.toml` | owned by the tool | manifest |

### 6.2 Policies

| Policy | On create | On update | On remove (file leaves target) |
|---|---|---|---|
| `merge` | write | 3-way merge (§7) | delete if unchanged from base, else keep + report |
| `seed` | write if absent | never touched | delete if unchanged from base, else keep + report |

Scaffold source (`src/…`, `tests/test_*.py`, `src/main.rs`, …) and `README.md` are `seed`. Config and tooling files are `merge`.

## 7. Merge engine

### 7.1 Dispatch by format

| Format | Handler |
|---|---|
| TOML | structured 3-way (tomlkit, round-trip) |
| YAML | structured 3-way (ruamel.yaml, round-trip, keeps comments) |
| JSON | structured 3-way (order-preserving) |
| line-set (`.gitignore`) | set 3-way: add lines added upstream, drop lines removed upstream if still present, keep user lines |
| ini-like (`.editorconfig`) | structured 3-way by section/key |
| everything else (pkl, markdown, Jinja-rendered code) | `git merge-file` |

### 7.2 Structured 3-way

For each key path in base ∪ ours ∪ theirs:
- ours == base → take theirs (including deletion)
- theirs == base → keep ours
- ours == theirs → keep
- otherwise → **conflict**

Arrays are atomic by default. Arrays declared set-like in the catalog (workspace members, `extend-exclude`, …) use set merge. Edits apply to *ours'* document so formatting and comments survive.

Any key-level conflict makes the handler fall back to a whole-file `git merge-file` of the three texts, so the git-style markers land in context. The file is intentionally invalid until resolved, the same way a git conflict is.

A layer declares set-like arrays per file name, keyed by glob over the dotted key path. Identity is either the exact value or, for dependency lists, the normalized requirement name, so `pytest>=8` in ours matches `pytest` in theirs and keeps ours' text:

```toml
[merge."pyproject.toml"]
set_like = { "project.dependencies" = "requirement", "dependency-groups.*" = "requirement", "tool.uv.workspace.members" = "exact" }
```

### 7.3 Conflicts

- Write the markers, finish processing every other file, write the manifest, print a summary, and **exit non-zero**. Resolving the markers and committing completes the operation. There is no separate `--continue`, because the manifest already describes the new state.
- `tmpl status` lists files that still contain markers. The root hk config includes a conflict-marker check.

### 7.4 Missing base (adopt, or a new file colliding with an existing one)

- Structured files: keys only in theirs are added. Differing values **keep ours and are reported** (`--prefer template` flips this).
- Line-set files: union.
- Text files: whole-file conflict unless identical. `--prefer ours|template` resolves it without markers. `--prefer` only ever applies when there is no base; a real 3-way conflict always gets markers.
- Scaffold files (`scaffold = true`, e.g. a unit's `src/**`) are never created by adopt: an existing project already has its own layout.

## 8. Commands

Every mutating command refuses to run on a dirty worktree (`--allow-dirty` overrides) and supports `--dry-run`, which prints the full diff. Git is the undo mechanism.

### 8.1 `tmpl init [PATH]`

1. Create the directory, `git init`, and make an empty initial commit.
2. Collect root options, then units (`--unit python:cli@.`, repeatable; interactive otherwise) and options (`--opt key=value`).
3. Write the manifest, reconcile with base = ∅, force-add `third_party/.gitkeep`.
4. Run setup (§8.9) unless `--no-setup`.
5. Commit the scaffold.

### 8.2 `tmpl adopt [PATH]` — priority feature

1. **Detect** (§9) → proposed manifest; show it and confirm, or `--yes`. `--plan` writes the manifest **without a `version`** and stops, so it can be edited first; `tmpl sync` on a versionless manifest reconciles against base = ∅, exactly like adopt.
2. **Reconcile** with base = ∅ (§7.4). Never touch `seed` files that already exist; only config and tooling are reconciled.
3. **Record** the manifest. From here on, the base is `render(manifest, version)`, not the user's file. Existing differences therefore count as intentional edits, and future updates bring in only template changes.
4. Optionally run setup. Adopt never commits.

### 8.3 `tmpl add LANG:KIND[@PATH]`

Adds a unit (checked against the matrix and against existing units) and reconciles. Units never nest: a unit's path may not equal, contain, or lie inside another unit's path, since a package would enclose another's tree and workspace. The root unit `.` is the exception, as the workspace root sits above every member. `init` and `adopt` refuse nested units the same way. Unit options, and the language's options when the unit brings a new language, come from `--opt KEY=VALUE` or their defaults. Adding the first unit of a new language also pulls in that language's layer. Adding a second unit (or one off `.`) creates the workspace root.

### 8.4 `tmpl remove PATH`

Removes the unit from the manifest and reconciles:
- Unit-owned files are deleted **only if unchanged from base**. Modified ones are kept, listed, and cause a non-zero exit.
- Fragments leave shared files through the merge (base has them, target doesn't). User edits near them survive, and collisions become conflicts, never silent loss.
- If it was the last unit of its language, that language's layer (tools, hk steps, workspace root) is removed the same way.
- A directory emptied by deletions is removed.

### 8.5 `tmpl feature add|remove FEATURE [PATH]`

Attaches a feature to or detaches it from the root (no `PATH`) or the unit at `PATH`, checked against §4.3, and reconciles. Root features are stored in `[root] features`, unit features in the unit's `features`. Adding one already attached, or removing one that isn't, is refused. Removal follows the same rules as §8.4. Removing a unit also removes its features.

`feature add --opt KEY=VALUE` sets an option the feature declares. Its other options are stored with their defaults. Removing a feature, or the unit it's attached to, drops the options only it declared. Both print each change, as `update` does (§8.6).

### 8.6 `tmpl update [PATH] [--to VERSION]`

Bumps `version` (default: the latest `vX.Y.Z` tag in `source`, read with `git ls-remote`) and reconciles. The target release does the work: when it isn't the running one, tmpl runs `uvx --no-config --from <source>@v<VERSION> tmpl update --to <VERSION>` (`tmpl sync` for releases before 0.4.0, which lack `update`), passing `--prefer`, `--dry-run` and `--allow-dirty` on. The base is still rendered by the release that applied the manifest (§10).

Options follow the target release. Ones it declares that the manifest lacks are stored with their defaults, and ones it no longer declares are dropped. Each is printed (`new  [root] key = value`, `dropped  [unit apps/tool] key = value`). Stored values are never changed, so a changed default reaches only options added by the update. Every option has a default, so update asks nothing.

### 8.7 `tmpl sync`

Reconciles the current manifest at the current version, e.g. after a hand edit of `.config/tmpl.toml`.

`sync` and `update` take the repo as `PATH`, the other commands as `--repo`; both default to the current directory.

`tmpl set KEY=VALUE… [--unit PATH]` is that edit plus the sync in one step. Each key goes to the root, a language present, or the unit that declares it; `--unit` picks one when several units do. Values are checked against the option's type and choices, and live-sourced options (§3.2) are refused: edit their source file instead.

`add`, `remove`, `set`, `feature` and `update` need a manifest with a `version`; on one from `adopt --plan`, edit it and run `tmpl sync` instead.

The base is the manifest the last reconcile applied. Every reconcile stamps `applied`, the hash of the manifest's normalized content without that line. When the file still hashes to it, the file is the base. Otherwise it was hand-edited, and sync walks the file's git history, newest first, for the version with that hash; the common case needs no history, so shallow CI clones work. If no commit holds it (a reconcile left uncommitted, then edited again), sync refuses: commit reconciles before editing the manifest.

`--check` writes nothing. It prints the diff and exits 1 when a sync would change anything, including restamping the manifest's `version` or `applied` hash. It accepts a dirty worktree. With the root option `sync_check` (default `true`), the root layer adds an hk step `tmpl_sync` running `uvx --no-config --from <source>@v<version> tmpl sync --check`, the release the manifest records. The step is slow: it runs on `pre-push` and in CI. It catches drift that only a sync repairs, such as a PEP 723 header that no longer matches the `scripts` dependency group (§5.3). CI needs read access to `source`.

### 8.8 Read-only commands

- `tmpl status`: manifest summary, drift (managed files that differ from the target render), unresolved conflict markers.
- `tmpl diff`: what `sync`/`update` would change.
- `tmpl list`: support matrix, options, and defaults.

### 8.9 Setup

Runs after `init`, and optionally after `adopt`/`add`/`update` (`--setup`):
- `mise trust`, `mise install`, `mise lock`
- per language: `uv sync --all-packages`, `cargo fetch`, `go mod download`, `pnpm install` / `bun install` / `npm install`
- `hk install`

Language commands come from each language layer's top-level `setup = [["uv", "sync", "--all-packages"]]` and run through `mise exec --`. `init` commits the scaffold with `--no-verify`, since `hk install` has just enabled hooks on generated files.

## 9. Detection (adopt)

| Lang | Signals | Kind inference | Options inferred |
|---|---|---|---|
| python | `pyproject.toml`; PEP 723 `# /// script` blocks | `[project.scripts]` → cli, else lib; ask when both apply; dir of PEP 723 files → scripts; a pyproject that is not a package (no `[build-system]`, or `tool.uv.package = false`, as uv decides) → no unit, with a warning | type checkers from dev deps / `[tool.*]` tables; `[tool.uv.workspace]` members → one unit each |
| rust | `Cargo.toml` | `src/main.rs` / `[[bin]]` → cli; `src/lib.rs` → lib; ask when both | `[workspace] members` → one unit each |
| go | `go.mod` | `package main` → cli, else lib | `go.work` `use` entries → one unit each |
| ts | `package.json` | `bin` → cli; vite/next deps → webapp; else lib | package manager from lockfile or `packageManager`; test runner from devDeps |
| bash / zsh / sh | shebangs (`bash`, `zsh`, `sh`/`dash`), `*.sh`, `*.zsh`, `*.plugin.zsh` | dir of scripts → scripts; `*.plugin.zsh` → plugin | test framework from `*.bats` / `spec/` |
| lua | `*.rockspec`, `lua/<name>/` + `plugin/` | nvim layout → plugin; rockspec → lib | runtime |

The tool also detects existing mise, hk, and CI config and maps it into the reconcile (never deletes it). Tool config tmpl would duplicate rather than merge (a second mise or hk config, or `ruff.toml`, `mypy.ini`, `pytest.ini`/`pytest.toml`, `ty.toml`, `pyrightconfig.json`, `basedpyright.json` at the root or in `.config/`, where tmpl configures these tools in `pyproject.toml`) is reported for the user to fold in by hand. Paths under `third_party/`, `node_modules/`, `target/`, hidden dirs (including `.venv/`), `vendor/`/`vendors/`, and nested repos (any dir holding `.git`) are skipped. PEP 723 dirs inside a package unit (its `src/` and `tests/` for a unit at `.`) are not separate units, and one at the same path as a package unit is reported instead of adopted.

## 10. Versioning and base rendering

- `tmpl` releases are semver git tags (`v0.1.0`, …) on this repo. Templates ship inside the Python package, so a tag pins the tool and its templates together.
- The old base is rendered by **the old release itself**: `uvx --no-config --from git+<source>@v<old> tmpl render <tmp> --repo <repo> --manifest <applied>`, which renders the applied manifest (§8.7) with the repo's live-sourced options and writes the tree plus a `.tmpl-render.json` index of each file's policy. Rendering logic changes between versions can't corrupt the base. uv's cache keeps repeated updates cheap and makes them work offline after the first run.
- `render` is the internal, side-effect-free primitive: manifest in, file tree out. Every other command is built on it, and it is the stable contract between versions. `tmpl render` produces the base side (§2.3).

## 11. Implementation

### 11.1 Stack

Python + cyclopts. Dependencies: jinja2, tomlkit, ruamel.yaml, attrs + cattrs (manifest/catalog models); git via subprocess (`git merge-file`, `git init`, `git add -f`). Distributed via `uv tool install` / mise `pipx:`.

### 11.2 Repo layout

```
.config/{mise,hk.pkl,…}          # this repo is itself a tmpl-managed python/cli unit
pyproject.toml
src/tmpl/
  cli.py                          # cyclopts app
  manifest.py                     # .config/tmpl.toml model + live-sourced options
  catalog.py                      # loads templates/, validates matrix + options
  render.py                       # manifest → in-memory file tree
  sinks.py                        # mise, hk, ci, gitignore, editorconfig, workspace, markdown
  merge.py                        # toml, yaml, json, lineset, ini, text (git merge-file)
  reconcile.py                    # base/ours/target → actions, conflicts, report
  docs.py                         # type guards over parsed documents
  git.py, proc.py                 # subprocess helpers
  detect/                         # per-language adopt detectors
  setup.py                        # post-render setup runners (not in the prototype)
  templates/
    root/{template.toml, files/}
    lang/<lang>/{template.toml, files/, unit/, kind/<kind>/}
    kind/<kind>/{template.toml, files/}
    feature/<feature>/{template.toml, files/}     # language parts: lang/<lang>/feature/<feature>/
tests/
```

### 11.3 Layer definition (`template.toml`)

A layer is a directory with an optional `template.toml` and an optional `files/` tree. Everything under `files/` renders at the layer's placement (the repo root, or the unit's path for unit layers). Path segments are Jinja templates, and a `.jinja` suffix marks content to render and is stripped. Files are `merge` unless a `[files."<glob>"]` rule says otherwise.

```toml
# templates/lang/python/template.toml
[options.python_version]
scope = "lang"
default = "3.14"
source = "pyproject.toml:project.requires-python"   # live-sourced: read from the repo, never stored
source_pattern = '(\d+\.\d+)'

[options.type_checker_fast]
scope = "lang"
choices = ["basedpyright", "pyright", "ty", "mypy", "none"]
default = "basedpyright"

[vars]                          # constants merged into the render context
checker_builtin = { ty = "ty", mypy = "mypy" }

[[fragment]]
sink = "mise.tools"
data = { python = "{{ python_version }}", uv = "latest" }

[[fragment]]
sink = "hk.steps"
order = 40                      # sorts within the sink; ties keep layer order
when = "{{ type_checker_fast != 'none' }}"   # rendered; the fragment applies when it is "True"
data = { name = "{{ type_checker_fast }}", builtin = "{{ checker_builtin.get(type_checker_fast, '') }}", hooks = ["pre-commit", "check"] }
```

```toml
# templates/lang/python/kind/cli/template.toml
[files."**"]                    # every file of this layer is scaffold source
policy = "seed"
scaffold = true

[[patch]]                       # deep-merged into a TOML file another layer renders at the same placement
dest = "pyproject.toml"
data = { project = { dependencies = ["cyclopts"], scripts = { "{{ unit.name }}" = "{{ unit.slug }}.cli:main" } } }
```

```toml
# templates/lang/python/kind/scripts/template.toml
package = false                 # not a package: skip lang/python/unit (§2.2)
```

```toml
# templates/feature/deps-update/template.toml
attaches = "root"               # declares a feature (§4.3); a unit feature may add `kinds = ["cli", …]`
```

Data values render as Jinja strings; a value that renders to `""` is dropped, which is how optional keys (like `builtin` above) disappear.

### 11.4 Testing

- **Snapshots:** render every matrix cell plus representative combinations (one per repo shape in §2.1).
- **Invariants,** checked for every scenario:
  - `sync` right after `init` produces no changes (idempotent).
  - `init A; add B; remove B` ≡ `init A` when nothing was edited.
  - `update` from vN to vN is a no-op.
  - user edits in extension points never conflict.
- **Adopt fixtures:** small realistic repos per language and shape, each with expected manifest and reconcile output.
- **End-to-end (slow, marked):** generated repos pass `mise run check`.

## 12. Migration from the Copier repo

1. Port the good content of `template/` and `copier.yml` into `templates/` layers and fragments. That covers license selection, the editorconfig options, the current hk steps, and the per-language scaffolds.
2. **Done:** `copier.yml`, `extensions.py`, `post-task.sh`, and `template/` are removed, along with the `children/*` submodules. Their upstream repos (`kemus/_tmpl_{python,rust,lua,shell,typescript}`) are to be deleted, not archived. Per-language scaffolds are written fresh from this spec rather than ported.
3. Adopt this repo itself as a `python/cli` unit.
4. Adopt existing Copier-generated projects with `tmpl adopt`. Their `.config/copier/*answers*.yml` files seed detection and are then deleted.

## 13. Decisions

### 13.1 Resolved

| # | Question | Decision |
|---|---|---|
| 1 | CLI language | Python + cyclopts |
| 2 | Kinds | cli, lib, scripts, plugin, service, webapp, tui, mcp-server, github-action, vscode-extension, browser-extension, all in the initial scope (§4.2) |
| 2a | Cross-cutting add-ons | a separate **features** concept: release, container, docs, deps-update, coverage, bench, fuzz, community, cli-extras, security-scan (§4.3) |
| 3 | POSIX sh | kept as its own language, `sh` |
| 4 | hk extension | no extension point; `hk.pkl` is edited directly and updated by 3-way text merge. (Checked with hk 2.1.0: `.config/hk.local.pkl` is documented as a personal, gitignored override, and a Pkl `import* "hk.d/*.pkl"` pattern works but was not chosen.) |
| 5 | Agent files | `AGENTS.md` only; current Claude versions read `AGENTS.md`. No empty `.omni/` placeholder: a `.gitkeep` there only earns its place once the template ships other `.omni/` content |
| 6 | Adopt value differences | keep ours + report; `--prefer template` flips it |
| 7 | Go CLI default | kong (cobra, urfave/cli, stdlib `flag` remain options) |
| 8 | License | `LICENSE` is part of the root baseline, default MIT |
| 9 | Secret scanning | betterleaks, not gitleaks |
| 10 | Service defaults | python FastAPI, go Huma on `net/http` (FastAPI-style typed handlers + OpenAPI), rust axum, ts Hono |
| 11 | Webapp default | Vite + React |
| 12 | Python MCP library | official `mcp` SDK |
| 13 | Changelog tooling (`release`) | git-cliff |
| 14 | Docs generator | picked by languages present: mkdocs-material → vitepress → mdbook; overridable |
| 15 | Dependency updates | Renovate |
| 16 | JS fuzzing | Jazzer.js |
| 17 | tui | stays its own kind |
| 18 | Python type checking | basedpyright on normal runs (check, pre-commit); mypy on pre-push and CI |
| 19 | Rust tests | cargo-nextest (+ doctests via `cargo test --doc`) |
| 20 | TS lint/format | oxlint + prettier |
| 21 | JS package manager default | pnpm + node |
| 22 | Shell tests | shellspec for bash, zsh, and sh |
| 23 | Lua | LuaJIT default; rockspec + luarocks for libs; nvim plugins tested with busted via nlua |
| 24 | TS cli / lib | commander; tsdown |
| 25 | github-action (python/go/rust) | composite: `uvx` for python, prebuilt release binary for go/rust |
| 26 | Extensions | split into `vscode-extension` and `browser-extension` (WXT) kinds |
| 27 | python/scripts | PEP 723 uv scripts |
| 28 | bash/sh cli | hand-rolled while/case parser |
| 29 | `container` | distroless for compiled, slim for interpreted, multi-stage, digest-pinned |
| 30 | Rust `release` | cargo-dist + crates.io |
| 31 | `coverage` | CI job summary only |
| 32 | Rust `bench` | divan |
| 33 | `community` | no code of conduct |

### 13.2 Still open

None.
