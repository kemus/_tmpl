"""Per-format 3-way merge (§7). `base is None` means no base exists (adopt, §7.4)."""

from __future__ import annotations

import io
import json
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, MutableMapping, MutableSequence, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

import msgspec
import tomlkit

from tmpl import catalog
from tmpl.catalog import MergeRule
from tmpl.docs import is_map, is_seq, plain
from tmpl.proc import executable
from tmpl.sinks import yaml

if TYPE_CHECKING:
    from tmpl.catalog import SetKey

type Prefer = Literal["ours", "template"]

MISSING = object()
# `git merge-file` returns the conflict count, capped at 127; larger codes are errors.
MAX_CONFLICTS = 127


@dataclass
class Merged:
    content: str
    conflict: bool = False
    # Adopt: values where ours differs from the template and was kept (or replaced with --prefer template).
    notes: list[str] = field(default_factory=list[str])


@dataclass
class _State:
    adopt: bool
    prefer: Prefer | None
    rule: MergeRule
    conflicts: list[str] = field(default_factory=list[str])
    notes: list[str] = field(default_factory=list[str])


def merge(path: str, base: str | None, ours: str, theirs: str, *, prefer: Prefer | None = None) -> Merged:
    if ours == theirs:
        return Merged(ours)
    if base is not None and ours == base:
        return Merged(theirs)
    if base is not None and theirs == base:
        return Merged(ours)
    # --prefer only resolves adopt differences; a real 3-way conflict always gets markers.
    text_prefer = prefer if base is None else None
    name = PurePosixPath(path).name
    handler = _handler(name)
    if handler is None:
        return merge_text(base, ours, theirs, text_prefer)
    rule = catalog.merge_rules().get(name, MergeRule())
    try:
        return handler(base, ours, theirs, _State(adopt=base is None, prefer=prefer, rule=rule))
    except _StructuredConflictError:
        # Key-level conflict: fall back to a whole-file text merge so git-style markers land in context.
        return merge_text(base, ours, theirs, text_prefer)


class _StructuredConflictError(Exception):
    pass


type _Handler = Callable[[str | None, str, str, _State], Merged]


def _handler(name: str) -> _Handler | None:
    if name.endswith(".toml"):
        return _merge_toml
    if name.endswith((".yml", ".yaml")):
        return _merge_yaml
    if name.endswith(".json"):
        return _merge_json
    if name == ".gitignore":
        return _merge_lineset
    if name == ".editorconfig":
        return _merge_ini
    return None


def _finish(state: _State, content: str) -> Merged:
    if state.conflicts:
        raise _StructuredConflictError
    return Merged(content, notes=state.notes)


def _merge_toml(base: str | None, ours: str, theirs: str, state: _State) -> Merged:
    doc = tomlkit.parse(ours)
    merge_map(tomlkit.parse(base) if base is not None else None, doc, tomlkit.parse(theirs), state, "")
    # Tables appended by the merge carry their own leading blank line; keep exactly one final newline.
    return _finish(state, tomlkit.dumps(doc).rstrip("\n") + "\n")


def _merge_yaml(base: str | None, ours: str, theirs: str, state: _State) -> Merged:
    y = yaml()
    doc: object = y.load(ours)
    their_doc: object = y.load(theirs)
    base_doc: object = y.load(base) if base is not None else None
    if not (is_map(doc) and is_map(their_doc)):
        raise _StructuredConflictError
    merge_map(base_doc if is_map(base_doc) else None, doc, their_doc, state, "")
    buf = io.StringIO()
    y.dump(doc, buf)
    return _finish(state, buf.getvalue())


