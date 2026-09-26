import tomllib
from pathlib import Path

import pytest

from tmpl import pep723
from tmpl.manifest import Manifest, Unit
from tmpl.render import RenderError, render

from .conftest import write

MANIFEST = Manifest(
    version="0.1.0",
    root={"description": "Demo tool", "author": "Test User"},
    lang={"python": {"type_checker_fast": "basedpyright", "type_checker_thorough": "mypy"}},
    unit=[Unit(".", "python", "cli")],
)


def test_python_cli_tree() -> None:
    tree = render(MANIFEST, "demo-tool")
    assert {
        ".config/hk.pkl",
        ".config/mise/config.toml",
        ".editorconfig",
        ".github/workflows/ci.yml",
        ".gitignore",
        "AGENTS.md",
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "src/demo_tool/__init__.py",
        "src/demo_tool/cli.py",
        "tests/test_demo_tool_cli.py",
        "third_party/.gitkeep",
    } <= set(tree)
    assert tree["src/demo_tool/cli.py"].scaffold
    assert tree["README.md"].policy == "seed"
    assert tree["third_party/.gitkeep"].force_add


def test_pyproject_combines_layers() -> None:
    data = tomllib.loads(render(MANIFEST, "demo-tool")["pyproject.toml"].content)
    assert data["project"]["name"] == "demo-tool"
    assert data["project"]["dependencies"] == ["cyclopts"]
    assert data["project"]["scripts"] == {"demo-tool": "demo_tool.cli:main"}
    assert data["dependency-groups"]["dev"] == ["basedpyright", "mypy", "pytest", "ruff"]
    assert "basedpyright" in data["tool"]
    assert "mypy" in data["tool"]


def test_hk_runs_thorough_checker_only_under_slow_profile() -> None:
    pkl = render(MANIFEST, "demo-tool")[".config/hk.pkl"].content
    assert '["mypy"] = (defs["mypy"]) { profiles = List("slow") }' in pkl
    assert "prefix" not in pkl


def test_render_is_deterministic() -> None:
    assert render(MANIFEST, "demo-tool") == render(MANIFEST, "demo-tool")


SCRIPT = '# /// script\n# dependencies = [\n#   "httpx>=0.27",\n#   "rich",\n# ]\n# ///\n'


def test_script_dependencies_join_the_root_dev_group(tmp_path: Path) -> None:
    write(tmp_path, {"scripts/fetch.py": SCRIPT, "scripts/show.py": '# /// script\n# dependencies = ["rich"]\n# ///\n'})
    manifest = Manifest(version="0.1.0", unit=[Unit(".", "python", "cli"), Unit("scripts", "python", "scripts")])
    groups = tomllib.loads(render(manifest, "demo-tool", tmp_path)["pyproject.toml"].content)["dependency-groups"]
    assert groups["scripts"] == ["httpx>=0.27", "rich"]
    assert groups["dev"][-1] == {"include-group": "scripts"}


def test_scripts_without_dependencies_add_no_group(tmp_path: Path) -> None:
    manifest = Manifest(version="0.1.0", unit=[Unit(".", "python", "cli"), Unit("scripts", "python", "scripts")])
    data = tomllib.loads(render(manifest, "demo-tool", tmp_path)["pyproject.toml"].content)
    assert "scripts" not in data["dependency-groups"]


def test_invalid_script_metadata_is_a_render_error(tmp_path: Path) -> None:
    write(tmp_path, {"scripts/bad.py": "# /// script\n# dependencies = [1]\n# ///\n"})
    manifest = Manifest(version="0.1.0", unit=[Unit(".", "python", "cli"), Unit("scripts", "python", "scripts")])
    with pytest.raises(RenderError, match=r"scripts/bad\.py: invalid PEP 723 metadata"):
        render(manifest, "demo-tool", tmp_path)


@pytest.mark.parametrize(
    ("text", "deps"),
    [
        ("print()\n", []),
        (SCRIPT, ["httpx>=0.27", "rich"]),
        ('# /// script\n# requires-python = ">=3.14"\n# ///\n', []),
        ("#!/usr/bin/env -S uv run --script\n" + SCRIPT + '"""Doc."""\n', ["httpx>=0.27", "rich"]),
    ],
)
def test_pep723_dependencies(text: str, deps: list[str]) -> None:
    assert pep723.dependencies(text) == deps


def test_pep723_rejects_two_script_blocks() -> None:
    with pytest.raises(ValueError, match="multiple"):
        pep723.dependencies(SCRIPT + "import sys\n" + SCRIPT)
