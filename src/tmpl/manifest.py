"""The `.config/tmpl.toml` manifest: desired state of a tmpl-managed repo."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec
import tomlkit
from tomlkit.items import AoT

if TYPE_CHECKING:
    from tomlkit.items import Table

MANIFEST_PATH = Path(".config/tmpl.toml")

type Options = dict[str, object]


class Unit(msgspec.Struct, forbid_unknown_fields=True):
    path: str
    lang: str
    kind: str
    features: list[str] = msgspec.field(default_factory=list[str])
    options: Options = msgspec.field(default_factory=dict[str, object])


class Manifest(msgspec.Struct, forbid_unknown_fields=True):
    # Empty until the first reconcile: `adopt --plan` writes a versionless manifest,
    # and the next `sync` reconciles it against an empty base (§8.2).
    version: str = ""
    source: str | None = None
    root: Options = msgspec.field(default_factory=dict[str, object])
    lang: dict[str, Options] = msgspec.field(default_factory=dict[str, Options])
    unit: list[Unit] = msgspec.field(default_factory=list[Unit])

    @property
    def langs(self) -> list[str]:
        """Languages present, in first-unit order."""
        return list(dict.fromkeys(u.lang for u in self.unit))


def loads(text: str) -> Manifest:
    return msgspec.convert(tomllib.loads(text), Manifest)


def load(repo: Path) -> Manifest | None:
    path = repo / MANIFEST_PATH
    if not path.exists():
        return None
    return loads(path.read_text())


def dumps(manifest: Manifest) -> str:
    doc = tomlkit.document()
    doc.add("version", manifest.version)
    if manifest.source:
        doc.add("source", manifest.source)
    doc.add(tomlkit.nl())
    doc.add("root", _table(manifest.root))
    langs = tomlkit.table(is_super_table=True)
    for lang, options in manifest.lang.items():
        if options:
            langs[lang] = _table(options)
    if langs:
        doc.add("lang", langs)
    units: list[Table] = []
    for unit in manifest.unit:
        table = tomlkit.table()
        table["path"], table["lang"], table["kind"] = unit.path, unit.lang, unit.kind
        if unit.features:
            table["features"] = unit.features
        if unit.options:
            table["options"] = _table(unit.options)
        units.append(table)
    doc.add("unit", AoT(units))
    return tomlkit.dumps(doc)


def dump(repo: Path, manifest: Manifest) -> None:
    path = repo / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(manifest))


def _table(options: Options) -> Table:
    table = tomlkit.table()
    for key, value in options.items():
        table[key] = value
    return table
