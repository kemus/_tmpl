"""The `.config/tmpl.toml` manifest: desired state of a tmpl-managed repo."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import attrs
import tomlkit
from tomlkit.items import AoT

from tmpl.convert import structure
from tmpl.docs import is_seq

if TYPE_CHECKING:
    from tomlkit.items import Table

MANIFEST_PATH = Path(".config/tmpl.toml")
DEFAULT_SOURCE = "git+https://github.com/kemus/_tmpl"

type Options = dict[str, object]


@attrs.define
class Unit:
    path: str
    lang: str
    kind: str
    features: list[str] = attrs.field(factory=list[str])
    options: Options = attrs.field(factory=dict[str, object])


@attrs.define
class Manifest:
    # Empty until the first reconcile: `adopt --plan` writes a versionless manifest,
    # and the next `sync` reconciles it against an empty base (§8.2).
    version: str = ""
    source: str | None = None
    # Hash of the manifest as the last reconcile wrote it (`digest`). A mismatch means a hand edit since, and the
    # applied state is found in the manifest's git history.
    applied: str | None = None
    root: Options = attrs.field(factory=dict[str, object])
    lang: dict[str, Options] = attrs.field(factory=dict[str, Options])
    unit: list[Unit] = attrs.field(factory=list[Unit])

    @property
    def spec(self) -> str:
        """The `uvx --from` requirement for the tmpl release that reconciled this manifest."""
        return f"{self.source or DEFAULT_SOURCE}@v{self.version}"

    @property
    def features(self) -> list[str]:
        """Features attached to the root, kept with the root options (§3.3)."""
        value = self.root.get("features", [])
        if not is_seq(value) or not all(isinstance(f, str) for f in value):
            msg = f"root.features: expected a list of feature names, got {value!r}"
            raise ValueError(msg)
        return [str(f) for f in value]

    @features.setter
    def features(self, value: list[str]) -> None:
        if value:
            self.root["features"] = value
        else:
            self.root.pop("features", None)

    @property
    def langs(self) -> list[str]:
        """Languages present, in first-unit order."""
        return list(dict.fromkeys(u.lang for u in self.unit))


def loads(text: str) -> Manifest:
    return structure(tomllib.loads(text), Manifest)


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
    if manifest.applied:
        doc.add("applied", manifest.applied)
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


def digest(manifest: Manifest) -> str:
    """Hash of the manifest's normalized content, without its own `applied` stamp."""
    text = dumps(attrs.evolve(manifest, applied=None))
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def stamp(manifest: Manifest) -> None:
    """Record the manifest as applied: a later mismatch with `digest` reveals a hand edit."""
    manifest.applied = digest(manifest)


def dump(repo: Path, manifest: Manifest) -> None:
    path = repo / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(manifest))


def _table(options: Options) -> Table:
    table = tomlkit.table()
    for key, value in options.items():
        table[key] = value
    return table
