"""The `tmpl` command line."""

import json
import re
import sys
import tempfile
import tomllib
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated

import attrs
import cattrs
from cyclopts import App, Parameter

from tmpl import __version__, catalog, convert, git, manifest, proc, reconcile, setup
from tmpl.detect import DetectError, detect
from tmpl.manifest import Manifest, Options, Unit
from tmpl.merge import Prefer
from tmpl.render import RenderedFile, RenderError, Tree, render

RENDER_INDEX = ".tmpl-render.json"
VERSIONLESS = f"{manifest.MANIFEST_PATH} has no version yet (from `adopt --plan`); edit it, then run `tmpl sync`"

app = App(name="tmpl", version=__version__, help="Composable, updatable project templates.")


class UsageError(Exception):
    pass


def _out(text: str) -> None:
    sys.stdout.write(text.rstrip("\n") + "\n")


def _err(text: str) -> None:
    sys.stderr.write(text.rstrip("\n") + "\n")


def _check_repo(repo: Path, *, allow_dirty: bool) -> None:
    if not git.is_repo(repo):
        msg = f"{repo} is not a git repository"
        raise UsageError(msg)
    dirty = git.dirty_paths(repo)
    if dirty and not allow_dirty:
        msg = f"worktree has uncommitted changes ({', '.join(dirty[:5])}); commit them or pass --allow-dirty"
        raise UsageError(msg)


type Flag = Annotated[bool, Parameter(negative=())]


@Parameter(name="*")
@attrs.define
class Reconcile:
    """Options shared by commands that reconcile the repo.

    Parameters
    ----------
    prefer
        Resolve differences with existing files (no base yet) toward ours or the template.
    dry_run
        Print the diff instead of writing.
    allow_dirty
        Run even with uncommitted changes.
    """

    prefer: Prefer | None = None
    dry_run: Flag = False
    allow_dirty: Flag = False


def _finish(repo: Path, actions: list[reconcile.Action], *, dry_run: bool) -> int:
    if dry_run:
        sys.stdout.write(reconcile.diff(repo, actions))
    else:
        reconcile.apply(repo, actions)
    _out(reconcile.summary(actions))
    return 1 if any(a.failed for a in actions) else 0


UNIT_SPEC = re.compile(r"(?P<lang>[a-z]+):(?P<kind>[a-z]+)(?:@(?P<path>.+))?")


def _parse_unit(spec: str) -> Unit:
    match = UNIT_SPEC.fullmatch(spec.strip())
    if match is None:
        msg = f"unit {spec!r}: expected LANG:KIND[@PATH], e.g. python:cli@."
        raise UsageError(msg)
    lang, kind, path = match["lang"], match["kind"], _unit_path(match["path"] or ".")
    if not catalog.supported(lang, kind):
        msg = f"unit {spec!r}: {lang}/{kind} is not in this version's catalog"
        raise UsageError(msg)
    return Unit(path, lang, kind)


def _unit_path(path: str) -> str:
    return path.strip().strip("/") or "."


def _overlap_text(path: str, other: str) -> str:
    if path == other:
        return f"a unit already lives at {path}"
    return (
        f"a unit at {path} would nest with the unit at {other}; units can't contain one another, except the root unit"
    )


def _find_unit(current: Manifest, path: str) -> Unit:
    path = _unit_path(path)
    for unit in current.unit:
        if unit.path == path:
            return unit
    msg = f"no unit at {path}; units: {', '.join(u.path for u in current.unit)}"
    raise UsageError(msg)


def _parse_opts(pairs: list[str]) -> dict[str, object]:
    opts: dict[str, object] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            msg = f"option {pair!r}: expected KEY=VALUE"
            raise UsageError(msg)
        opts[key.strip()] = value.strip()
    return opts


def _new_manifest(repo: Path, units: list[Unit], given: dict[str, object]) -> Manifest:
    """Route each `--opt` to every scope that declares it: root, the units' languages, the units."""
    claimed: set[str] = set()

    def take(specs: dict[str, catalog.OptionSpec]) -> dict[str, object]:
        picked = {k: v for k, v in given.items() if k in specs}
        claimed.update(picked)
        return picked

    root_specs = catalog.root_options([])
    created = Manifest(root=catalog.resolve(root_specs, take(root_specs), repo).stored)
    for lang in dict.fromkeys(u.lang for u in units):
        specs = catalog.lang_options(lang, [])
        if stored := catalog.resolve(specs, take(specs), repo).stored:
            created.lang[lang] = stored
    for unit in units:
        specs = catalog.unit_options(unit.lang, unit.kind, unit.features)
        unit.options = catalog.resolve(specs, take(specs), repo / unit.path).stored
        created.unit.append(unit)
    if unknown := sorted(set(given) - claimed):
        msg = f"unknown options for these units: {unknown}"
        raise UsageError(msg)
    return created


