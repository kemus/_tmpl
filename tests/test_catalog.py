"""Option specs: the `tools` type and migration from the options it replaces."""

import pytest

from tmpl import catalog

SPEC = catalog.OptionSpec(
    scope="lang",
    type="tools",
    choices=["basedpyright", "ty", "mypy"],
    replaces={"fast": "pre-commit", "thorough": "pre-push"},
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("mypy:ci, ty", {"ty": "pre-commit", "mypy": "ci"}),
        ("none", {}),
        ("", {}),
        ({"mypy": "pre-push", "basedpyright": "pre-commit"}, {"basedpyright": "pre-commit", "mypy": "pre-push"}),
    ],
)
def test_tools_option_takes_text_or_a_table(value: object, expected: dict[str, str]) -> None:
    # `repr` shows the order: choices order, whatever order the tools came in.
    assert repr(SPEC.coerce("checkers", value)) == repr(expected)


@pytest.mark.parametrize(
    ("value", "error"),
    [("pyright", "unknown tool 'pyright'"), ("ty:nightly", "expected a stage"), (3, "expected a table")],
)
def test_tools_option_refuses_unknown_tools_and_stages(value: object, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        SPEC.coerce("checkers", value)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({"fast": "ty", "thorough": "mypy"}, {"ty": "pre-commit", "mypy": "pre-push"}),
        ({"fast": "mypy", "thorough": "mypy"}, {"mypy": "pre-commit"}),
        ({"fast": "none", "thorough": "none"}, {}),
        ({"thorough": "mypy"}, {"mypy": "pre-push"}),
    ],
)
def test_migrate_builds_tools_from_the_options_they_replace(given: dict[str, object], expected: object) -> None:
    assert catalog.migrate({"checkers": SPEC}, given) == {**given, "checkers": expected}


def test_migrate_keeps_a_stored_value_and_skips_absent_options() -> None:
    assert catalog.migrate({"checkers": SPEC}, {"checkers": {}, "fast": "ty"}) == {"checkers": {}, "fast": "ty"}
    assert catalog.migrate({"checkers": SPEC}, {}) == {}
