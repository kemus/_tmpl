"""`render`: manifest in, file tree out. Side-effect free (§10)."""

from __future__ import annotations

import posixpath
import re
import tomllib
from typing import TYPE_CHECKING

import attrs
import jinja2
import tomlkit

from tmpl import catalog, sinks
from tmpl.convert import structure
from tmpl.docs import is_map, is_seq

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping
    from pathlib import Path

    from tmpl.catalog import Layer, Policy
    from tmpl.manifest import Manifest, Unit


class RenderError(Exception):
    pass


@attrs.frozen
class RenderedFile:
    content: str
    policy: Policy = "merge"
    scaffold: bool = False
    force_add: bool = False


type Tree = dict[str, RenderedFile]


@attrs.frozen
class Instance:
    """A layer applied at a placement with its rendering context."""

    layer: Layer
    placement: str
    context: dict[str, object]


def join(placement: str, rel: str) -> str:
    return posixpath.normpath(posixpath.join(placement, rel))


def default_name(unit: Unit, repo_name: str) -> str:
    return repo_name if unit.path == "." else posixpath.basename(unit.path)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def instances(manifest: Manifest, repo_name: str, live_root: Path | None) -> list[Instance]:
    root_given = {k: v for k, v in manifest.root.items() if k != "features"}
    root_values = catalog.resolve(catalog.options_for(["root"], "root"), root_given, live_root).values
    root_ctx = {"repo_name": repo_name, **root_values}
    out: list[Instance] = []

    def add(layer_id: str, placement: str, ctx: dict[str, object]) -> None:
        found = catalog.layer(layer_id)
        if found:
            out.append(Instance(found, placement, {**ctx, **found.spec.vars}))

    add("root", ".", root_ctx)
    lang_ctx: dict[str, dict[str, object]] = {}
    for lang in manifest.langs:
        if catalog.layer(f"lang/{lang}") is None:
            msg = f"unknown language: {lang}"
            raise RenderError(msg)
        # Live lang options are read at the first unit of that language.
        first = next(u for u in manifest.unit if u.lang == lang)
        live = live_root / first.path if live_root else None
        specs = catalog.options_for([f"lang/{lang}"], "lang")
        lang_ctx[lang] = {**root_ctx, **catalog.resolve(specs, manifest.lang.get(lang, {}), live).values}
        add(f"lang/{lang}", ".", lang_ctx[lang])
    for unit in manifest.unit:
        if not catalog.supported(unit.lang, unit.kind):
            msg = f"unsupported unit {unit.lang}/{unit.kind} at {unit.path}"
            raise RenderError(msg)
        layer_ids = catalog.unit_layer_ids(unit.lang, unit.kind)
        live = live_root / unit.path if live_root else None
        values = catalog.resolve(catalog.options_for(layer_ids, "unit"), unit.options, live).values
        name = str(values.get("name") or default_name(unit, repo_name))
        info = {"path": unit.path, "lang": unit.lang, "kind": unit.kind, "name": name, "slug": slug(name)}
        ctx = {**lang_ctx[unit.lang], **values, "unit": info}
        for layer_id in layer_ids:
            add(layer_id, unit.path, ctx)
    return out


def _env(layer: Layer) -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(layer.dir),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=jinja2.select_autoescape(enabled_extensions=("html", "xml"), default_for_string=False),
    )


def _render_data(env: jinja2.Environment, value: object, ctx: dict[str, object]) -> object:
    if isinstance(value, str):
        return env.from_string(value).render(ctx)
    if is_map(value):
        out: dict[str, object] = {}
        for key, item in value.items():
            rendered = _render_data(env, item, ctx)
            if rendered != "":
                out[env.from_string(key).render(ctx)] = rendered
        return out
    if is_seq(value):
        return [_render_data(env, item, ctx) for item in value]
    return value


def _deep_patch(target: MutableMapping[str, object], patch: Mapping[str, object]) -> None:
    """Merge patch into target: tables recurse, arrays gain missing items, scalars are replaced."""
    for key, value in patch.items():
        current = target.get(key)
        if is_map(value) and is_map(current):
            _deep_patch(current, value)
        elif is_seq(value) and is_seq(current):
            current.extend(item for item in list(value) if item not in current)
        else:
            target[key] = value


