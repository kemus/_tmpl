import tomllib
from pathlib import Path

import pytest

from tmpl import manifest
from tmpl.cli import UsageError, app
from tmpl.detect import detect

from .conftest import commit_all, git


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
    assert (repo / "tests/test_new_tool_cli.py").exists()
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


def _script_groups(repo: Path) -> dict[str, list[object]] | None:
    return tomllib.loads((repo / "pyproject.toml").read_text()).get("dependency-groups")


# With a package, the group joins its pyproject; with scripts alone, the non-package root.
@pytest.mark.parametrize("units", [["--unit", "python:cli"], []])
def test_sync_follows_script_header_changes(units: list[str], tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), *units, "--unit", "python:scripts@scripts", "--no-setup") == 0
    script = repo / "scripts/example.py"

    for deps, expected in [('["rich>=13"]', ["rich>=13"]), ('["httpx"]', ["httpx"]), ("[]", None)]:
        text = script.read_text()
        script.write_text(text.replace(text.split("# dependencies = ")[1].split("\n")[0], deps))
        commit_all(repo, f"deps {deps}")
        assert run("sync", str(repo)) == 0
        groups = _script_groups(repo)
        assert groups is not None
        assert groups.get("scripts") == expected
        assert ({"include-group": "scripts"} in groups["dev"]) == (expected is not None)
        commit_all(repo, "sync")


def test_sync_check_reports_drift_without_writing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:scripts@scripts", "--no-setup") == 0
    capsys.readouterr()
    assert run("sync", str(repo), "--check") == 0
    assert capsys.readouterr().out == ""

    # Uncommitted on purpose: the check runs from hooks against any worktree.
    script = repo / "scripts/example.py"
    script.write_text(script.read_text().replace("# dependencies = []", '# dependencies = ["httpx"]'))
    assert run("sync", str(repo), "--check") == 1
    out = capsys.readouterr().out
    assert '+scripts = ["httpx"]' in out
    assert "  update  pyproject.toml" in out
    assert git(repo, "status", "--porcelain").splitlines() == [" M scripts/example.py"]


def test_sync_check_reports_a_manifest_to_restamp(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:lib", "--no-setup") == 0
    path = repo / manifest.MANIFEST_PATH
    path.write_text(path.read_text().replace('version = "0.1.0"\n', ""))
    commit_all(repo, "unversioned")
    capsys.readouterr()
    assert run("sync", str(repo), "--check") == 1
    assert "(version unset -> 0.1.0)" in capsys.readouterr().out
    assert git(repo, "status", "--porcelain") == ""


def test_sync_check_hk_step_runs_the_recorded_release(tmp_path: Path) -> None:
    repo = tmp_path / "on"
    assert run("init", str(repo), "--unit", "python:lib", "--no-setup") == 0
    step = 'check = "uvx --no-config --from git+https://github.com/kemus/_tmpl@v0.1.0 tmpl sync --check"'
    assert step in (repo / ".config/hk.pkl").read_text()

    off = tmp_path / "off"
    assert run("init", str(off), "--unit", "python:lib", "--opt", "sync_check=false", "--no-setup") == 0
    assert "tmpl_sync" not in (off / ".config/hk.pkl").read_text()


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


def test_init_stores_bool_options_as_booleans(tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    unit = ["--unit", "python:scripts@scripts", "--opt", "importable=true"]
    assert run("init", str(repo), *unit, "--no-setup") == 0
    recorded = manifest.load(repo)
    assert recorded is not None
    assert recorded.unit[0].options["importable"] is True


def test_init_rejects_a_non_boolean_bool_option(tmp_path: Path) -> None:
    unit = ["--unit", "python:scripts@scripts", "--opt", "importable=yes"]
    with pytest.raises(ValueError, match="expected true or false"):
        run("init", str(tmp_path / "new-tool"), *unit, "--no-setup")


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


def test_generated_scripts_root_is_not_reported(tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:scripts@scripts", "--no-setup") == 0
    detected = detect(repo)
    assert [(u.path, u.kind) for u in detected.manifest.unit] == [("scripts", "scripts")]
    assert detected.warnings == []
