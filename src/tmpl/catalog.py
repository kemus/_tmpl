"""Template layers shipped in `tmpl/templates/`, and option resolution against them."""

from __future__ import annotations

import re
import tomllib
from fnmatch import fnmatch
from functools import cache
from pathlib import Path
from typing import Literal

import attrs

from tmpl.convert import structure
from tmpl.docs import is_map

TEMPLATES = Path(__file__).parent / "templates"

type Scope = Literal["root", "lang", "unit"]
type Attach = Literal["root", "unit"]
type Policy = Literal["merge", "seed"]
type SetKey = Literal["exact", "requirement"]


@attrs.frozen
class OptionSpec:
    scope: Scope
    default: object = None
    choices: list[object] | None = None
    type: Literal["str", "int", "bool"] = "str"
    # Live source: "<file relative to the scope's path>:<dotted key>"; never stored (§3.2).
    source: str | None = None
    source_pattern: str | None = None

    def coerce(self, name: str, value: object) -> object:
        if self.type == "int":
            value = int(str(value))
        elif self.type == "bool" and not isinstance(value, bool):
            # `--opt` values arrive as text; the manifest stores TOML booleans.
            text = str(value).lower()
            if text not in {"true", "false"}:
                msg = f"option {name}={value!r}: expected true or false"
                raise ValueError(msg)
            value = text == "true"
        if self.choices is not None and value not in self.choices:
            msg = f"option {name}={value!r}: expected one of {self.choices}"
            raise ValueError(msg)
        return value


@attrs.frozen
class FileRule:
    policy: Policy = "merge"
    # Scaffold source: adopt never creates it in an existing repo.
    scaffold: bool = False
    # Staged with `git add -f` when created (the path is gitignored).
    force_add: bool = False


@attrs.frozen
class Fragment:
    sink: str
    data: dict[str, object]
    order: int = 50
    when: str | None = None


@attrs.frozen
class Patch:
    dest: str
    data: dict[str, object]


@attrs.frozen
class MergeRule:
    set_like: dict[str, SetKey] = attrs.field(factory=dict[str, SetKey])


@attrs.frozen
class LayerSpec:
    options: dict[str, OptionSpec] = attrs.field(factory=dict[str, OptionSpec])
    vars: dict[str, object] = attrs.field(factory=dict[str, object])
    files: dict[str, FileRule] = attrs.field(factory=dict[str, FileRule])
    fragment: list[Fragment] = attrs.field(factory=list[Fragment])
    patch: list[Patch] = attrs.field(factory=list[Patch])
    merge: dict[str, MergeRule] = attrs.field(factory=dict[str, MergeRule])
    # Commands run by setup (§8.9) through `mise exec --`, once per layer in the repo.
    setup: list[list[str]] = attrs.field(factory=list[list[str]])
    # On a lang-by-kind layer: false for kinds that are not packages (scripts). They skip the
    # language's unit layer, and with it the manifest file and workspace membership.
    package: bool = True
    # On a `feature/<f>` layer, which declares the feature: where it attaches, and for a unit feature the kinds it
    # suits (all when unset). A unit feature needs `lang/<lang>/feature/<f>` for the unit's language (§4.3).
    attaches: Attach | None = None
    kinds: list[str] | None = None


@attrs.frozen
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
    spec = structure(tomllib.loads(spec_path.read_text()), LayerSpec)
    return Layer(layer_id, directory, spec)


def unit_layer_ids(lang: str, kind: str) -> list[str]:
    ids = [f"lang/{lang}/unit", f"kind/{kind}", f"lang/{lang}/kind/{kind}"]
    found = layer(ids[-1])
    return ids if found is None or found.spec.package else ids[1:]


def supported(lang: str, kind: str) -> bool:
    return layer(f"lang/{lang}/kind/{kind}") is not None


def features() -> list[str]:
    directory = TEMPLATES / "feature"
    names = sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []
    return [name for name in names if (found := layer(f"feature/{name}")) and found.spec.attaches]


def feature_layer_ids(feature: str, lang: str) -> list[str]:
    return [f"feature/{feature}", f"lang/{lang}/feature/{feature}"]


def feature_problem(feature: str, lang: str | None = None, kind: str | None = None) -> str | None:
    """Why `feature` can't attach to the root (no `lang`) or to a `lang`/`kind` unit; None if it can."""
    declared = layer(f"feature/{feature}")
    if declared is None or declared.spec.attaches is None:
        return f"unknown feature {feature!r}; features: {', '.join(features()) or 'none'}"
    attaches, kinds = declared.spec.attaches, declared.spec.kinds
    if attaches != ("root" if lang is None else "unit"):
        return f"feature {feature!r} attaches to {'the root' if attaches == 'root' else 'a unit (pass its PATH)'}"
    if lang is None:
        return None
    if kinds is not None and kind not in kinds:
        return f"feature {feature!r} suits {', '.join(kinds)} units, not {kind}"
    if layer(f"lang/{lang}/feature/{feature}") is None:
        return f"feature {feature!r} has no {lang} support in this version"
    return None


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


@attrs.define
class Resolved:
    """Option values for rendering, split into what the manifest stores and what was read live."""

    values: dict[str, object] = attrs.field(factory=dict[str, object])
    stored: dict[str, object] = attrs.field(factory=dict[str, object])


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
        if not is_map(data):
            return None
        data = data.get(key)
    return data
