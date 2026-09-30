"""`tmpl update`: move a repo to another tmpl release (§8.6)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tmpl import __version__, catalog, manifest, proc
from tmpl.cli import UsageError

from .conftest import commit_all, git
from .test_commands import new_repo, recorded, run


def test_update_to_this_version_records_new_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = new_repo(tmp_path, "python:lib")
    assert run("feature", "add", "deps-update", "--repo", str(repo)) == 0
    commit_all(repo, "add deps-update")
    templates = tmp_path / "templates"
    shutil.copytree(catalog.TEMPLATES, templates)
    with (templates / "root/template.toml").open("a") as spec:
        spec.write('\n[options.greeting]\nscope = "root"\ndefault = "hi"\n')
    monkeypatch.setattr(catalog, "TEMPLATES", templates)
    catalog.layer.cache_clear()
    try:
        capsys.readouterr()
        assert run("update", str(repo), "--to", f"v{__version__}") == 0
        assert "     new  [root] greeting = 'hi'" in capsys.readouterr().out
        assert recorded(repo).root["greeting"] == "hi"
        assert recorded(repo).features == ["deps-update"]
    finally:
        catalog.layer.cache_clear()


def test_update_drops_undeclared_options(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = new_repo(tmp_path, "python:lib")
    clean = recorded(repo)
    edited = recorded(repo)
    edited.root["gone"] = 1
    edited.lang["python"] = {**edited.lang.get("python", {}), "old": True}
    edited.unit[0].options["stale"] = "x"
    manifest.dump(repo, edited)
    commit_all(repo, "hand edit")
    capsys.readouterr()
    assert run("update", str(repo), "--to", __version__) == 0
    assert [line for line in capsys.readouterr().out.splitlines() if "dropped" in line] == [
        " dropped  [root] gone = 1",
        " dropped  [lang.python] old = True",
        " dropped  [unit .] stale = 'x'",
    ]
    assert recorded(repo) == clean


def test_update_to_another_release_runs_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = new_repo(tmp_path, "python:lib")
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(proc, "run", fake_run)
    assert run("update", str(repo), "--to", "9.0.0", "--dry-run") == 0
    assert run("update", str(repo), "--to", "0.2.0", "--prefer", "ours") == 0
    uvx = ("uvx", "--no-config", "--from")
    assert calls == [
        (*uvx, f"{manifest.DEFAULT_SOURCE}@v9.0.0", "tmpl", "update", "--to", "9.0.0", str(repo), "--dry-run"),
        (*uvx, f"{manifest.DEFAULT_SOURCE}@v0.2.0", "tmpl", "sync", str(repo), "--prefer", "ours"),
    ]


def test_update_defaults_to_the_latest_release_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "commit", "-q", "--allow-empty", "-m", "release")
    for tag in ("v0.1.0", "v0.10.0", "v0.9.2", "v1.0.0rc1", "latest"):
        git(source, "tag", tag)
    repo = new_repo(tmp_path, "python:lib")
    current = recorded(repo)
    current.source = f"git+file://{source}"
    manifest.dump(repo, current)
    commit_all(repo, "local source")
    calls: list[tuple[str, ...]] = []
    real_run = proc.run

    def fake_uvx(*args: str, **_: object) -> subprocess.CompletedProcess[str]:
        if args[0] != "uvx":
            return real_run(*args)
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(proc, "run", fake_uvx)
    assert run("update", str(repo)) == 0
    assert calls[0][3] == f"git+file://{source}@v0.10.0"


def test_update_refuses_a_versionless_manifest(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    current = recorded(repo)
    current.version = ""
    manifest.dump(repo, current)
    with pytest.raises(UsageError, match="has no version yet"):
        run("update", str(repo), "--to", "9.0.0")


@pytest.mark.parametrize("version", ["1.2", "latest", "v1.2.3.4"])
def test_update_refuses_a_malformed_version(version: str, tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    with pytest.raises(UsageError, match=r"expected X\.Y\.Z"):
        run("update", str(repo), "--to", version)


def test_every_change_refreshes_options(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = new_repo(tmp_path, "python:lib")
    edited = recorded(repo)
    edited.root["gone"] = 1
    manifest.dump(repo, edited)
    commit_all(repo, "hand edit")
    capsys.readouterr()
    assert run("set", "sync_check=false", "--repo", str(repo)) == 0
    assert " dropped  [root] gone = 1" in capsys.readouterr().out
    assert "gone" not in recorded(repo).root
    assert recorded(repo).root["sync_check"] is False


def test_changes_refuse_a_manifest_from_a_later_release(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    later = recorded(repo)
    later.version = "99.0.0"
    manifest.dump(repo, later)
    commit_all(repo, "from a later release")
    with pytest.raises(UsageError, match=r"is at tmpl 99\.0\.0, later than this tmpl"):
        run("set", "sync_check=false", "--repo", str(repo))
    with pytest.raises(UsageError, match="later than this tmpl"):
        run("sync", str(repo))
    assert run("update", str(repo), "--to", __version__) == 0
    assert recorded(repo).version == __version__


def test_tool_output_follows_ours_on_a_pipe() -> None:
    script = 'import sys; from tmpl import proc; sys.stdout.write("ours\\n"); proc.run("echo", "tool", capture=False)'
    done = proc.run(sys.executable, "-c", script)
    assert (done.returncode, done.stdout) == (0, "ours\ntool\n")
