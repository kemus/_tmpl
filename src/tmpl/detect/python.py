"""Python detection: pyproject.toml units, kinds, and type checkers."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tmpl.docs import is_map, is_seq
from tmpl.manifest import Options, Unit

if TYPE_CHECKING:
    from pathlib import Path

FAST_CHECKERS = ("basedpyright", "pyright", "ty")


@dataclass
class Found:
    units: list[Unit] = field(default_factory=list[Unit])
    lang_options: Options = field(default_factory=dict[str, object])
    warnings: list[str] = field(default_factory=list[str])


def detect(repo: Path) -> Found:
    found = Found()
    root = _load(repo / "pyproject.toml")
    if root is None:
        return found
    members = _members(repo, root)
    paths = (["."] if is_map(root.get("project")) else []) + members
    checkers: set[str] = set()
    for path in paths:
        data = _load(repo / path / "pyproject.toml") or {}
        project = data.get("project")
        scripts = project.get("scripts") if is_map(project) else None
        found.units.append(Unit(path, "python", "cli" if scripts else "lib"))
        checkers |= _checkers(data)
    found.lang_options = _type_checkers(checkers | _checkers(root))
    return found


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
    """Map the checkers a project already uses onto the fast/thorough slots; none found → defaults."""
    fast = next((c for c in FAST_CHECKERS if c in present), None)
    has_mypy = "mypy" in present
    if fast is None and not has_mypy:
        return {}
    if fast is None:
        return {"type_checker_fast": "mypy", "type_checker_thorough": "none"}
    return {"type_checker_fast": fast, "type_checker_thorough": "mypy" if has_mypy else "none"}
