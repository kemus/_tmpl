"""The `tmpl` command line."""

import json
import re
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Annotated

import attrs
import cattrs
from cyclopts import App, Parameter

from tmpl import __version__, catalog, convert, git, manifest, proc, reconcile, setup
from tmpl.detect import DetectError, detect
from tmpl.manifest import Manifest, Unit
from tmpl.merge import Prefer
from tmpl.render import RenderedFile, RenderError, Tree, render

RENDER_INDEX = ".tmpl-render.json"

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
    lang, kind, path = match["lang"], match["kind"], (match["path"] or ".").strip("/") or "."
    if not catalog.supported(lang, kind):
        msg = f"unit {spec!r}: {lang}/{kind} is not in this version's catalog"
        raise UsageError(msg)
    return Unit(path, lang, kind)


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

    root_specs = catalog.options_for(["root"], "root")
    created = Manifest(root=catalog.resolve(root_specs, take(root_specs), repo).stored)
    for lang in dict.fromkeys(u.lang for u in units):
        specs = catalog.options_for([f"lang/{lang}"], "lang")
        if stored := catalog.resolve(specs, take(specs), repo).stored:
            created.lang[lang] = stored
    for unit in units:
        specs = catalog.options_for(catalog.unit_layer_ids(unit.lang, unit.kind), "unit")
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
    if len({u.path for u in units}) != len(units):
        msg = "two units share a path"
        raise UsageError(msg)
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
    opts = opts or Reconcile()
    repo = path.resolve()
    _check_repo(repo, allow_dirty=opts.allow_dirty or opts.dry_run or check)
    current = manifest.load(repo)
    if current is None:
        msg = f"no {manifest.MANIFEST_PATH} in {repo}; use `tmpl adopt`"
        raise UsageError(msg)
    applied = _applied(repo, current)
    base = _render_base(applied, repo) if applied else None
    current.version = __version__
    manifest.stamp(current)
    actions = reconcile.plan(repo, base, render(current, repo.name, repo), opts.prefer)
    if check:
        return _check(repo, actions, current)
    if not opts.dry_run:
        manifest.dump(repo, current)
    return _finish(repo, actions, dry_run=opts.dry_run)


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
        return {path: RenderedFile((out / path).read_text(), **meta) for path, meta in index.items()}


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
