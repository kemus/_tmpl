from tmpl import manifest
from tmpl.manifest import Manifest, Unit

# Stamps from the actual 0.8.1 and 0.9.0 consumers for this released manifest.
CANONICAL_STAMP = "sha256:1938bf7d5e562c6a8a5585bde18ce8ec36124cb628149cf5dd70712aac2dea48"
INLINE_STAMP = "sha256:8ca4f800446610a5392a60db327c98a2ccea20b8294d20c3895ee2bcd9c6bbee"


def released_manifest() -> Manifest:
    return Manifest(
        version="0.9.0",
        applied=INLINE_STAMP,
        root={
            "description": "",
            "author": "cross-release-check",
            "license": "MIT",
            "indent": "2",
            "max_line_length": 120,
            "sync_check": True,
        },
        lang={"python": {"type_checkers": {"basedpyright": "pre-commit", "mypy": "pre-push"}}},
        unit=[Unit(".", "python", "lib")],
    )


def test_digest_uses_the_representation_understood_by_older_releases() -> None:
    current = released_manifest()
    assert manifest.digest(current) == CANONICAL_STAMP
    assert "type_checkers = {" in manifest.dumps(current)
    assert manifest.matches_digest(current, INLINE_STAMP)
    assert manifest.matches_digest(current, CANONICAL_STAMP)
    manifest.stamp(current)
    assert current.applied == CANONICAL_STAMP


def test_legacy_digest_recognition_still_detects_edits() -> None:
    current = released_manifest()
    current.root["description"] = "hand edited"
    assert not manifest.matches_digest(current, INLINE_STAMP)
    assert not manifest.matches_digest(current, CANONICAL_STAMP)


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
