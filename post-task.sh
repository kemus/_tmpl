#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_SRC="$1"
DEST="$(pwd)"
ANSWERS="$DEST/.config/copier/base-answers.yml"

# Read variables from answers
LANGUAGE=$(grep '^language:' "$ANSWERS" | awk '{print $2}')
USE_CLAUDE=$(grep '^use_claude:' "$ANSWERS" | awk '{print $2}')
LICENSE=$(grep '^license:' "$ANSWERS" | awk '{print $2}')
AUTHOR=$(grep '^author:' "$ANSWERS" | sed "s/^author: //")
AUTHOR_EMAIL=$(grep '^author_email:' "$ANSWERS" | sed "s/^author_email: //")
PROJECT_NAME=$(grep '^project_name:' "$ANSWERS" | sed "s/^project_name: //")

# Symlinks
ln -sf .agents/instructions/AGENTS.md AGENTS.md
if [[ "$USE_CLAUDE" == "true" ]]; then
  ln -sf .agents/claude .claude
  ln -sf .agents/instructions/AGENTS.md CLAUDE.md
fi

# Mise + license
mise trust --quiet
mise exec go:github.com/Shresht7/gh-license -- \
  gh-license create "$LICENSE" \
  --author "$AUTHOR <$AUTHOR_EMAIL>" \
  --project "$PROJECT_NAME"

# Ensure copier
uv tool install copier --with copier-template-extensions 2>/dev/null || true

# Invoke child: children/<language>/
CHILD="$TEMPLATE_SRC/children/$LANGUAGE"
CHILD_ANSWERS="$DEST/.config/copier/${LANGUAGE}-answers.yml"

if [[ -d "$CHILD" ]]; then
  if [[ -f "$CHILD_ANSWERS" ]]; then
    copier update --trust --defaults --answers-file "$CHILD_ANSWERS" "$DEST"
  else
    copier copy --trust --defaults \
      --answers-file "$CHILD_ANSWERS" \
      --data-file "$ANSWERS" \
      "$CHILD" "$DEST"
  fi
fi
