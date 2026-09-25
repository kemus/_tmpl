"""Type guards for parsed TOML/YAML/JSON documents (tomlkit, ruamel and plain containers alike)."""

from __future__ import annotations

from collections.abc import MutableMapping, MutableSequence
from typing import TypeIs


def is_map(value: object) -> TypeIs[MutableMapping[str, object]]:
    """Document tables: keys are always strings in TOML, JSON, and the YAML we manage."""
    return isinstance(value, MutableMapping)


def is_seq(value: object) -> TypeIs[MutableSequence[object]]:
    return isinstance(value, MutableSequence) and not isinstance(value, str)


def plain(value: object) -> object:
    """Strip formatting wrappers so values compare by content."""
    if is_map(value):
        return {k: plain(v) for k, v in value.items()}
    if is_seq(value):
        return [plain(v) for v in value]
    unwrap = getattr(value, "unwrap", None)
    return unwrap() if callable(unwrap) else value
