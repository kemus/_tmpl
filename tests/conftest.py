import subprocess
from pathlib import Path

import pytest

from tmpl.proc import executable


@pytest.fixture(autouse=True)
def isolated_git(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests away from the user's git config: identity and default branch come from a scratch file."""
    config = tmp_path_factory.mktemp("git") / "config"
    config.write_text("[user]\n\tname = Test User\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [executable("git"), "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def write(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def commit_all(repo: Path, message: str = "commit") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
