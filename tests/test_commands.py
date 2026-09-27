"""`tmpl set`, `add` and `remove`: change the manifest, then reconcile against the applied base."""

import tomllib
from pathlib import Path

import pytest

from tmpl import manifest
from tmpl.cli import UsageError, app

from .conftest import commit_all, git


def run(*args: str) -> int:
    result = app(list(args), result_action="return_value")
    assert isinstance(result, int)
    return result


def new_repo(tmp_path: Path, *units: str) -> Path:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), *(f"--unit={u}" for u in units), "--no-setup") == 0
    return repo


def recorded(repo: Path) -> manifest.Manifest:
    current = manifest.load(repo)
    assert current is not None
    assert current.applied == manifest.digest(current)
    return current


def test_set_a_root_option_updates_the_manifest_and_files(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    assert run("set", "indent=4", "max_line_length=100", "--repo", str(repo)) == 0
    assert recorded(repo).root | {"indent": "4", "max_line_length": 100} == recorded(repo).root
    assert "indent_size = 4" in (repo / ".editorconfig").read_text().split("[*]\n")[1].split("\n[")[0]


def test_set_a_language_option(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    assert run("set", "type_checker_thorough=none", "--repo", str(repo)) == 0
    assert recorded(repo).lang["python"]["type_checker_thorough"] == "none"
    assert "mypy" not in tomllib.loads((repo / "pyproject.toml").read_text())["tool"]


def test_set_a_unit_option_needs_the_unit_when_several_declare_it(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:scripts@scripts", "python:scripts@tools")
    with pytest.raises(UsageError, match="several units; pass --unit PATH"):
        run("set", "importable=true", "--repo", str(repo))
    assert run("set", "importable=true", "--unit", "tools/", "--repo", str(repo)) == 0
    options = {u.path: u.options["importable"] for u in recorded(repo).unit}
    assert options == {"scripts": False, "tools": True}


@pytest.mark.parametrize(
    ("pair", "error"),
    [
        ("nope=1", UsageError),
        ("", UsageError),
        ("python_version=3.13", UsageError),
        ("indent=3", ValueError),
        ("max_line_length=wide", ValueError),
    ],
)
def test_set_refuses_bad_options(pair: str, error: type[Exception], tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    before = (repo / manifest.MANIFEST_PATH).read_text()
    with pytest.raises(error):
        run("set", *filter(None, [pair]), "--repo", str(repo))
    assert (repo / manifest.MANIFEST_PATH).read_text() == before


def test_set_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = new_repo(tmp_path, "python:lib")
    capsys.readouterr()
    assert run("set", "indent=4", "--dry-run", "--repo", str(repo)) == 0
    assert "+indent_size = 4" in capsys.readouterr().out
    assert git(repo, "status", "--porcelain") == ""


def test_add_then_remove_a_unit(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    before = (repo / "pyproject.toml").read_text()
    assert run("add", "python:cli@apps/tool", "--repo", str(repo)) == 0
    assert [(u.path, u.kind) for u in recorded(repo).unit] == [(".", "lib"), ("apps/tool", "cli")]
    assert (repo / "apps/tool/src/tool/cli.py").exists()
    assert "apps/tool" in tomllib.loads((repo / "pyproject.toml").read_text())["tool"]["uv"]["workspace"]["members"]
    commit_all(repo, "add tool")

    assert run("remove", "apps/tool", "--repo", str(repo)) == 0
    assert [u.path for u in recorded(repo).unit] == ["."]
    assert not (repo / "apps").exists()
    assert (repo / "pyproject.toml").read_text() == before


def test_add_refuses_a_taken_path_and_foreign_options(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    with pytest.raises(UsageError, match=r"already lives at \.$"):
        run("add", "python:cli", "--repo", str(repo))
    with pytest.raises(UsageError, match=r"unknown options for this unit: \['indent'\]"):
        run("add", "python:cli@apps/tool", "--opt", "indent=4", "--repo", str(repo))
    with pytest.raises(UsageError, match="set python options with `tmpl set`"):
        run("add", "python:cli@apps/tool", "--opt", "type_checker_fast=ty", "--repo", str(repo))


def test_add_takes_unit_options(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    assert run("add", "python:scripts@scripts", "--opt", "importable=true", "--repo", str(repo)) == 0
    assert recorded(repo).unit[1].options == {"importable": True}


def test_remove_keeps_modified_files_and_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = new_repo(tmp_path, "python:lib", "python:cli@apps/tool")
    cli = repo / "apps/tool/src/tool/cli.py"
    cli.write_text(cli.read_text() + "# mine\n")
    commit_all(repo, "edit the cli")
    capsys.readouterr()
    assert run("remove", "apps/tool", "--repo", str(repo)) == 1
    assert "    kept  apps/tool/src/tool/cli.py" in capsys.readouterr().out
    assert cli.exists()
    assert not (repo / "apps/tool/pyproject.toml").exists()


def test_remove_the_last_unit_of_a_language_drops_the_language(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:scripts@scripts")
    assert run("set", "type_checker_fast=ty", "--repo", str(repo)) == 0
    commit_all(repo, "use ty")
    with pytest.raises(UsageError, match="no unit at nope; units: scripts"):
        run("remove", "nope", "--repo", str(repo))
    assert run("remove", "scripts", "--repo", str(repo)) == 0
    assert recorded(repo).lang == {}
    assert not (repo / "pyproject.toml").exists()


def test_commands_refuse_a_versionless_manifest(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    path = repo / manifest.MANIFEST_PATH
    path.write_text(path.read_text().replace(f'version = "{recorded(repo).version}"\n', ""))
    commit_all(repo, "unversioned")
    with pytest.raises(UsageError, match="has no version yet"):
        run("set", "indent=4", "--repo", str(repo))
