"""The few git operations tmpl needs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tmpl import proc
from tmpl.manifest import MANIFEST_PATH

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class GitError(Exception):
    pass


def run(repo: Path, *args: str) -> str:
    result = proc.run("git", "-C", str(repo), *args)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def is_repo(repo: Path) -> bool:
    try:
        run(repo, "rev-parse", "--git-dir")
    except GitError:
        return False
    return True


def dirty_paths(repo: Path) -> list[str]:
    """Uncommitted changes, ignoring the manifest (`adopt --plan` leaves it for editing)."""
    lines = run(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    paths = [line[3:] for line in lines]
    return [p for p in paths if p != MANIFEST_PATH.as_posix()]


def file_history(repo: Path, path: str) -> Iterator[str]:
    """The committed contents of `path`, newest first."""
    for commit in run(repo, "log", "--format=%H", "--", path).split():
        yield run(repo, "show", f"{commit}:{path}")


def add_force(repo: Path, paths: list[str]) -> None:
    run(repo, "add", "-f", "--", *paths)


def config(repo: Path, key: str) -> str | None:
    try:
        return run(repo, "config", "--get", key).strip() or None
    except GitError:
        return None
