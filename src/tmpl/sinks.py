"""Shared-file sinks: each merges its fragments deterministically into one file (§5)."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping
from typing import IO, TYPE_CHECKING, Protocol

import attrs
import tomlkit
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from tmpl.convert import structure
from tmpl.docs import is_map

if TYPE_CHECKING:
    from tomlkit.items import InlineTable

    from tmpl.catalog import Policy

HK_VERSION = "2.1.0"
HK_PACKAGE = f"package://github.com/jdx/hk/releases/download/v{HK_VERSION}/hk@{HK_VERSION}#"
HK_HOOKS = ("pre-commit", "pre-push", "fix", "check")
FIXING_HOOKS = ("pre-commit", "fix")


@attrs.frozen
class Frag:
    """A rendered fragment: data plus where its layer was placed."""

    data: dict[str, object]
    placement: str


@attrs.frozen
class SinkFile:
    path: str
    content: str
    policy: Policy = "merge"


type Sink = Callable[[list[Frag], dict[str, object]], list[SinkFile]]


class YamlIO(Protocol):
    """The typed surface of ruamel's (untyped) YAML object that tmpl uses."""

    def load(self, stream: str) -> object: ...
    def dump(self, data: object, stream: IO[str]) -> None: ...


class _Commentable(Protocol):
    def yaml_add_eol_comment(self, comment: str, key: str) -> None: ...


def _eol_comment(target: _Commentable, key: str, comment: str) -> None:
    target.yaml_add_eol_comment(comment, key)


def yaml() -> YamlIO:
    """The round-trip YAML dialect used for generated and merged YAML."""
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _str_map(value: object) -> dict[str, object]:
    return structure(value, dict[str, object])


def _str_list(value: object) -> list[str]:
    return structure(value, list[str])


def _merged(frags: list[Frag]) -> dict[str, object]:
    out: dict[str, object] = {}
    for frag in frags:
        out.update(frag.data)
    return out


def _inline(value: Mapping[str, object]) -> InlineTable:
    table = tomlkit.inline_table()
    for key, item in value.items():
        table[key] = item
    return table


def mise(frags_by_sink: dict[str, list[Frag]]) -> list[SinkFile]:
    doc = tomlkit.document()
    for section in ("tools", "env"):
        values = _merged(frags_by_sink.get(f"mise.{section}", []))
        if values:
            table = tomlkit.table()
            for key, value in values.items():
                # Dotted keys (mise's `_.python.venv`) stay dotted, with table values inline.
                item = _inline(value) if is_map(value) else value
                table.add(tomlkit.key(key.split(".")) if "." in key else key, item)
            doc.add(section, table)
    tasks = _merged(frags_by_sink.get("mise.tasks", []))
    if tasks:
        super_table = tomlkit.table(is_super_table=True)
        for name, task in tasks.items():
            table = tomlkit.table()
            for key, item in _str_map(task).items():
                table[key] = item
            super_table.add(name, table)
        doc.add("tasks", super_table)
    return [SinkFile(".config/mise/config.toml", tomlkit.dumps(doc))]


def _pkl(value: str) -> str:
    return json.dumps(value)


def hk(frags: list[Frag], _ctx: dict[str, object]) -> list[SinkFile]:
    steps = [_str_map(f.data) for f in frags]
    lines = [
        f'amends "{HK_PACKAGE}/Config.pkl"',
        f'import "{HK_PACKAGE}/Builtins.pkl"',
        "",
        "local defs = new Mapping<String, Step> {",
    ]
    for step in steps:
        name, builtin = str(step["name"]), step.get("builtin")
        props = [f"{k} = {_pkl(str(step[k]))}" for k in ("prefix", "check", "fix") if k in step]
        if "glob" in step:
            props.append(f"glob = List({_pkl(str(step['glob']))})")
        if builtin and not props:
            lines.append(f"  [{_pkl(name)}] = Builtins.{builtin}")
            continue
        lines.append(f"  [{_pkl(name)}] = (Builtins.{builtin}) {{" if builtin else f"  [{_pkl(name)}] {{")
        lines += [f"    {prop}" for prop in props]
        lines.append("  }")
    lines += ["}", "", "hooks {"]
    for hook in HK_HOOKS:
        lines.append(f"  [{_pkl(hook)}] {{")
        if hook in FIXING_HOOKS:
            lines.append("    fix = true")
        if hook == "pre-commit":
            lines.append('    stash = "git"')
        lines.append("    steps {")
        for step in steps:
            if hook not in _str_list(step.get("hooks", [])):
                continue
            ref = f"defs[{_pkl(str(step['name']))}]"
            # Thorough steps run on pre-push always, but in `check` only under the slow profile (CI).
            if hook == "check" and step.get("slow"):
                ref = f'({ref}) {{ profiles = List("slow") }}'
            lines.append(f"      [{_pkl(str(step['name']))}] = {ref}")
        lines += ["    }", "  }"]
    lines.append("}")
    return [SinkFile(".config/hk.pkl", "\n".join(lines) + "\n")]


