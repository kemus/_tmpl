"""The few git operations tmpl needs, via subprocess."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from tmpl.manifest import MANIFEST_PATH
from tmpl.proc import executable

if TYPE_CHECKING:
    from pathlib import Path


class GitError(Exception):
    pass


def run(repo: Path, *args: str) -> str:
    proc = subprocess.run([executable("git"), "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


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


def add_force(repo: Path, paths: list[str]) -> None:
    run(repo, "add", "-f", "--", *paths)


def config(repo: Path, key: str) -> str | None:
    try:
        return run(repo, "config", "--get", key).strip() or None
    except GitError:
        return None
