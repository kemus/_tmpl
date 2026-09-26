"""Detect and adopt against trimmed copies of real repos, plus a synthetic uv workspace.

Fixtures hold config only; Python stubs are written here so this repo's linters never see them.
"""

import shutil
import tomllib
from pathlib import Path

import pytest

from tmpl import manifest
from tmpl.cli import app
from tmpl.detect import DetectError, detect

from .conftest import commit_all, git, write

FIXTURES = Path(__file__).parent / "fixtures"
PEP723 = '# /// script\n# requires-python = ">=3.14"\n# dependencies = ["cyclopts>=4.25"]\n# ///\n"""Stub."""\n'

STUBS = {
    "llmstxt-scraper": {"src/llmstxt_scraper/__init__.py": "", "src/llmstxt_scraper/cli/__init__.py": ""},
    "kupdate": {"src/kupdate/__init__.py": "", "src/kupdate/cli.py": "def main() -> None: ...\n"},
    "serve": {"main.py": "def main() -> None: ...\n", "index.ts": "export {};\n"},
    "ai-sessions": {"scripts/update.py": PEP723, "tests/__init__.py": "", "tests/test_update.py": ""},
    "uv-workspace": {
        "apps/tool/src/tool/__init__.py": "",
        "libs/core/src/core/__init__.py": "",
        "scripts/report.py": PEP723,
        # A nested checkout: its scripts are someone else's and must not become a unit.
        "vendors/other/.git/HEAD": "ref: refs/heads/main\n",
        "vendors/other/tool.py": PEP723,
    },
}

CONFIG_WARNINGS = {
    "llmstxt-scraper": [".config/ruff.toml", ".config/mypy.ini", ".config/ty.toml", "pyrightconfig.json"],
    "kupdate": [".config/ruff.toml", ".config/mypy.ini", ".config/pytest.ini", ".config/basedpyright.json"],
    "ai-sessions": [".config/ruff.toml", ".config/mypy.ini", ".config/pytest.toml", ".config/pyrightconfig.json"],
    "uv-workspace": [],
}

UNITS = {
    "llmstxt-scraper": [(".", "cli")],
    "kupdate": [(".", "cli")],
    "ai-sessions": [("scripts", "scripts")],
    "uv-workspace": [("apps/tool", "cli"), ("libs/core", "lib"), ("scripts", "scripts")],
}

CHECKERS = {
    "llmstxt-scraper": {"type_checker_fast": "basedpyright", "type_checker_thorough": "mypy"},
    "kupdate": {"type_checker_fast": "basedpyright", "type_checker_thorough": "mypy"},
    "ai-sessions": {"type_checker_fast": "basedpyright", "type_checker_thorough": "mypy"},
    "uv-workspace": {"type_checker_fast": "ty", "type_checker_thorough": "none"},
}


def run(*args: str) -> int:
    result = app(list(args), result_action="return_value")
    assert isinstance(result, int)
    return result


def copy(name: str, tmp_path: Path) -> Path:
    path = tmp_path / name
    shutil.copytree(FIXTURES / name, path)
    write(path, STUBS[name])
    git(path, "init", "-q")
    commit_all(path, "initial")
    return path


@pytest.mark.parametrize("name", list(UNITS))
def test_detect(name: str, tmp_path: Path) -> None:
    detected = detect(copy(name, tmp_path))
    assert [(u.path, u.kind) for u in detected.manifest.unit] == UNITS[name]
    assert detected.manifest.lang["python"] == CHECKERS[name]
    config = [w.split()[1].rstrip(":") for w in detected.warnings if w.startswith("existing ")]
    assert config == CONFIG_WARNINGS[name]


def test_non_package_root_is_reported(tmp_path: Path) -> None:
    detected = detect(copy("ai-sessions", tmp_path))
    assert "pyproject.toml is not a package (no [build-system], or tool.uv.package = false); " in detected.warnings[0]


def test_serve_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DetectError, match=r"no supported units found.*pyproject\.toml is not a package"):
        detect(copy("serve", tmp_path))


# The real repos carry their own hk.pkl; adopting it without a base is a text conflict.
OWN_HK = ["llmstxt-scraper", "kupdate", "ai-sessions"]


@pytest.mark.parametrize("name", OWN_HK)
def test_adopt_conflicts_on_own_hk_config(name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = copy(name, tmp_path)
    assert run("adopt", str(repo), "--yes") == 1
    assert "conflict  .config/hk.pkl" in capsys.readouterr().out
    assert "<<<<<<<" in (repo / ".config/hk.pkl").read_text()


@pytest.mark.parametrize("name", list(UNITS))
def test_sync_after_adopt_is_a_no_op(name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = copy(name, tmp_path)
    assert run("adopt", str(repo), "--yes", "--prefer", "ours") == 0
    commit_all(repo, "adopt tmpl")
    capsys.readouterr()
    assert run("sync", str(repo)) == 0
    assert capsys.readouterr().out.strip() == "nothing to do"
    assert git(repo, "status", "--porcelain") == ""


def test_adopt_workspace_keeps_members_and_skips_scripts(tmp_path: Path) -> None:
    repo = copy("uv-workspace", tmp_path)
    assert run("adopt", str(repo), "--yes") == 0
    recorded = manifest.load(repo)
    assert recorded is not None
    assert [(u.path, u.kind) for u in recorded.unit] == UNITS["uv-workspace"]

    root = tomllib.loads((repo / "pyproject.toml").read_text())
    assert "project" not in root
    assert set(root["tool"]["uv"]["workspace"]["members"]) >= {"apps/*", "libs/*"}
    assert not (repo / "scripts/pyproject.toml").exists()
    # The script's PEP 723 dependencies reach the venv through the root dev group.
    assert root["dependency-groups"]["scripts"] == ["cyclopts>=4.25"]
    assert {"include-group": "scripts"} in root["dependency-groups"]["dev"]
    tool = tomllib.loads((repo / "apps/tool/pyproject.toml").read_text())
    assert tool["project"]["version"] == "0.3.0"
    assert tool["tool"]["uv"]["sources"] == {"core": {"workspace": True}}
