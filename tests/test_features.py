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
    """A copy of the templates with `docs`, a unit feature for python cli units."""
    templates = tmp_path / "templates"
    shutil.copytree(catalog.TEMPLATES, templates)
    write(
        templates,
        {
            "feature/docs/template.toml": 'attaches = "unit"\nkinds = ["cli"]\n',
            "lang/python/feature/docs/template.toml": "",
            "lang/python/feature/docs/files/docs/{{ unit.slug }}.md.jinja": "# {{ unit.name }}\n",
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
    assert (repo / "apps/tool/docs/tool.md").read_text() == "# tool\n"
    commit_all(repo, "add docs")

    with pytest.raises(UsageError, match=r"not attached to the unit at \.;"):
        run("feature", "remove", "docs", ".", "--repo", str(repo))
    assert run("feature", "remove", "docs", "apps/tool", "--repo", str(repo)) == 0
    assert recorded(repo).unit[1].features == []
    assert not (repo / "apps/tool/docs").exists()
