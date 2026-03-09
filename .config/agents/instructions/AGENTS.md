# _tmpl

Base project template (stage 0) for the copier template system.

## Structure

- `copier.yml` — all questions and computed variables live here
- `extensions.py` — Jinja extensions (cwd_name, git_user_name, git_user_email)
- `post-task.sh` — symlinks, mise, license, then invokes child subtemplate
- `template/` — shared output files (language-agnostic)
- `children/` — submodules for language-specific subtemplates (stage 1)

## Multi-stage architecture

1. Stage 0 (this repo): shared files + questions, invokes stage 1 child
2. Stage 1 (children/): language-specific files, may invoke stage 2
3. Stage 2: dialect-specific files (e.g. shell -> bash/posix/zsh)

Variables flow down via `--data-file` pointing to base answers.