def render(manifest: Manifest, repo_name: str, live_root: Path | None = None) -> Tree:
    tree: Tree = {}
    frags: dict[str, list[tuple[int, int, sinks.Frag]]] = {}
    patches: list[tuple[str, dict[str, object]]] = []
    root_ctx: dict[str, object] = {}
    for index, inst in enumerate(instances(manifest, repo_name, live_root)):
        env = _env(inst.layer)
        if inst.layer.id == "root":
            root_ctx = inst.context
        tree.update(_render_files(inst, env))
        for frag in inst.layer.spec.fragment:
            if frag.when is None or env.from_string(frag.when).render(inst.context) == "True":
                data = structure(_render_data(env, frag.data, inst.context), dict[str, object])
                frags.setdefault(frag.sink, []).append((frag.order, index, sinks.Frag(data, inst.placement)))
        for patch in inst.layer.spec.patch:
            data = structure(_render_data(env, patch.data, inst.context), dict[str, object])
            patches.append((join(inst.placement, patch.dest), data))
    ordered = {sink: [f for _, _, f in sorted(items, key=lambda t: t[:2])] for sink, items in frags.items()}
    for path, file in _run_sinks(ordered, root_ctx).items():
        # A sink landing on a rendered TOML file (the workspace table on a root package) patches it.
        if path in tree and path.endswith(".toml"):
            _apply_patch(tree, path, tomllib.loads(file.content))
        else:
            tree[path] = file
    for path, data in patches:
        _apply_patch(tree, path, data)
    return {path: _tidy(path, f) for path, f in sorted(tree.items())}


def _render_files(inst: Instance, env: jinja2.Environment) -> Tree:
    """The layer's `files/` dir: paths and `.jinja` contents are templates."""
    tree: Tree = {}
    if not inst.layer.files_dir.is_dir():
        return tree
    for src in sorted(p for p in inst.layer.files_dir.rglob("*") if p.is_file()):
        rel_src = src.relative_to(inst.layer.files_dir).as_posix()
        rel = env.from_string(rel_src.removesuffix(".jinja")).render(inst.context)
        if src.suffix == ".jinja":
            content = env.get_template(src.relative_to(inst.layer.dir).as_posix()).render(inst.context)
        else:
            content = src.read_text()
        rule = inst.layer.rule_for(rel)
        tree[join(inst.placement, rel)] = RenderedFile(content, rule.policy, rule.scaffold, rule.force_add)
    return tree


def _run_sinks(ordered: dict[str, list[sinks.Frag]], root_ctx: dict[str, object]) -> Tree:
    unknown = set(ordered) - set(sinks.SINKS) - set(sinks.MISE_SINKS)
    if unknown:
        msg = f"fragments for unknown sinks: {sorted(unknown)}"
        raise RenderError(msg)
    outputs = sinks.mise(ordered)
    for name, sink in sinks.SINKS.items():
        outputs += sink(ordered.get(name, []), root_ctx)
    return {out.path: RenderedFile(out.content, out.policy) for out in outputs}


def _apply_patch(tree: Tree, path: str, data: dict[str, object]) -> None:
    if path not in tree or not path.endswith(".toml"):
        msg = f"patch target {path} is not a rendered TOML file"
        raise RenderError(msg)
    doc = tomlkit.parse(tree[path].content)
    _deep_patch(doc, data)
    old = tree[path]
    tree[path] = RenderedFile(tomlkit.dumps(doc), old.policy, old.scaffold, old.force_add)


def _tidy(path: str, file: RenderedFile) -> RenderedFile:
    """Give every TOML table header a blank line before it (Jinja blocks and patches drop them)."""
    if not path.endswith(".toml"):
        return file
    content = re.sub(r"(?<=[^\n])\n(?=\[)", "\n\n", file.content)
    return RenderedFile(content, file.policy, file.scaffold, file.force_add)
