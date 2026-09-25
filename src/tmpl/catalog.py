"""Template layers shipped in `tmpl/templates/`, and option resolution against them."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from functools import cache
from pathlib import Path
from typing import Literal

import msgspec

TEMPLATES = Path(__file__).parent / "templates"

type Scope = Literal["root", "lang", "unit"]
type Policy = Literal["merge", "seed"]
type SetKey = Literal["exact", "requirement"]


class OptionSpec(msgspec.Struct, forbid_unknown_fields=True):
    scope: Scope
    default: object = None
    choices: list[object] | None = None
    type: Literal["str", "int"] = "str"
    # Live source: "<file relative to the scope's path>:<dotted key>"; never stored (§3.2).
    source: str | None = None
    source_pattern: str | None = None

    def coerce(self, name: str, value: object) -> object:
        if self.type == "int":
            value = int(str(value))
        if self.choices is not None and value not in self.choices:
            msg = f"option {name}={value!r}: expected one of {self.choices}"
            raise ValueError(msg)
        return value


class FileRule(msgspec.Struct, forbid_unknown_fields=True):
    policy: Policy = "merge"
    # Scaffold source: adopt never creates it in an existing repo.
    scaffold: bool = False
    # Staged with `git add -f` when created (the path is gitignored).
    force_add: bool = False


class Fragment(msgspec.Struct, forbid_unknown_fields=True):
    sink: str
    data: dict[str, object]
    order: int = 50
    when: str | None = None


class Patch(msgspec.Struct, forbid_unknown_fields=True):
    dest: str
    data: dict[str, object]


class MergeRule(msgspec.Struct, forbid_unknown_fields=True):
    set_like: dict[str, SetKey] = msgspec.field(default_factory=dict[str, SetKey])


class LayerSpec(msgspec.Struct, forbid_unknown_fields=True):
    options: dict[str, OptionSpec] = msgspec.field(default_factory=dict[str, OptionSpec])
    vars: dict[str, object] = msgspec.field(default_factory=dict[str, object])
    files: dict[str, FileRule] = msgspec.field(default_factory=dict[str, FileRule])
    fragment: list[Fragment] = msgspec.field(default_factory=list[Fragment])
    patch: list[Patch] = msgspec.field(default_factory=list[Patch])
    merge: dict[str, MergeRule] = msgspec.field(default_factory=dict[str, MergeRule])
    # Commands run by setup (§8.9) through `mise exec --`, once per layer in the repo.
    setup: list[list[str]] = msgspec.field(default_factory=list[list[str]])


@dataclass(frozen=True)
class Layer:
    id: str
    dir: Path
    spec: LayerSpec

    @property
    def files_dir(self) -> Path:
        return self.dir / "files"

    def rule_for(self, rel: str) -> FileRule:
        for pattern, rule in self.spec.files.items():
            if fnmatch(rel, pattern):
                return rule
        return FileRule()


@cache
def layer(layer_id: str) -> Layer | None:
    directory = TEMPLATES / layer_id
    spec_path = directory / "template.toml"
    if not spec_path.exists():
        return None
    spec = msgspec.convert(tomllib.loads(spec_path.read_text()), LayerSpec)
    return Layer(layer_id, directory, spec)


def unit_layer_ids(lang: str, kind: str) -> list[str]:
    return [f"lang/{lang}/unit", f"kind/{kind}", f"lang/{lang}/kind/{kind}"]


def supported(lang: str, kind: str) -> bool:
    return layer(f"lang/{lang}/kind/{kind}") is not None


def merge_rules() -> dict[str, MergeRule]:
    """Merge rules by file name, from every layer."""
    rules: dict[str, MergeRule] = {}
    for spec_path in TEMPLATES.rglob("template.toml"):
        found = layer(spec_path.parent.relative_to(TEMPLATES).as_posix())
        if found:
            rules.update(found.spec.merge)
    return rules


def options_for(layer_ids: list[str], scope: Scope) -> dict[str, OptionSpec]:
    specs: dict[str, OptionSpec] = {}
    for layer_id in layer_ids:
        found = layer(layer_id)
        if found:
            specs.update({k: v for k, v in found.spec.options.items() if v.scope == scope})
    return specs


@dataclass
class Resolved:
    """Option values for rendering, split into what the manifest stores and what was read live."""

    values: dict[str, object] = field(default_factory=dict[str, object])
    stored: dict[str, object] = field(default_factory=dict[str, object])


def resolve(specs: dict[str, OptionSpec], given: dict[str, object], live_root: Path | None) -> Resolved:
    unknown = set(given) - set(specs)
    if unknown:
        msg = f"unknown options: {sorted(unknown)}"
        raise ValueError(msg)
    out = Resolved()
    for name, spec in specs.items():
        if spec.source:
            live = read_live(spec, live_root) if live_root else None
            value = live if live is not None else given.get(name, spec.default)
            if value is not None:
                out.values[name] = spec.coerce(name, value)
            continue
        value = given.get(name, spec.default)
        if value is None:
            continue
        out.values[name] = out.stored[name] = spec.coerce(name, value)
    return out


def read_live(spec: OptionSpec, root: Path) -> object | None:
    if spec.source is None:
        return None
    file, _, dotted = spec.source.partition(":")
    path = root / file
    if not path.exists():
        return None
    value = lookup(tomllib.loads(path.read_text()), dotted)
    if value is not None and spec.source_pattern:
        match = re.search(spec.source_pattern, str(value))
        return match.group(1) if match else None
    return value


def lookup(data: object, dotted: str) -> object | None:
    for key in dotted.split("."):
        if not isinstance(data, dict):
            return None
        data = msgspec.convert(data, dict[str, object]).get(key)
    return data
