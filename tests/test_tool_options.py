import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from tmpl import catalog, manifest, sinks
from tmpl.cli import UsageError
from tmpl.detect import detect
from tmpl.manifest import Manifest, Unit
from tmpl.render import option_context, render

from .conftest import commit_all, write
from .test_commands import recorded
from .test_init import run


@pytest.fixture
def tool_groups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Add example groups and a minimal TS layer without shipping unevaluated tools."""
    templates = tmp_path / "templates"
    shutil.copytree(catalog.TEMPLATES, templates)
    root = templates / "root/template.toml"
    root.write_text(
        root.read_text()
        + """
[options.yaml_formatters]
scope = "root"
type = "tools"
files = ["*.yaml", "*.yml"]
choices = ["yamlfmt", "prettier"]
default = { yamlfmt = "pre-commit" }
default_by_layer = { "lang/ts" = { prettier = "pre-commit" } }

[options.shell_linters]
scope = "root"
type = "tools"
files = ["*.sh"]
choices = ["shellcheck"]
default = { shellcheck = "pre-push" }

[options.json_formatters]
scope = "root"
type = "tools"
files = ["*.json"]
choices = ["prettier"]
default = { prettier = "pre-commit" }

[[fragment]]
sink = "test.shell"
when = "{{ 'shellcheck' in shell_linters }}"
data = {}
""",
    )
    write(
        templates,
        {
            "lang/ts/template.toml": "",
            "lang/ts/kind/lib/template.toml": "",
            "lang/ts/kind/lib/files/index.ts": "export {};\n",
            "feature/assets/template.toml": (
                'attaches = "root"\n[options.asset_name]\nscope = "root"\ndefault = "notes.txt"\n'
                '[options.asset_linters]\nscope = "root"\ntype = "tools"\nfiles = ["*.sh"]\n'
                'choices = ["shellcheck"]\ndefault = { shellcheck = "pre-commit" }\n'
            ),
            "feature/assets/files/assets/{{ asset_name }}.jinja": "hello\n",
        },
    )

    def optional_shell_file(frags: list[sinks.Frag], _ctx: dict[str, object]) -> list[sinks.SinkFile]:
        return [sinks.SinkFile("optional.sh", "true\n")] if frags else []

    monkeypatch.setitem(sinks.SINKS, "test.shell", optional_shell_file)
    monkeypatch.setattr(catalog, "TEMPLATES", templates)
    catalog.layer.cache_clear()
    yield
    catalog.layer.cache_clear()


@pytest.mark.usefixtures("tool_groups")
@pytest.mark.parametrize(("lang", "formatter"), [("python", "yamlfmt"), ("ts", "prettier")])
def test_init_uses_rendered_files_and_selected_layers(tmp_path: Path, lang: str, formatter: str) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", f"{lang}:lib", "--no-setup") == 0
    current = recorded(repo)
    assert current.root["yaml_formatters"] == {formatter: "pre-commit"}
    assert "shell_linters" not in current.root
    assert not (repo / "optional.sh").exists()
    assert "json_formatters" not in current.root
    assert run("sync", str(repo), "--check") == 0


@pytest.mark.usefixtures("tool_groups")
def test_init_refuses_an_explicit_unavailable_group(tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    with pytest.raises(ValueError, match="shell_linters: no rendered file matches"):
        run("init", str(repo), "--unit", "python:lib", "--opt", "shell_linters=shellcheck", "--no-setup")
    assert not repo.exists()


@pytest.mark.usefixtures("tool_groups")
def test_refresh_adds_and_drops_groups_with_their_files(tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:lib", "--no-setup") == 0
    with pytest.raises(UsageError, match="json_formatters: no rendered file matches"):
        run("set", "json_formatters=prettier", "--repo", str(repo))
    assert run("feature", "add", "deps-update", "--repo", str(repo)) == 0
    assert recorded(repo).root["json_formatters"] == {"prettier": "pre-commit"}
    commit_all(repo, "add json file")
    assert run("feature", "remove", "deps-update", "--repo", str(repo)) == 0
    assert "json_formatters" not in recorded(repo).root


@pytest.mark.usefixtures("tool_groups")
def test_adding_a_layer_keeps_saved_answers(tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:lib", "--no-setup") == 0
    assert run("add", "ts:lib@web", "--repo", str(repo)) == 0
    assert recorded(repo).root["yaml_formatters"] == {"yamlfmt": "pre-commit"}
    commit_all(repo, "add ts")
    assert run("set", "yaml_formatters=none", "--repo", str(repo)) == 0
    assert recorded(repo).root["yaml_formatters"] == {}
    assert run("sync", str(repo), "--check") == 0


@pytest.mark.usefixtures("tool_groups")
def test_feature_options_use_the_final_rendered_paths(tmp_path: Path) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:lib", "--no-setup") == 0
    assert (
        run(
            "feature",
            "add",
            "assets",
            "--repo",
            str(repo),
            "--opt",
            "asset_linters=shellcheck:ci",
            "--opt",
            "asset_name=run.sh",
        )
        == 0
    )
    assert recorded(repo).root["asset_linters"] == {"shellcheck": "ci"}


@pytest.mark.usefixtures("tool_groups")
@pytest.mark.parametrize(
    "pairs",
    [
        ["asset_linters=shellcheck", "asset_name=run.sh"],
        ["asset_name=run.sh", "asset_linters=shellcheck"],
    ],
)
def test_set_checks_the_final_paths_regardless_of_pair_order(tmp_path: Path, pairs: list[str]) -> None:
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--unit", "python:lib", "--no-setup") == 0
    assert run("feature", "add", "assets", "--repo", str(repo)) == 0
    commit_all(repo, "add text asset")
    assert "asset_linters" not in recorded(repo).root
    assert run("set", *pairs, "--repo", str(repo)) == 0
    assert recorded(repo).root["asset_linters"] == {"shellcheck": "pre-commit"}


@pytest.mark.usefixtures("tool_groups")
def test_context_includes_sinks_and_ignores_unrelated_disk_files(tmp_path: Path) -> None:
    write(tmp_path, {"unmanaged.sh": "echo hello\n"})
    current = Manifest(unit=[Unit("tools", "python", "lib")])
    context = option_context(current, "demo", tmp_path)
    assert ".github/workflows/ci.yml" in context.files
    assert ".config/tmpl.toml" in context.files
    assert "tools/src/tools/__init__.py" in context.files
    assert "unmanaged.sh" not in context.files
    assert "lang/python" in context.layers
    assert "lang/python/kind/lib" in context.layers
    assert "basedpyright" in render(current, "demo")[".config/hk.pkl"].content


@pytest.mark.usefixtures("tool_groups")
def test_interactive_init_asks_only_unanswered_applicable_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answers = iter(["python:lib", "unknown", "", "mypy:ci"])
    prompts: list[str] = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--no-setup") == 0
    assert len(prompts) == 4
    assert "yaml formatters" in prompts[1]
    assert "yamlfmt:pre-commit" in prompts[1]
    assert prompts[1] == prompts[2]
    assert "type checkers" in prompts[3]
    assert "unknown tool" in capsys.readouterr().err
    assert recorded(repo).lang["python"]["type_checkers"] == {"mypy": "ci"}


@pytest.mark.usefixtures("tool_groups")
def test_interactive_init_respects_explicit_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["python:lib", "none"])
    prompts: list[str] = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    repo = tmp_path / "new-tool"
    assert run("init", str(repo), "--opt", "type_checkers=ty", "--no-setup") == 0
    assert len(prompts) == 2
    assert recorded(repo).root["yaml_formatters"] == {}
    assert recorded(repo).lang["python"]["type_checkers"] == {"ty": "pre-commit"}


@pytest.mark.usefixtures("tool_groups")
def test_adopt_uses_the_same_applicability_rules(tmp_path: Path) -> None:
    repo = tmp_path / "existing"
    write(repo, {"pyproject.toml": '[project]\nname = "existing"\n[build-system]\nrequires = []\n'})
    current = detect(repo).manifest
    assert current.root["yaml_formatters"] == {"yamlfmt": "pre-commit"}
    assert "shell_linters" not in current.root
    assert manifest.loads(manifest.dumps(current)).root == current.root


def test_file_filters_are_only_for_tool_options() -> None:
    with pytest.raises(ValueError, match="only supported on tools options"):
        catalog.OptionSpec(scope="root", files=["*.yml"])


def test_first_selected_layer_default_wins_and_saved_none_is_kept() -> None:
    spec = catalog.OptionSpec(
        scope="root",
        type="tools",
        choices=["yamlfmt", "prettier"],
        default={"yamlfmt": "pre-commit"},
        default_by_layer={"lang/ts": {"prettier": "pre-commit"}, "lang/python": {"yamlfmt": "ci"}},
    )
    context = catalog.OptionContext(frozenset({"ci.yml"}), frozenset({"lang/python", "lang/ts"}))
    assert catalog.resolve({"formatter": spec}, {}, None, context).stored == {
        "formatter": {"prettier": "pre-commit"},
    }
    assert catalog.resolve({"formatter": spec}, {"formatter": {}}, None, context).stored == {"formatter": {}}
