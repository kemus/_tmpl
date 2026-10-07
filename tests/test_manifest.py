from tmpl import manifest
from tmpl.manifest import Manifest, Unit


def test_round_trip() -> None:
    original = Manifest(
        version="0.1.0",
        root={"description": "Demo", "license": "MIT"},
        lang={"python": {"type_checkers": {"basedpyright": "pre-commit", "mypy": "pre-push"}}, "go": {}},
        unit=[Unit(".", "python", "cli", options={"name": "demo"}), Unit("libs/core", "python", "lib")],
    )
    text = manifest.dumps(original)
    assert manifest.loads(text) == Manifest(
        version="0.1.0",
        root=original.root,
        lang={"python": {"type_checkers": {"basedpyright": "pre-commit", "mypy": "pre-push"}}},
        unit=original.unit,
    )
    assert "[lang.go]" not in text
    assert 'type_checkers = {basedpyright = "pre-commit", mypy = "pre-push"}' in text
    assert "[[unit]]" in text


def test_versionless_manifest_loads() -> None:
    loaded = manifest.loads('[[unit]]\npath = "."\nlang = "python"\nkind = "cli"\n')
    assert loaded.version == ""
    assert loaded.langs == ["python"]
