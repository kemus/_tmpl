"""`tmpl feature add|remove`: attach features to the root or a unit (§4.3, §8.5)."""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from tmpl import catalog
from tmpl.cli import UsageError

from .conftest import commit_all, write
from .test_commands import new_repo, recorded, run

RENOVATE = ".github/renovate.json"


def test_add_then_remove_a_root_feature(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    assert run("feature", "add", "deps-update", "--repo", str(repo)) == 0
    assert recorded(repo).features == ["deps-update"]
    assert "config:recommended" in json.loads((repo / RENOVATE).read_text())["extends"]
    commit_all(repo, "add deps-update")

    assert run("feature", "remove", "deps-update", "--repo", str(repo)) == 0
    assert "features" not in recorded(repo).root
    assert not (repo / RENOVATE).exists()


def test_feature_add_refuses_what_does_not_fit(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    before = (repo / ".config/tmpl.toml").read_text()
    with pytest.raises(UsageError, match="unknown feature 'nope'; features: deps-update"):
        run("feature", "add", "nope", "--repo", str(repo))
    with pytest.raises(UsageError, match="feature 'deps-update' attaches to the root"):
        run("feature", "add", "deps-update", ".", "--repo", str(repo))
    with pytest.raises(UsageError, match="feature 'deps-update' is not attached to the root; attached: none"):
        run("feature", "remove", "deps-update", "--repo", str(repo))
    assert (repo / ".config/tmpl.toml").read_text() == before
    assert run("feature", "add", "deps-update", "--repo", str(repo)) == 0
    commit_all(repo, "add deps-update")
    with pytest.raises(UsageError, match="already attached to the root"):
        run("feature", "add", "deps-update", "--repo", str(repo))


@pytest.fixture
def unit_feature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A copy of the templates with `docs`, a unit feature for python cli units, and `banner`, a root feature.

    Each declares options: `docs` a unit option and a python one, `banner` a root option.
    """
    templates = tmp_path / "templates"
    shutil.copytree(catalog.TEMPLATES, templates)
    write(
        templates,
        {
            "feature/docs/template.toml": (
                'attaches = "unit"\nkinds = ["cli"]\n[options.style]\nscope = "unit"\nchoices = ["short", "long"]\n'
                'default = "long"\n'
            ),
            "lang/python/feature/docs/template.toml": '[options.docs_tool]\nscope = "lang"\ndefault = "mkdocs"\n',
            "lang/python/feature/docs/files/docs/{{ unit.slug }}.md.jinja": (
                "# {{ unit.name }}\n\n{{ style }}, built with {{ docs_tool }}\n"
            ),
            "feature/banner/template.toml": 'attaches = "root"\n[options.banner]\nscope = "root"\ndefault = "hi"\n',
            "feature/banner/files/BANNER.jinja": "{{ banner }}\n",
        },
    )
    monkeypatch.setattr(catalog, "TEMPLATES", templates)
    catalog.layer.cache_clear()
    yield
    catalog.layer.cache_clear()


@pytest.mark.usefixtures("unit_feature")
def test_add_then_remove_a_unit_feature(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib", "python:cli@apps/tool")
    with pytest.raises(UsageError, match=r"attaches to a unit \(pass its PATH\)"):
        run("feature", "add", "docs", "--repo", str(repo))
    with pytest.raises(UsageError, match="suits cli units, not lib"):
        run("feature", "add", "docs", ".", "--repo", str(repo))
    assert run("feature", "add", "docs", "apps/tool/", "--repo", str(repo)) == 0
    assert recorded(repo).unit[1].features == ["docs"]
    assert (repo / "apps/tool/docs/tool.md").read_text() == "# tool\n\nlong, built with mkdocs\n"
    commit_all(repo, "add docs")

    with pytest.raises(UsageError, match=r"not attached to the unit at \.;"):
        run("feature", "remove", "docs", ".", "--repo", str(repo))
    assert run("feature", "remove", "docs", "apps/tool", "--repo", str(repo)) == 0
    assert recorded(repo).unit[1].features == []
    assert not (repo / "apps/tool/docs").exists()


@pytest.mark.usefixtures("unit_feature")
def test_unit_feature_options(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = new_repo(tmp_path, "python:lib", "python:cli@apps/tool")
    with pytest.raises(UsageError, match="option 'name': not declared by feature 'docs'"):
        run("feature", "add", "docs", "apps/tool", "--opt", "name=x", "--repo", str(repo))
    with pytest.raises(ValueError, match="expected one of"):
        run("feature", "add", "docs", "apps/tool", "--opt", "style=medium", "--repo", str(repo))
    capsys.readouterr()
    assert run("feature", "add", "docs", "apps/tool", "--opt", "style=short", "--repo", str(repo)) == 0
    assert "     new  [lang.python] docs_tool = 'mkdocs'" in capsys.readouterr().out
    assert recorded(repo).unit[1].options["style"] == "short"
    assert recorded(repo).lang["python"]["docs_tool"] == "mkdocs"
    assert (repo / "apps/tool/docs/tool.md").read_text() == "# tool\n\nshort, built with mkdocs\n"
    commit_all(repo, "add docs")

    assert run("set", "docs_tool=sphinx", "--repo", str(repo)) == 0
    assert (repo / "apps/tool/docs/tool.md").read_text() == "# tool\n\nshort, built with sphinx\n"
    commit_all(repo, "use sphinx")

    capsys.readouterr()
    assert run("feature", "remove", "docs", "apps/tool", "--repo", str(repo)) == 0
    assert [line for line in capsys.readouterr().out.splitlines() if "dropped" in line] == [
        " dropped  [lang.python] docs_tool = 'sphinx'",
        " dropped  [unit apps/tool] style = 'short'",
    ]
    assert "style" not in recorded(repo).unit[1].options
    assert "docs_tool" not in recorded(repo).lang.get("python", {})


@pytest.mark.usefixtures("unit_feature")
def test_removing_a_unit_drops_its_features_language_options(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib", "python:cli@apps/tool")
    assert run("feature", "add", "docs", "apps/tool", "--repo", str(repo)) == 0
    commit_all(repo, "add docs")
    assert run("remove", "apps/tool", "--repo", str(repo)) == 0
    assert "docs_tool" not in recorded(repo).lang.get("python", {})


@pytest.mark.usefixtures("unit_feature")
def test_root_feature_options(tmp_path: Path) -> None:
    repo = new_repo(tmp_path, "python:lib")
    assert run("feature", "add", "banner", "--opt", "banner=hello", "--repo", str(repo)) == 0
    assert recorded(repo).root["banner"] == "hello"
    assert (repo / "BANNER").read_text() == "hello\n"
    commit_all(repo, "add banner")

    assert run("feature", "remove", "banner", "--repo", str(repo)) == 0
    assert "banner" not in recorded(repo).root
    assert not (repo / "BANNER").exists()
