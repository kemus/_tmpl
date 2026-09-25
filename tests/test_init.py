import tomllib
from pathlib import Path

import pytest

from tmpl import manifest
from tmpl.cli import UsageError, app

from .conftest import git


def run(*args: str) -> int:
    result = app(list(args), result_action="return_value")
    assert isinstance(result, int)
    return result


def test_init_creates_committed_scaffold(tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:cli", "--no-setup") == 0

    recorded = manifest.load(repo)
    assert recorded is not None
    assert recorded.root["author"] == "Test User"
    assert [(u.path, u.lang, u.kind) for u in recorded.unit] == [(".", "python", "cli")]
    assert (repo / "src/new_tool/cli.py").exists()
    assert (repo / "tests/test_cli.py").exists()
    assert tomllib.loads((repo / "pyproject.toml").read_text())["project"]["name"] == "new-tool"

    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "log", "--format=%s").splitlines() == ["chore: scaffold with tmpl 0.1.0", "initial commit"]
    assert "third_party/.gitkeep" in git(repo, "ls-files", "third_party")


def test_sync_after_init_is_a_no_op(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:cli@.", "--no-setup") == 0
    capsys.readouterr()
    assert run("sync", str(repo)) == 0
    assert capsys.readouterr().out.strip() == "nothing to do"
    assert git(repo, "status", "--porcelain") == ""


def test_init_routes_options_by_scope(tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    opts = ["--opt", "indent=4", "--opt", "type_checker_fast=ty", "--opt", "description=Does things"]
    assert run("init", str(repo), "--unit", "python:cli", *opts, "--no-setup") == 0
    recorded = manifest.load(repo)
    assert recorded is not None
    assert recorded.root["indent"] == "4"
    assert recorded.root["description"] == "Does things"
    assert recorded.lang["python"]["type_checker_fast"] == "ty"
    assert "indent_size = 4" in (repo / ".editorconfig").read_text()


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["--unit", "python:cli", "--opt", "nope=1"], "unknown options"),
        (["--unit", "cobol:cli"], "not in this version's catalog"),
        (["--unit", "python"], "expected LANG:KIND"),
        (["--unit", "python:cli", "--unit", "python:cli@."], "share a path"),
    ],
)
def test_init_rejects_bad_input(tmp_path: Path, args: list[str], error: str) -> None:
    repo = tmp_path / "new-tool"
    with pytest.raises(UsageError, match=error):
        run("init", str(repo), *args, "--no-setup")
    assert not repo.exists()


def test_init_refuses_non_empty_dir(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x\n")
    with pytest.raises(UsageError, match="not empty"):
        run("init", str(tmp_path), "--unit", "python:cli", "--no-setup")
