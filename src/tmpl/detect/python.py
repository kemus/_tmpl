"""Python detection: pyproject.toml units, kinds, PEP 723 script dirs, and type checkers."""

from __future__ import annotations

import re
import tomllib
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import attrs

from tmpl.docs import is_map, is_seq
from tmpl.manifest import Options, Unit

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

FAST_CHECKERS = ("basedpyright", "pyright", "ty")
SKIP_DIRS = frozenset({"third_party", "node_modules", "target", "vendor", "vendors", "dist", "build"})
PEP723 = re.compile(r"^# /// script$", re.MULTILINE)


@attrs.define
class Found:
    units: list[Unit] = attrs.field(factory=list[Unit])
    lang_options: Options = attrs.field(factory=dict[str, object])
    warnings: list[str] = attrs.field(factory=list[str])


def detect(repo: Path) -> Found:
    found = Found()
    root = _load(repo / "pyproject.toml") or {}
    candidates = (["."] if is_map(root.get("project")) else []) + _members(repo, root)
    checkers = _checkers(root)
    for path in candidates:
        data = _load(repo / path / "pyproject.toml") or {}
        checkers |= _checkers(data)
        if not _is_package(data):
            manifest_file = PurePosixPath(path, "pyproject.toml")
            # The root stays tmpl's python root either way: dev tools, checker config, and workspace tables.
            managed = "; tmpl still manages its python root tables" if path == "." else ""
            found.warnings.append(
                f"{manifest_file} is not a package (no [build-system], or tool.uv.package = false); "
                f"not adopted as a unit{managed}",
            )
            continue
        project = data.get("project")
        scripts = project.get("scripts") if is_map(project) else None
        found.units.append(Unit(path, "python", "cli" if scripts else "lib"))
    _add_script_units(repo, found)
    found.lang_options = _type_checkers(checkers)
    return found


def _is_package(data: dict[str, object]) -> bool:
    """Mirror uv: a project is packaged when tool.uv.package says so, else when it declares a build system."""
    tool = data.get("tool")
    uv = tool.get("uv") if is_map(tool) else None
    package = uv.get("package") if is_map(uv) else None
    return package if isinstance(package, bool) else "build-system" in data


def _add_script_units(repo: Path, found: Found) -> None:
    """Group PEP 723 scripts by directory; each directory outside a package unit becomes a python/scripts unit."""
    packages = [u.path for u in found.units]
    for directory in sorted({f.parent.relative_to(repo).as_posix() for f in _pep723_files(repo)}):
        if directory in packages:
            found.warnings.append(f"PEP 723 scripts in {directory}/ share a path with a package unit; not adopted")
        elif not any(_inside_package(directory, p) for p in packages):
            found.units.append(Unit(directory, "python", "scripts"))


def _inside_package(directory: str, package: str) -> bool:
    if package == ".":
        return directory.split("/", maxsplit=1)[0] in {"src", "tests"}
    return directory.startswith(f"{package}/")


def _pep723_files(repo: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in repo.walk():
        dirnames[:] = [d for d in dirnames if not _skipped(dirpath / d)]
        for name in filenames:
            path = dirpath / name
            if name.endswith(".py") and PEP723.search(path.read_text(errors="replace")):
                yield path


def _skipped(directory: Path) -> bool:
    """Hidden and dependency dirs, and nested repos (submodules, vendored checkouts)."""
    return directory.name.startswith(".") or directory.name in SKIP_DIRS or (directory / ".git").exists()


def _load(file: Path) -> dict[str, object] | None:
    return tomllib.loads(file.read_text()) if file.is_file() else None


def _members(repo: Path, root: dict[str, object]) -> list[str]:
    tool = root.get("tool")
    uv = tool.get("uv") if is_map(tool) else None
    workspace = uv.get("workspace") if is_map(uv) else None
    patterns = workspace.get("members") if is_map(workspace) else None
    if not is_seq(patterns):
        return []
    matches = (m for pattern in patterns for m in sorted(repo.glob(str(pattern))))
    return [m.relative_to(repo).as_posix() for m in matches if (m / "pyproject.toml").is_file()]


def _requirement_names(value: object) -> set[str]:
    names: set[str] = set()
    if is_seq(value):
        for item in value:
            if match := re.match(r"[A-Za-z0-9._-]+", str(item)):
                names.add(match.group(0).lower())
    return names


def _checkers(data: dict[str, object]) -> set[str]:
    names: set[str] = set()
    groups = data.get("dependency-groups")
    if is_map(groups):
        for deps in groups.values():
            names |= _requirement_names(deps)
    project = data.get("project")
    optional = project.get("optional-dependencies") if is_map(project) else None
    if is_map(optional):
        for deps in optional.values():
            names |= _requirement_names(deps)
    tool = data.get("tool")
    if is_map(tool):
        names |= set(tool)
    return names & {*FAST_CHECKERS, "mypy"}


def _type_checkers(present: set[str]) -> Options:
    """Map the checkers a project already uses onto stages; none found → defaults.

    The first fast checker found runs at pre-commit, and mypy at pre-push beside it, or at pre-commit alone.
    """
    fast = next((c for c in FAST_CHECKERS if c in present), None)
    tools = {fast: "pre-commit"} if fast else {}
    if "mypy" in present:
        tools["mypy"] = "pre-push" if fast else "pre-commit"
    return {"type_checkers": tools} if tools else {}
