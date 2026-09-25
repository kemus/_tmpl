"""Post-render setup (§8.9): install the pinned tools, sync dependencies, install git hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tmpl import catalog, proc

if TYPE_CHECKING:
    from pathlib import Path


def run(repo: Path, langs: list[str]) -> None:
    for args in (("mise", "trust", "--quiet"), ("mise", "install"), ("mise", "lock")):
        proc.check(*args, cwd=repo)
    for lang in langs:
        found = catalog.layer(f"lang/{lang}")
        for command in found.spec.setup if found else []:
            proc.check("mise", "exec", "--", *command, cwd=repo)
    proc.check("mise", "exec", "--", "hk", "install", cwd=repo)
