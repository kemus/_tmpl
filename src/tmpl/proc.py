"""Running external tools: resolved to absolute paths, fixed argv, never through a shell."""

from __future__ import annotations

import shutil
import subprocess
import sys
from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class MissingToolError(Exception):
    pass


class ToolError(Exception):
    pass


@cache
def executable(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        msg = f"{name} not found on PATH"
        raise MissingToolError(msg)
    return found


def run(*args: str, cwd: Path | None = None, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run ARGS[0] by name; uncaptured output goes to the terminal. The caller checks the exit code."""
    cmd = [executable(args[0]), *args[1:]]
    if not capture:
        # Ours first: a piped stdout is block-buffered, and the tool writes to the same file.
        sys.stdout.flush()
        sys.stderr.flush()
    return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True, check=False)  # noqa: S603 — fixed argv, resolved executable, no shell


def check(*args: str, cwd: Path | None = None) -> None:
    """Run ARGS[0] with output on the terminal; raise ToolError if it fails."""
    if run(*args, cwd=cwd, capture=False).returncode != 0:
        msg = f"`{' '.join(args)}` failed"
        raise ToolError(msg)
