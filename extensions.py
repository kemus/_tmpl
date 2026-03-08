import subprocess
from pathlib import Path

from jinja2.ext import Extension


def cwd_name() -> str:
    return Path.cwd().name


def git_user_name(default: str = "") -> str:
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or default
    except (subprocess.CalledProcessError, FileNotFoundError):
        return default


def git_user_email(default: str = "") -> str:
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or default
    except (subprocess.CalledProcessError, FileNotFoundError):
        return default


class GitExtension(Extension):
    def __init__(self, environment):
        super().__init__(environment)
        environment.globals["cwd_name"] = cwd_name
        environment.globals["git_user_name"] = git_user_name
        environment.globals["git_user_email"] = git_user_email