@app.command
def init(
    path: Path = Path(),
    *,
    unit: list[str] | None = None,
    opt: list[str] | None = None,
    no_setup: Flag = False,
) -> int:
    """Create a new repo: git init, render the manifest's files, run setup, commit the scaffold.

    Parameters
    ----------
    path
        Directory to create (it may exist if empty).
    unit
        LANG:KIND[@PATH], repeatable. Asked for when omitted.
    opt
        KEY=VALUE for any root, language or unit option, repeatable.
    no_setup
        Skip `mise install`, dependency sync and `hk install`.
    """
    repo = path.resolve()
    if repo.exists() and any(repo.iterdir()):
        msg = f"{repo} is not empty; use `tmpl adopt` for an existing repo"
        raise UsageError(msg)
    specs = unit or [s for s in input("Units (LANG:KIND[@PATH], comma-separated): ").split(",") if s.strip()]
    if not specs:
        msg = "no units given"
        raise UsageError(msg)
    units = [_parse_unit(spec) for spec in specs]
    for index, parsed in enumerate(units):
        if other := manifest.overlap(parsed.path, [u.path for u in units[:index]]):
            raise UsageError(_overlap_text(parsed.path, other))
    given = _parse_opts(opt or [])
    created = _new_manifest(repo, units, given)
    created.version = __version__

    repo.mkdir(parents=True, exist_ok=True)
    git.run(repo, "init", "-q")
    git.run(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", "initial commit")
    if "author" not in given:
        created.root["author"] = git.config(repo, "user.name") or ""
    # An empty base, unlike adopt's missing one, creates scaffold source.
    actions = reconcile.plan(repo, {}, render(created, repo.name, repo))
    manifest.stamp(created)
    manifest.dump(repo, created)
    reconcile.apply(repo, actions)
    if not no_setup:
        setup.run(repo, created.langs)
    git.run(repo, "add", "-A")
    # Hooks are not run: the scaffold is generated, and `hk install` may have just enabled them.
    git.run(repo, "commit", "-q", "--no-verify", "-m", f"chore: scaffold with tmpl {__version__}")
    _out(reconcile.summary(actions))
    return 0


@app.command
def adopt(
    path: Path = Path(),
    *,
    yes: Flag = False,
    plan: Flag = False,
    opts: Reconcile | None = None,
) -> int:
    """Bring an existing repo under tmpl: detect units, reconcile config against an empty base.

    Parameters
    ----------
    path
        Repository to adopt.
    yes
        Accept the detected manifest without asking.
    plan
        Write the detected manifest (without a version) and stop; edit it, then run `tmpl sync`.
    """
    opts = opts or Reconcile()
    repo = path.resolve()
    _check_repo(repo, allow_dirty=opts.allow_dirty or opts.dry_run)
    if manifest.load(repo) is not None:
        msg = f"{repo} already has {manifest.MANIFEST_PATH}; use `tmpl sync`"
        raise UsageError(msg)
    detected = detect(repo)
    for warning in detected.warnings:
        _err(f"warning: {warning}")
    proposed = detected.manifest
    _out(manifest.dumps(proposed))
    if plan:
        manifest.dump(repo, proposed)
        _out(f"wrote {manifest.MANIFEST_PATH}; edit it, then run `tmpl sync`")
        return 0
    if not (yes or opts.dry_run) and input("Adopt with this manifest? [y/N] ").strip().lower() != "y":
        return 1
    proposed.version = __version__
    actions = reconcile.plan(repo, None, render(proposed, repo.name, repo), opts.prefer)
    if not opts.dry_run:
        manifest.stamp(proposed)
        manifest.dump(repo, proposed)
    return _finish(repo, actions, dry_run=opts.dry_run)


@app.command
def sync(path: Path = Path(), *, check: Flag = False, opts: Reconcile | None = None) -> int:
    """Reconcile the repo with its manifest at this tmpl version.

    `--prefer` only applies to a versionless manifest from `adopt --plan`.

    Parameters
    ----------
    path
        Repository to sync.
    check
        Write nothing, print the diff, and exit 1 if a sync would change anything (implies --allow-dirty).
    """
    return _reconcile(path.resolve(), opts or Reconcile(), check=check)


# The first release with `update`; an update to an earlier one runs its `sync`.
FIRST_UPDATE = (0, 4, 0)
RELEASE_TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)")


