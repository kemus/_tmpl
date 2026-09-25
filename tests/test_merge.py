import tomllib

from tmpl.merge import merge, merge_text

BASE = '[project]\nname = "demo"\nversion = "0.1.0"\n\n[tool.ruff]\nline-length = 120\n'


def test_toml_takes_template_change_to_untouched_key() -> None:
    ours = BASE.replace('version = "0.1.0"', 'version = "0.2.0"')
    theirs = BASE.replace("120", "100")
    merged = merge("pyproject.toml", BASE, ours, theirs)
    assert not merged.conflict
    data = tomllib.loads(merged.content)
    assert data["project"]["version"] == "0.2.0"
    assert data["tool"]["ruff"]["line-length"] == 100


def test_toml_key_conflict_falls_back_to_text_markers() -> None:
    merged = merge("pyproject.toml", BASE, BASE.replace("120", "88"), BASE.replace("120", "100"))
    assert merged.conflict
    assert "<<<<<<< ours" in merged.content
    assert ">>>>>>> template" in merged.content


def test_adopt_keeps_ours_and_notes_difference() -> None:
    ours = "[tool.ruff]\nline-length = 100\n"
    merged = merge("pyproject.toml", None, ours, '[tool.ruff]\nline-length = 120\nsrc = ["src"]\n')
    data = tomllib.loads(merged.content)
    assert data["tool"]["ruff"] == {"line-length": 100, "src": ["src"]}
    assert merged.notes == ["tool.ruff.line-length: kept 100 (template: 120)"]


def test_adopt_prefer_template_replaces() -> None:
    merged = merge("pyproject.toml", None, "[a]\nx = 1\n", "[a]\nx = 2\n", prefer="template")
    assert tomllib.loads(merged.content) == {"a": {"x": 2}}


def test_dev_dependencies_merge_by_requirement_name() -> None:
    ours = '[dependency-groups]\ndev = ["pytest>=8", "Ruff"]\n'
    theirs = '[dependency-groups]\ndev = ["mypy", "pytest", "ruff"]\n'
    merged = merge("pyproject.toml", None, ours, theirs)
    assert tomllib.loads(merged.content)["dependency-groups"]["dev"] == ["pytest>=8", "Ruff", "mypy"]


def test_gitignore_lineset() -> None:
    base = "# OS\n.DS_Store\n\n# Python\n__pycache__/\n"
    ours = "# OS\n.DS_Store\n\n# Python\n__pycache__/\n\n# Mine\n/scratch/\n"
    theirs = "# OS\n.DS_Store\nThumbs.db\n\n# Python\n.venv/\n"
    merged = merge(".gitignore", base, ours, theirs)
    assert merged.content == "# OS\n.DS_Store\nThumbs.db\n\n# Python\n.venv/\n\n# Mine\n/scratch/\n"


def test_editorconfig_keeps_comments_and_adds_section() -> None:
    ours = "root = true\n\n# house style\n[*]\nindent_size = 2\n"
    theirs = "root = true\n\n[*]\nindent_size = 2\ncharset = utf-8\n\n[*.py]\nindent_size = 4\n"
    merged = merge(".editorconfig", None, ours, theirs)
    assert merged.content == (
        "root = true\n\n# house style\n[*]\nindent_size = 2\ncharset = utf-8\n\n[*.py]\nindent_size = 4\n"
    )


def test_text_three_way() -> None:
    merged = merge_text("a\nb\nc\n", "A\nb\nc\n", "a\nb\nC\n")
    assert merged.content == "A\nb\nC\n"
    assert not merged.conflict


def test_text_adopt_conflicts_unless_preferred() -> None:
    assert merge("README.md", None, "mine\n", "theirs\n").conflict
    assert merge("README.md", None, "mine\n", "theirs\n", prefer="ours").content == "mine\n"
