#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_SRC="$1"
LANGUAGE="$2"
USE_CLAUDE="$3"
LICENSE="$4"
SHELL_TYPE="${5:-}"
AUTHOR="$6"
AUTHOR_EMAIL="$7"
PROJECT_NAME="$8"
PROJECT_NAME_KEBAB="$9"
PROJECT_SLUG="${10}"
PROJECT_DESCRIPTION="${11}"
INDENT_STYLE="${12}"
MAX_LINE_LENGTH="${13}"

DEST="$(pwd)"

# Write base answers for child templates to consume via --data-file
mkdir -p "$DEST/.config/copier"
cat > "$DEST/.config/copier/base-answers.yml" << EOF
language: $LANGUAGE
use_claude: $USE_CLAUDE
license: $LICENSE
shell_type: $SHELL_TYPE
author: $AUTHOR
author_email: $AUTHOR_EMAIL
project_name: $PROJECT_NAME
project_name_kebab: $PROJECT_NAME_KEBAB
project_slug: $PROJECT_SLUG
project_description: $PROJECT_DESCRIPTION
indent_style: '$INDENT_STYLE'
max_line_length: $MAX_LINE_LENGTH
EOF

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
CHILD_ANSWERS_REL=".config/copier/${LANGUAGE}-answers.yml"
CHILD_ANSWERS="$DEST/$CHILD_ANSWERS_REL"
ANSWERS="$DEST/.config/copier/base-answers.yml"

if [[ -d "$CHILD" ]]; then
  if [[ -f "$CHILD_ANSWERS" ]]; then
    copier update --trust --defaults --answers-file "$CHILD_ANSWERS_REL" "$DEST"
  else
    copier copy --trust --defaults \
      --answers-file "$CHILD_ANSWERS_REL" \
      --data-file "$ANSWERS" \
      "$CHILD" "$DEST"
  fi
fi