@app.command
def update(path: Path = Path(), *, to: str | None = None, opts: Reconcile | None = None) -> int:
    """Move the repo to another tmpl release (default: the latest) and reconcile.

    The target release does the work, so its templates and options apply: options it declares that the manifest
    lacks are recorded with their defaults, and options it no longer declares are dropped; both are listed.

    Parameters
    ----------
    path
        Repository to update.
    to
        Release version, e.g. 0.4.0; defaults to the latest release tag in the manifest's `source`.
    """
    repo, opts = path.resolve(), opts or Reconcile()
    current = manifest.load(repo)
    if current is None:
        msg = f"no {manifest.MANIFEST_PATH} in {repo}; use `tmpl adopt`"
        raise UsageError(msg)
    if not current.version:
        raise UsageError(VERSIONLESS)
    source = current.source or manifest.DEFAULT_SOURCE
    target = _version(to.removeprefix("v")) if to else _latest_release(repo, source)
    if target == _version(__version__):
        # No change of its own: the reconcile's option refresh is the update.
        return _reconcile(repo, opts, lambda _: None, downgrade=True)
    release = ".".join(map(str, target))
    command = ["update", "--to", release] if target >= FIRST_UPDATE else ["sync"]
    flags = [
        *(["--prefer", opts.prefer] if opts.prefer else []),
        *(["--dry-run"] if opts.dry_run else []),
        *(["--allow-dirty"] if opts.allow_dirty else []),
    ]
    _out(f"tmpl {__version__}: running tmpl {release}")
    # `--no-config`: a user `no-build` would refuse the git source.
    args = ("uvx", "--no-config", "--from", f"{source}@v{release}", "tmpl", *command, str(repo), *flags)
    return proc.run(*args, capture=False).returncode


