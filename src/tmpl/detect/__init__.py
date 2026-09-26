"""Adopt detection (§9): existing tree → proposed manifest."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import attrs

from tmpl import catalog, git
from tmpl.detect import python
from tmpl.docs import is_map, is_seq
from tmpl.manifest import Manifest, Options, Unit

if TYPE_CHECKING:
    from pathlib import Path

# Config tmpl would duplicate instead of merge; reported so the user can fold it in by hand.
FOREIGN_CONFIG = (
    "mise.toml",
    ".mise.toml",
    ".config/mise.toml",
    ".mise/config.toml",
    "hk.pkl",
    ".github/workflows/check.yml",
    # Tool config outside pyproject.toml, where tmpl configures these tools.
    *(f"{d}{f}" for d in ("", ".config/") for f in ("ruff.toml", "mypy.ini", "pytest.ini", "pytest.toml", "ty.toml")),
    *(f"{d}{f}" for d in ("", ".config/") for f in ("pyrightconfig.json", "basedpyright.json")),
)


@attrs.define
class Detected:
    manifest: Manifest
    warnings: list[str] = attrs.field(factory=list[str])


class DetectError(Exception):
    pass


def detect(repo: Path) -> Detected:
    found = python.detect(repo)
    if not found.units:
        msg = "no supported units found (this version detects python projects only)"
        raise DetectError("; ".join([msg, *found.warnings]))
    warnings = list(found.warnings)
    for unit in found.units:
        if not catalog.supported(unit.lang, unit.kind):
            msg = f"detected {unit.lang}/{unit.kind} at {unit.path}, which this version cannot render yet"
            raise DetectError(msg)
    foreign = [p for p in FOREIGN_CONFIG if (repo / p).exists()]
    warnings += [f"existing {p}: tmpl manages its own copy; fold it in by hand" for p in foreign]
    copier = sorted((repo / ".config/copier").glob("*answers*.yml")) if (repo / ".config/copier").is_dir() else []
    warnings += [f"Copier answers {p.relative_to(repo)} can be deleted once adopted" for p in copier]

    lang_given = {"python": found.lang_options}
    root_given = _root_options(repo)
    manifest = Manifest(root={}, lang={}, unit=[])
    manifest.root = catalog.resolve(catalog.options_for(["root"], "root"), root_given, repo).stored
    for lang, given in lang_given.items():
        specs = catalog.options_for([f"lang/{lang}"], "lang")
        stored = catalog.resolve(specs, given, repo).stored
        if stored:
            manifest.lang[lang] = stored
    for unit in found.units:
        specs = catalog.options_for(catalog.unit_layer_ids(unit.lang, unit.kind), "unit")
        manifest.unit.append(
            Unit(unit.path, unit.lang, unit.kind, options=catalog.resolve(specs, {}, repo / unit.path).stored),
        )
    return Detected(manifest, warnings)


def _root_options(repo: Path) -> Options:
    options: Options = {}
    pyproject = _pyproject(repo)
    if description := catalog.lookup(pyproject, "project.description"):
        options["description"] = description
    authors = catalog.lookup(pyproject, "project.authors")
    if is_seq(authors) and authors and is_map(authors[0]) and (name := authors[0].get("name")):
        options["author"] = name
    license_ = catalog.lookup(pyproject, "project.license")
    if isinstance(license_, str):
        choices = catalog.options_for(["root"], "root")["license"].choices or []
        if license_ not in choices:
            msg = f"license {license_!r} is not in this version's catalog ({choices})"
            raise DetectError(msg)
        options["license"] = license_
    options.setdefault("author", git.config(repo, "user.name") or "")
    star = _editorconfig_star((repo / ".editorconfig").read_text()) if (repo / ".editorconfig").exists() else {}
    if star.get("indent_style") == "tab":
        options["indent"] = "tab"
    elif star.get("indent_size") in {"2", "4"}:
        options["indent"] = star["indent_size"]
    # .editorconfig is repo-wide; ruff's line length is the next best signal.
    ruff_length = catalog.lookup(pyproject, "tool.ruff.line-length")
    if star.get("max_line_length", "").isdigit():
        options["max_line_length"] = int(star["max_line_length"])
    elif isinstance(ruff_length, int):
        options["max_line_length"] = ruff_length
    return options


def _editorconfig_star(text: str) -> dict[str, str]:
    section, star = "", dict[str, str]()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif section == "*" and "=" in line and not line.startswith(("#", ";")):
            key, _, value = line.partition("=")
            star[key.strip()] = value.strip()
    return star


def _pyproject(path: Path) -> dict[str, object]:
    file = path / "pyproject.toml"
    return tomllib.loads(file.read_text()) if file.exists() else {}
