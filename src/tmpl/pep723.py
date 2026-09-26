"""PEP 723 inline script metadata (`# /// script` blocks)."""

from __future__ import annotations

import re
import tomllib

from tmpl.docs import is_map, is_seq

# The reference regex from the specification.
BLOCK = re.compile(r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$")


def metadata(text: str) -> dict[str, object] | None:
    """The script block's TOML, or None without one. Raises ValueError on a duplicate block or bad TOML."""
    blocks = [m for m in BLOCK.finditer(text) if m.group("type") == "script"]
    if len(blocks) > 1:
        msg = "multiple `script` blocks"
        raise ValueError(msg)
    if not blocks:
        return None
    lines = blocks[0].group("content").splitlines(keepends=True)
    return tomllib.loads("".join(line[2:] if line.startswith("# ") else line[1:] for line in lines))


def dependencies(text: str) -> list[str]:
    data = metadata(text)
    deps: object = data.get("dependencies", []) if is_map(data) else []
    if not is_seq(deps) or not all(isinstance(d, str) for d in deps):
        msg = "`dependencies` must be a list of strings"
        raise ValueError(msg)
    return [str(d) for d in deps]