def _version(text: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", text):
        msg = f"version {text!r}: expected X.Y.Z"
        raise UsageError(msg)
    return tuple(int(part) for part in text.split("."))


def _latest_release(repo: Path, source: str) -> tuple[int, ...]:
    refs = git.run(repo, "ls-remote", "--tags", "--refs", source.removeprefix("git+"))
    found = [tuple(map(int, m.groups())) for m in map(RELEASE_TAG.fullmatch, refs.split()) if m]
    if not found:
        msg = f"no release tags (vX.Y.Z) in {source}"
        raise UsageError(msg)
    return max(found)


def _refresh_options(repo: Path, current: Manifest) -> None:
    """Store the options this version declares: new ones at their defaults, undeclared ones dropped (§8.6)."""

    def refresh(where: str, specs: dict[str, catalog.OptionSpec], given: dict[str, object], live: Path) -> Options:
        stored = catalog.resolve(specs, _picked(given, specs), live).stored
        for key in sorted(stored.keys() - given.keys()):
            _out(f"     new  {where} {key} = {stored[key]!r}")
        for key in sorted(given.keys() - stored.keys()):
            _out(f" dropped  {where} {key} = {given[key]!r}")
        return stored

    features = current.features
    current.root = refresh("[root]", catalog.root_options(features), current.root_options, repo)
    current.features = features
    for lang in current.langs:
        specs = catalog.lang_options(lang, current.lang_features(lang))
        if stored := refresh(f"[lang.{lang}]", specs, current.lang.get(lang, {}), repo):
            current.lang[lang] = stored
        else:
            current.lang.pop(lang, None)
    for unit in current.unit:
        specs = catalog.unit_options(unit.lang, unit.kind, unit.features)
        unit.options = refresh(f"[unit {unit.path}]", specs, unit.options, repo / unit.path)


def _reconcile(
    repo: Path,
    opts: Reconcile,
    change: Callable[[Manifest], None] | None = None,
    *,
    check: bool = False,
    downgrade: bool = False,
) -> int:
    """Apply `change` to the manifest, then reconcile against the render of the manifest as last applied (§2.3).

    A change also stores the options this version declares (§8.6). Only `update` (`downgrade`) may reconcile a
    manifest a later release wrote.
    """
    _check_repo(repo, allow_dirty=opts.allow_dirty or opts.dry_run or check)
    current = manifest.load(repo)
    if current is None:
        msg = f"no {manifest.MANIFEST_PATH} in {repo}; use `tmpl adopt`"
        raise UsageError(msg)
    if not downgrade and current.version and _version(current.version) > _version(__version__):
        msg = (
            f"{manifest.MANIFEST_PATH} is at tmpl {current.version}, later than this tmpl {__version__}; "
            f"use tmpl {current.version} or later, or `tmpl update --to {__version__}` to move back"
        )
        raise UsageError(msg)
    applied = _applied(repo, current)
    if change is not None and applied is None:
        raise UsageError(VERSIONLESS)
    # Before any change: `applied` may be `current` itself.
    base = _render_base(applied, repo) if applied else None
    if change is not None:
        change(current)
        _refresh_options(repo, current)
    current.version = __version__
    manifest.stamp(current)
    actions = reconcile.plan(repo, base, render(current, repo.name, repo), opts.prefer)
    if check:
        return _check(repo, actions, current)
    if not opts.dry_run:
        manifest.dump(repo, current)
    return _finish(repo, actions, dry_run=opts.dry_run)


@app.command
def add(spec: str, *, opt: list[str] | None = None, repo: Path = Path(), opts: Reconcile | None = None) -> int:
    """Add a unit to the manifest and reconcile; options not given take their defaults.

    Parameters
    ----------
    spec
        LANG:KIND[@PATH], e.g. python:cli@apps/tool; PATH is relative to the repo root and defaults to `.`.
    opt
        KEY=VALUE for a unit option, or a language option when the unit brings a new language; repeatable.
    repo
        Repository to change.
    """
    root = repo.resolve()
    unit = _parse_unit(spec)
    given = _parse_opts(opt or [])

    def change(current: Manifest) -> None:
        if other := manifest.overlap(unit.path, [u.path for u in current.unit]):
            raise UsageError(_overlap_text(unit.path, other))
        unit_specs = catalog.unit_options(unit.lang, unit.kind, unit.features)
        new_lang = unit.lang not in current.langs
        lang_specs = catalog.lang_options(unit.lang, current.features) if new_lang else {}
        if unknown := sorted(set(given) - set(unit_specs) - set(lang_specs)):
            hint = "" if new_lang else f"; set {unit.lang} options with `tmpl set`"
            msg = f"unknown options for this unit: {unknown}{hint}"
            raise UsageError(msg)
        unit.options = catalog.resolve(unit_specs, _picked(given, unit_specs), root / unit.path).stored
        if lang_specs and (stored := catalog.resolve(lang_specs, _picked(given, lang_specs), root).stored):
            current.lang[unit.lang] = stored
        current.unit.append(unit)

    return _reconcile(root, opts or Reconcile(), change)


@app.command
def remove(path: str, *, repo: Path = Path(), opts: Reconcile | None = None) -> int:
    """Remove the unit at PATH from the manifest and reconcile.

    Its files are deleted only if unchanged from the last reconcile; modified ones are kept and listed, and the
    command exits 1. Removing a language's last unit removes the language too.

    Parameters
    ----------
    path
        Unit path relative to the repo root.
    repo
        Repository to change.
    """

    root = repo.resolve()

    def change(current: Manifest) -> None:
        unit = _find_unit(current, path)
        current.unit.remove(unit)
        if unit.lang not in current.langs:
            current.lang.pop(unit.lang, None)

    return _reconcile(root, opts or Reconcile(), change)


@app.command(name="set")
def set_cmd(*pairs: str, unit: str | None = None, repo: Path = Path(), opts: Reconcile | None = None) -> int:
    """Set manifest options and reconcile.

    Parameters
    ----------
    pairs
        KEY=VALUE for a root, language or unit option.
    unit
        Path of the unit whose option to set; needed when several units declare it.
    repo
        Repository to change.
    """
    given = _parse_opts(list(pairs))
    if not given:
        msg = "no KEY=VALUE given"
        raise UsageError(msg)

    def change(current: Manifest) -> None:
        for key, value in given.items():
            table, spec = _option_table(current, key, unit)
            table[key] = spec.coerce(key, value)

    return _reconcile(repo.resolve(), opts or Reconcile(), change)


feature_app = App(name="feature", help="Attach features to the root or a unit, or detach them.")
app.command(feature_app)


@feature_app.command(name="add")
def feature_add(
    feature: str,
    path: str | None = None,
    *,
    opt: list[str] | None = None,
    repo: Path = Path(),
    opts: Reconcile | None = None,
) -> int:
    """Attach FEATURE to the root, or to the unit at PATH, and reconcile; its options not given take their defaults.

    Parameters
    ----------
    feature
        Feature name; unknown names list the features this version ships.
    path
        Unit path relative to the repo root; omit for a root feature.
    opt
        KEY=VALUE for an option the feature declares; repeatable.
    repo
        Repository to change.
    """
    root = repo.resolve()
    given = _parse_opts(opt or [])

    def change(current: Manifest) -> None:
        unit = _find_unit(current, path) if path is not None else None
        problem = catalog.feature_problem(feature, unit.lang, unit.kind) if unit else catalog.feature_problem(feature)
        if problem:
            raise UsageError(problem)
        attached = unit.features if unit else current.features
        if feature in attached:
            msg = f"feature {feature!r} is already attached to {_where(unit)}"
            raise UsageError(msg)
        if unit:
            unit.features.append(feature)
        else:
            current.features = [*attached, feature]
        _set_feature_options(current, feature, unit, given)

    return _reconcile(root, opts or Reconcile(), change)


@feature_app.command(name="remove")
def feature_remove(feature: str, path: str | None = None, *, repo: Path = Path(), opts: Reconcile | None = None) -> int:
    """Detach FEATURE from the root, or from the unit at PATH, and reconcile.

    Its files are deleted only if unchanged from the last reconcile; modified ones are kept and listed, and the
    command exits 1.

    Parameters
    ----------
    feature
        Feature name.
    path
        Unit path relative to the repo root; omit for a root feature.
    repo
        Repository to change.
    """
    root = repo.resolve()

    def change(current: Manifest) -> None:
        unit = _find_unit(current, path) if path is not None else None
        attached = unit.features if unit else current.features
        if feature not in attached:
            msg = f"feature {feature!r} is not attached to {_where(unit)}; attached: {', '.join(attached) or 'none'}"
            raise UsageError(msg)
        if unit:
            unit.features.remove(feature)
        else:
            current.features = [f for f in attached if f != feature]

    return _reconcile(root, opts or Reconcile(), change)


def _where(unit: Unit | None) -> str:
    return f"the unit at {unit.path}" if unit else "the root"


def _set_feature_options(current: Manifest, feature: str, unit: Unit | None, given: dict[str, object]) -> None:
    """Store each of `given` in the table of the scope that declares it among `feature`'s layers."""
    langs = [unit.lang] if unit else current.langs
    scopes: list[tuple[Callable[[], Options], dict[str, catalog.OptionSpec]]] = [
        (partial(getattr, unit, "options"), catalog.options_for(catalog.feature_layer_ids(feature, unit.lang), "unit"))
        if unit
        else (lambda: current.root, catalog.options_for([f"feature/{feature}"], "root")),
    ]
    scopes += [
        (partial(current.lang.setdefault, lang, {}), catalog.options_for([f"lang/{lang}/feature/{feature}"], "lang"))
        for lang in langs
    ]
    for key, value in given.items():
        found = [(table, spec) for table, specs in scopes if (spec := specs.get(key))]
        if not found:
            msg = f"option {key!r}: not declared by feature {feature!r}"
            raise UsageError(msg)
        table, spec = found[0]
        if spec.source:
            msg = f"option {key!r} is read from {spec.source}; edit that instead"
            raise UsageError(msg)
        table()[key] = spec.coerce(key, value)


def _picked(given: dict[str, object], specs: dict[str, catalog.OptionSpec]) -> dict[str, object]:
    return {k: v for k, v in given.items() if k in specs}


def _option_table(current: Manifest, key: str, unit: str | None) -> tuple[dict[str, object], catalog.OptionSpec]:
    """The manifest table storing option `key`, with its spec: the root, a language present, or a unit."""
    # Each scope's table is fetched only once the key matches, so a language gains no empty table.
    scopes: list[tuple[Callable[[], dict[str, object]], dict[str, catalog.OptionSpec]]] = []
    if unit is None:
        scopes.append((lambda: current.root, catalog.root_options(current.features)))
        scopes += [
            (partial(current.lang.setdefault, lang, {}), catalog.lang_options(lang, current.lang_features(lang)))
            for lang in current.langs
        ]
    units = current.unit if unit is None else [_find_unit(current, unit)]
    scopes += [(partial(getattr, u, "options"), catalog.unit_options(u.lang, u.kind, u.features)) for u in units]
    found = [(table, spec) for table, specs in scopes if (spec := specs.get(key))]
    if not found:
        where = f"the unit at {_unit_path(unit)}" if unit is not None else "this repo's layers"
        msg = f"option {key!r}: not declared by {where}"
        raise UsageError(msg)
    if len(found) > 1:
        msg = f"option {key!r} is declared by several units; pass --unit PATH"
        raise UsageError(msg)
    table, spec = found[0]
    if spec.source:
        msg = f"option {key!r} is read from {spec.source}; edit that instead"
        raise UsageError(msg)
    return table(), spec


def _applied(repo: Path, current: Manifest) -> Manifest | None:
    """The manifest as the last reconcile applied it, the base's desired state (§2.3); None before any reconcile.

    A hand edit since then leaves `applied` naming an earlier content, which the manifest's git history holds.
    """
    if not current.version:
        return None
    if current.applied is None or manifest.digest(current) == current.applied:
        return current
    for text in git.file_history(repo, manifest.MANIFEST_PATH.as_posix()):
        try:
            past = manifest.loads(text)
        except (tomllib.TOMLDecodeError, cattrs.BaseValidationError):
            continue
        if manifest.digest(past) == current.applied:
            return past
    msg = (
        f"{manifest.MANIFEST_PATH} was edited since the last reconcile, and no commit holds the manifest that "
        f"reconcile wrote ({current.applied}); commit reconciles before editing the manifest"
    )
    raise UsageError(msg)


def _check(repo: Path, actions: list[reconcile.Action], stamped: Manifest) -> int:
    """Report drift: any action but a note, or a manifest a sync would rewrite (new version or hand edits)."""
    drift = [a for a in actions if a.op != "noted"]
    path = manifest.MANIFEST_PATH.as_posix()
    if (repo / path).read_text() != (text := manifest.dumps(stamped)):
        drift.append(reconcile.Action(path, "update", text))
    if not drift:
        return 0
    sys.stdout.write(reconcile.diff(repo, drift))
    _out(reconcile.summary(drift))
    _err("tmpl: out of sync with the manifest; run `tmpl sync`")
    return 1


def _render_base(recorded: Manifest, repo: Path) -> Tree:
    """Render the manifest with the tmpl release that produced it (§10)."""
    if recorded.version == __version__:
        return render(recorded, repo.name, repo, base=True)
    with tempfile.TemporaryDirectory() as tmp:
        out, applied = Path(tmp) / "out", Path(tmp) / "tmpl.toml"
        # The repo's manifest may carry hand edits since; the release renders the applied one.
        applied.write_text(manifest.dumps(recorded))
        # `--no-config`: a user `no-build` would refuse the git source.
        release = ("uvx", "--no-config", "--from", recorded.spec, "tmpl")
        proc.check(*release, "render", "--repo", str(repo), "--manifest", str(applied), "--out", str(out))
        index = json.loads((out / RENDER_INDEX).read_text())
        # A later release may index fields this one lacks; drop them so a downgrade still renders its base.
        known = attrs.fields_dict(RenderedFile).keys() - {"content"}
        return {
            path: RenderedFile((out / path).read_text(), **{k: v for k, v in meta.items() if k in known})
            for path, meta in index.items()
        }


@app.command(name="render")
def render_cmd(
    out: Path,
    *,
    repo: Path = Path(),
    manifest_file: Annotated[Path | None, Parameter(name="--manifest")] = None,
) -> int:
    """Render the repo's manifest into OUT, with a policy index: the base for syncs from a later tmpl version.

    Parameters
    ----------
    out
        Empty output directory.
    repo
        Repository whose manifest (and live-sourced options) to render.
    manifest_file
        Render this manifest instead of the repo's, with the repo's live-sourced options.
    """
    repo = repo.resolve()
    recorded = manifest.loads(manifest_file.read_text()) if manifest_file else manifest.load(repo)
    if recorded is None:
        msg = f"no {manifest.MANIFEST_PATH} in {repo}"
        raise UsageError(msg)
    tree = render(recorded, repo.name, repo, base=True)
    index: dict[str, dict[str, object]] = {}
    for path, file in tree.items():
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(file.content)
        index[path] = {"policy": file.policy, "scaffold": file.scaffold, "force_add": file.force_add}
    (out / RENDER_INDEX).write_text(json.dumps(index, indent=2) + "\n")
    return 0


def main() -> None:
    try:
        code = app()
    except (
        UsageError,
        DetectError,
        RenderError,
        git.GitError,
        proc.MissingToolError,
        proc.ToolError,
        ValueError,
    ) as exc:
        _err(f"tmpl: {exc}")
        code = 2
    except cattrs.BaseValidationError as exc:
        _err(f"tmpl: {convert.error_text(exc)}")
        code = 2
    sys.exit(code if isinstance(code, int) else 0)
