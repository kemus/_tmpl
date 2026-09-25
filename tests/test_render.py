import tomllib

from tmpl.manifest import Manifest, Unit
from tmpl.render import render

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
        "tests/test_cli.py",
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
