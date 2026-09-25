"""Resolving external tools to absolute paths before running them."""

import shutil
from functools import cache


class MissingToolError(Exception):
    pass


@cache
def executable(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        msg = f"{name} not found on PATH"
        raise MissingToolError(msg)
    return found
