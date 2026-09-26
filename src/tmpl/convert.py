"""Structuring parsed documents into typed values: one strict cattrs converter for the whole package."""

from __future__ import annotations

import cattrs

converter = cattrs.Converter(forbid_extra_keys=True)
# `object` fields hold arbitrary document values (option defaults, fragment data): pass them through.
converter.register_structure_hook_func(lambda t: t is object, lambda value, _: value)


def _strict[T](kind: type[T]) -> None:
    """Reject values of another type instead of coercing them (cattrs turns 3 into "3" by default)."""

    def hook(value: object, _: type[T]) -> T:
        # bool subclasses int; a TOML `true` is never an int.
        if isinstance(value, kind) and not (kind is int and isinstance(value, bool)):
            return value
        msg = f"expected {kind.__name__}, got {type(value).__name__} {value!r}"
        raise TypeError(msg)

    converter.register_structure_hook(kind, hook)


for _kind in (str, int, bool):
    _strict(_kind)


def structure[T](value: object, kind: type[T]) -> T:
    return converter.structure(value, kind)


def error_text(exc: cattrs.BaseValidationError) -> str:
    """One line per invalid value, each with its path."""
    return "; ".join(cattrs.transform_error(exc, path="$"))