def _merge_json(base: str | None, ours: str, theirs: str, state: _State) -> Merged:
    doc: object = json.loads(ours)
    their_doc: object = json.loads(theirs)
    base_doc: object = json.loads(base) if base is not None else None
    if not (is_map(doc) and is_map(their_doc)):
        raise _StructuredConflictError
    merge_map(base_doc if is_map(base_doc) else None, doc, their_doc, state, "")
    return _finish(state, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def _eq(a: object, b: object) -> bool:
    if a is MISSING or b is MISSING:
        return a is b
    return plain(a) == plain(b)


def _set_key(path: str, rule: MergeRule) -> SetKey | None:
    for pattern, key in rule.set_like.items():
        if fnmatch(path, pattern):
            return key
    return None


def _requirement_name(item: object) -> str:
    text = str(plain(item))
    match = re.match(r"[A-Za-z0-9._-]+", text)
    return re.sub(r"[-_.]+", "-", match.group(0)).lower() if match else text


def merge_map(
    base: Mapping[str, object] | None,
    ours: MutableMapping[str, object],
    theirs: Mapping[str, object],
    state: _State,
    path: str,
) -> None:
    """Merge theirs into ours in place. `base is None` only in adopt mode (no base at all)."""
    base_map = base or {}
    for key in [*ours.keys(), *(k for k in theirs if k not in ours)]:
        key_path = f"{path}.{key}" if path else key
        b = base_map.get(key, MISSING)
        o = ours.get(key, MISSING)
        t = theirs.get(key, MISSING)
        if _eq(o, t):
            continue
        set_key = _set_key(key_path, state.rule)
        if state.adopt:
            _adopt_key(ours, theirs, key, key_path, state)
        elif _eq(o, b):
            _take(ours, key, t)
        elif _eq(t, b):
            continue
        elif is_map(o) and is_map(t):
            merge_map(b if is_map(b) else {}, o, t, state, key_path)
        elif set_key and is_seq(o) and is_seq(t):
            _merge_set(b if is_seq(b) else [], o, t, set_key)
        else:
            state.conflicts.append(key_path)


def _adopt_key(
    ours: MutableMapping[str, object],
    theirs: Mapping[str, object],
    key: str,
    key_path: str,
    state: _State,
) -> None:
    o, t = ours.get(key, MISSING), theirs.get(key, MISSING)
    set_key = _set_key(key_path, state.rule)
    if o is MISSING:
        _take(ours, key, t)
    elif t is MISSING:
        return
    elif is_map(o) and is_map(t):
        merge_map(None, o, t, state, key_path)
    elif set_key and is_seq(o) and is_seq(t):
        _merge_set([], o, t, set_key)
    elif state.prefer == "template":
        _take(ours, key, t)
        state.notes.append(f"{key_path}: replaced with template value {plain(t)!r}")
    else:
        state.notes.append(f"{key_path}: kept {plain(o)!r} (template: {plain(t)!r})")


def _take(ours: MutableMapping[str, object], key: str, t: object) -> None:
    if t is MISSING:
        del ours[key]
    else:
        ours[key] = t


def _merge_set(
    base: Sequence[object],
    ours: MutableSequence[object],
    theirs: Sequence[object],
    set_key: SetKey,
) -> None:
    """Set merge by identity key: keep ours' element text, add upstream additions, drop upstream removals."""

    def ident(item: object) -> object:
        return _requirement_name(item) if set_key == "requirement" else plain(item)

    in_base = {ident(x) for x in base}
    in_theirs = {ident(x) for x in theirs}
    for index in reversed(range(len(ours))):
        item = ident(ours[index])
        if item in in_base and item not in in_theirs:
            del ours[index]
    in_ours = {ident(x) for x in ours}
    for item in theirs:
        if ident(item) not in in_base and ident(item) not in in_ours:
            ours.append(plain(item))


def _merge_lineset(base: str | None, ours: str, theirs: str, state: _State) -> Merged:
    """Lines as a set, kept in ours' order; new upstream lines go after their upstream predecessor."""
    base_lines = set((base or "").splitlines())
    result = ours.splitlines()
    theirs_lines = theirs.splitlines()
    their_set = set(theirs_lines)
    result = [line for line in result if not line.strip() or line not in base_lines or line in their_set]
    for block in "\n".join(theirs_lines).split("\n\n"):
        anchor: int | None = None
        pending: list[str] = []
        for line in block.splitlines():
            if line in result:
                anchor = result.index(line)
                if pending:
                    result[anchor:anchor] = pending
                    anchor += len(pending)
                    pending = []
            elif line not in base_lines:
                if anchor is None:
                    pending.append(line)
                else:
                    anchor += 1
                    result.insert(anchor, line)
        if pending:
            while result and not result[-1].strip():
                result.pop()
            result += ["", *pending] if result else pending
    return _finish(state, "\n".join(result) + "\n")


def _parse_ini(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {"": {}}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
        elif "=" in line:
            key, _, value = line.partition("=")
            sections[current][key.strip()] = value.strip()
    return sections


def _merge_ini(base: str | None, ours: str, theirs: str, state: _State) -> Merged:
    """Merge on parsed sections, then apply the resulting edits to ours' lines to keep comments and layout."""
    ours_parsed = _parse_ini(ours)
    result: dict[str, object] = {k: dict(v) for k, v in ours_parsed.items()}
    base_parsed = _parse_ini(base) if base is not None else None
    merge_map(base_parsed, result, _parse_ini(theirs), state, "")
    if state.conflicts:
        raise _StructuredConflictError
    lines = ours.splitlines()
    for section, values in msgspec.convert(result, dict[str, dict[str, str]]).items():
        _apply_ini_section(lines, section, values, ours_parsed.get(section))
    for section in ours_parsed:
        if section and section not in result:
            _delete_ini_section(lines, section)
    return Merged("\n".join(lines) + "\n", notes=state.notes)


def _ini_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    """[start, end) of a section's body lines; the preamble is section ''."""
    start = 0 if section == "" else None
    for index, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            if start is not None:
                return start, index
            if line[1:-1] == section:
                start = index + 1
    return (start, len(lines)) if start is not None else None


def _apply_ini_section(lines: list[str], section: str, want: dict[str, str], had: dict[str, str] | None) -> None:
    if had is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"[{section}]", *(f"{k} = {v}" for k, v in want.items())]
        return
    start, end = _ini_bounds(lines, section) or (len(lines), len(lines))
    for index in reversed(range(start, end)):
        key = lines[index].partition("=")[0].strip()
        if "=" in lines[index] and not lines[index].lstrip().startswith(("#", ";")):
            if key not in want:
                del lines[index]
            elif want[key] != had.get(key):
                lines[index] = f"{key} = {want[key]}"
    start, end = _ini_bounds(lines, section) or (start, end)
    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = [f"{k} = {v}" for k, v in want.items() if k not in had]


def _delete_ini_section(lines: list[str], section: str) -> None:
    bounds = _ini_bounds(lines, section)
    if bounds is not None:
        del lines[bounds[0] - 1 : bounds[1]]


def merge_text(base: str | None, ours: str, theirs: str, prefer: Prefer | None = None) -> Merged:
    """`git merge-file`; with no base, differences become one conflict unless a side is preferred."""
    with tempfile.TemporaryDirectory() as tmp:
        files: list[str] = []
        for name, content in (("ours", ours), ("base", base or ""), ("template", theirs)):
            file = Path(tmp) / name
            file.write_text(content)
            files.append(str(file))
        args = [executable("git"), "merge-file", "-p", "-L", "ours", "-L", "base", "-L", "template"]
        if prefer is not None:
            args.append("--ours" if prefer == "ours" else "--theirs")
        proc = subprocess.run([*args, *files], capture_output=True, text=True, check=False)
    if not 0 <= proc.returncode <= MAX_CONFLICTS:
        raise RuntimeError(proc.stderr)
    return Merged(proc.stdout, conflict=proc.returncode > 0)
