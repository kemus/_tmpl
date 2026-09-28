import shutil
import tomllib
from pathlib import Path

import pytest

from tmpl import manifest
from tmpl.cli import app
from tmpl.detect import DetectError, detect

from .conftest import commit_all, git, write

FIXTURES = Path(__file__).parent / "fixtures"


def run(*args: str) -> int:
    result = app(list(args), result_action="return_value")
    assert isinstance(result, int)
    return result


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "legacy-tool"
    shutil.copytree(FIXTURES / "py-cli", path)
    git(path, "init", "-q")
    commit_all(path, "initial")
    return path


def test_adopt_detects_and_preserves(repo: Path) -> None:
    assert run("adopt", str(repo), "--yes") == 0
    recorded = manifest.load(repo)
    assert recorded is not None
    assert recorded.root["author"] == "Legacy Author"
    assert recorded.root["max_line_length"] == 100
    assert recorded.lang["python"] == {"type_checker_fast": "mypy", "type_checker_thorough": "none"}
    assert [(u.path, u.lang, u.kind) for u in recorded.unit] == [(".", "python", "cli")]

    pyproject = tomllib.loads((repo / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == "1.4.2"
    assert pyproject["project"]["requires-python"] == ">=3.13"
    assert pyproject["project"]["dependencies"] == ["cyclopts>=4", "httpx"]
    assert pyproject["tool"]["ruff"]["line-length"] == 100
    assert pyproject["tool"]["ruff"]["lint"]["select"] == ["ALL"]
    assert pyproject["dependency-groups"]["dev"] == ["pytest>=8", "mypy>=1.10", "ruff"]

    lines = [line for line in (repo / ".gitignore").read_text().splitlines() if line]
    mine = ["__pycache__/", "*.pyc", "/scratch/"]
    assert [line for line in lines if line in mine] == mine
    assert ".venv/" in lines
    assert len(lines) == len(set(lines))
    assert (repo / "README.md").read_text() == "# legacy-tool\n\nHand-written readme.\n"
    assert (repo / "src/legacy_tool/cli.py").read_text() == 'def main() -> None:\n    print("legacy")\n'
    assert not (repo / "src/legacy_tool/__main__.py").exists()
    assert not (repo / "tests").exists()
    assert (repo / ".config/hk.pkl").exists()
    assert "third_party/.gitkeep" in git(repo, "ls-files", "--cached", "third_party")


def test_sync_after_adopt_is_a_no_op(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("adopt", str(repo), "--yes") == 0
    commit_all(repo, "adopt tmpl")
    capsys.readouterr()
    assert run("sync", str(repo)) == 0
    assert capsys.readouterr().out.strip() == "nothing to do"
    assert git(repo, "status", "--porcelain") == ""


def test_sync_applies_option_change_and_keeps_local_edits(repo: Path) -> None:
    assert run("adopt", str(repo), "--yes") == 0
    agents = repo / "AGENTS.md"
    agents.write_text(agents.read_text() + "\n## Local notes\n\nKeep this.\n")
    commit_all(repo, "adopt tmpl")
    manifest_path = repo / manifest.MANIFEST_PATH
    manifest_path.write_text(manifest_path.read_text().replace('indent = "2"', 'indent = "4"'))
    commit_all(repo, "switch to 4-space indent")

    assert run("sync", str(repo)) == 0
    assert "indent_size = 4" in (repo / ".editorconfig").read_text()
    assert (repo / "AGENTS.md").read_text().endswith("## Local notes\n\nKeep this.\n")


def test_adopt_refuses_dirty_tree(repo: Path) -> None:
    (repo / "README.md").write_text("changed\n")
    with pytest.raises(Exception, match="uncommitted changes"):
        run("adopt", str(repo), "--yes")


def test_detect_refuses_nested_units(tmp_path: Path) -> None:
    package = (
        '[project]\nname = "{name}"\n\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    write(
        tmp_path,
        {
            "pyproject.toml": '[tool.uv.workspace]\nmembers = ["apps", "apps/tool"]\n',
            "apps/pyproject.toml": package.format(name="apps"),
            "apps/tool/pyproject.toml": package.format(name="tool"),
        },
    )
    with pytest.raises(DetectError, match="detected units at apps and apps/tool, which nest"):
        detect(tmp_path)