def ci(frags: list[Frag], _ctx: dict[str, object]) -> list[SinkFile]:
    steps: list[CommentedMap] = []
    for frag in frags:
        data = dict(frag.data)
        comment = data.pop("comment", None)
        step = CommentedMap(data)
        if comment:
            _eol_comment(step, "uses", str(comment))
        steps.append(step)
    workflow = CommentedMap(
        {
            "name": "CI",
            "on": {"push": {"branches": ["main"]}, "pull_request": {"branches": ["main"]}},
            "permissions": {"contents": "read"},
            "jobs": {"check": {"runs-on": "ubuntu-latest", "steps": steps}},
        },
    )
    buf = io.StringIO()
    yaml().dump(workflow, buf)
    return [SinkFile(".github/workflows/ci.yml", buf.getvalue())]


def gitignore(frags: list[Frag], _ctx: dict[str, object]) -> list[SinkFile]:
    by_file: dict[str, list[str]] = {}
    for frag in frags:
        path = ".gitignore" if frag.placement == "." else f"{frag.placement}/.gitignore"
        block = [f"# {frag.data['heading']}", *_str_list(frag.data["lines"])]
        by_file.setdefault(path, []).append("\n".join(block))
    return [SinkFile(path, "\n\n".join(blocks) + "\n") for path, blocks in by_file.items()]


def editorconfig(frags: list[Frag], _ctx: dict[str, object]) -> list[SinkFile]:
    sections: dict[str, dict[str, object]] = {}
    for frag in frags:
        for glob, keys in frag.data.items():
            sections.setdefault(glob, {}).update(_str_map(keys))
    parts = ["root = true"]
    for glob, keys in sections.items():
        parts.append("\n".join([f"[{glob}]", *(f"{k} = {v}" for k, v in keys.items() if v != "")]))
    return [SinkFile(".editorconfig", "\n\n".join(parts) + "\n")]


def _sections(frags: list[Frag]) -> str:
    return "".join(f"\n## {f.data['title']}\n\n{str(f.data['body']).rstrip()}\n" for f in frags)


def readme(frags: list[Frag], ctx: dict[str, object]) -> list[SinkFile]:
    head = f"# {ctx['repo_name']}\n"
    if ctx.get("description"):
        head += f"\n{ctx['description']}\n"
    return [SinkFile("README.md", head + _sections(frags), policy="seed")]


def agents(frags: list[Frag], _ctx: dict[str, object]) -> list[SinkFile]:
    return [SinkFile("AGENTS.md", "# AGENTS.md\n" + _sections(frags))]


def python_workspace(frags: list[Frag], _ctx: dict[str, object]) -> list[SinkFile]:
    """A uv workspace once a python unit sits off `.`; render patches it into a root package's pyproject."""
    members = sorted({str(f.data["member"]) for f in frags} - {"."})
    if not members:
        return []
    doc = tomlkit.document()
    doc.add("tool", {"uv": {"workspace": {"members": members}}})
    return [SinkFile("pyproject.toml", tomlkit.dumps(doc))]


SINKS: dict[str, Sink] = {
    "hk.steps": hk,
    "ci.steps": ci,
    "gitignore": gitignore,
    "editorconfig": editorconfig,
    "readme.sections": readme,
    "agents.sections": agents,
    "workspace.python": python_workspace,
}
MISE_SINKS = ("mise.tools", "mise.env", "mise.tasks")
