"""Reconcile: merge(base, ours, target) per path → actions, then apply them (§2.3, §6.2)."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Literal

import attrs

from tmpl import git
from tmpl.merge import Prefer, merge

if TYPE_CHECKING:
    from pathlib import Path

    from tmpl.render import RenderedFile, Tree

# "kept": a modified file the template dropped; "noted": unchanged, but adopt kept values that differ.
type Op = Literal["create", "update", "delete", "conflict", "kept", "noted"]


@attrs.define
class Action:
    path: str
    op: Op
    content: str | None = None
    force_add: bool = False
    notes: list[str] = attrs.field(factory=list[str])

    @property
    def failed(self) -> bool:
        """Needs the user: conflict markers, or a modified file the template no longer wants."""
        return self.op in {"conflict", "kept"}


def plan(repo: Path, base: Tree | None, target: Tree, prefer: Prefer | None = None) -> list[Action]:
    """`base is None` means adopt: nothing was rendered before, and scaffold source is never created."""
    adopt = base is None
    base = base or {}
    actions: list[Action] = []
    for path in sorted(set(base) | set(target)):
        b, t = base.get(path), target.get(path)
        file = repo / path
        ours = file.read_text() if file.is_file() else None
        if ours is None:
            action = _missing(path, b, t, adopt=adopt)
        elif t is None:
            action = _dropped(path, b, ours)
        elif t.policy == "seed" or (t.policy == "follow" and b is None):
            action = None
        else:
            action = _merged(path, b, ours, t, prefer)
        if action is not None:
            actions.append(action)
    return actions


def _missing(path: str, b: RenderedFile | None, t: RenderedFile | None, *, adopt: bool) -> Action | None:
    """The file is absent from the repo."""
    if t is None:
        return None
    if b is None:
        return None if adopt and t.scaffold else Action(path, "create", t.content, force_add=t.force_add)
    if t.policy != "seed" and b.content != t.content:
        return Action(path, "conflict", notes=["deleted locally but changed in the template"])
    return None


def _dropped(path: str, b: RenderedFile | None, ours: str) -> Action:
    """The template no longer renders the file."""
    if b is not None and ours == b.content:
        return Action(path, "delete")
    return Action(path, "kept", notes=["modified locally; no longer part of the template"])


def _merged(path: str, b: RenderedFile | None, ours: str, t: RenderedFile, prefer: Prefer | None) -> Action | None:
    merged = merge(path, b.content if b else None, ours, t.content, prefer=prefer)
    if merged.conflict:
        return Action(path, "conflict", merged.content, notes=merged.notes)
    if merged.content != ours:
        return Action(path, "update", merged.content, notes=merged.notes)
    if merged.notes:
        return Action(path, "noted", notes=merged.notes)
    return None


def apply(repo: Path, actions: list[Action]) -> None:
    for action in actions:
        file = repo / action.path
        if action.op == "delete":
            file.unlink()
            for parent in file.parents:
                if parent == repo or any(parent.iterdir()):
                    break
                parent.rmdir()
        elif action.content is not None:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(action.content)
    forced = [a.path for a in actions if a.op == "create" and a.force_add]
    if forced:
        git.add_force(repo, forced)


def diff(repo: Path, actions: list[Action]) -> str:
    out: list[str] = []
    for action in actions:
        file = repo / action.path
        old = file.read_text() if file.is_file() else ""
        new = "" if action.op == "delete" else (action.content if action.content is not None else old)
        out += difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            f"a/{action.path}",
            f"b/{action.path}",
        )
    return "".join(out)


def summary(actions: list[Action]) -> str:
    lines: list[str] = []
    for action in actions:
        lines.append(f"{action.op:>8}  {action.path}")
        lines += [f"{'':>8}    {note}" for note in action.notes]
    return "\n".join(lines) if lines else "nothing to do"
