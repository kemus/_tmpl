#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_SRC="$1"
LANGUAGE="$2"
USE_CLAUDE="$3"
LICENSE="$4"
SHELL_TYPE="${5:-}"
PYTHON_VERSION="${6:-}"
SHELL_TEST_FRAMEWORK="${7:-}"
TS_TEST_FRAMEWORK="${8:-}"
AUTHOR="$9"
AUTHOR_EMAIL="${10}"
PROJECT_NAME="${11}"
PROJECT_NAME_KEBAB="${12}"
PROJECT_SLUG="${13}"
PROJECT_DESCRIPTION="${14}"
INDENT_STYLE="${15}"
MAX_LINE_LENGTH="${16}"

DEST="$(pwd)"

# Write base answers for child templates to consume via --data-file
mkdir -p "$DEST/.config/copier"
cat > "$DEST/.config/copier/base-answers.yml" << EOF
language: $LANGUAGE
use_claude: $USE_CLAUDE
license: $LICENSE
shell_type: $SHELL_TYPE
python_version: $PYTHON_VERSION
shell_test_framework: $SHELL_TEST_FRAMEWORK
ts_test_framework: $TS_TEST_FRAMEWORK
author: $AUTHOR
author_email: $AUTHOR_EMAIL
project_name: $PROJECT_NAME
project_name_kebab: $PROJECT_NAME_KEBAB
project_slug: $PROJECT_SLUG
project_description: $PROJECT_DESCRIPTION
indent_style: '$INDENT_STYLE'
max_line_length: $MAX_LINE_LENGTH
EOF

# Create empty directories (copier excludes .gitkeep)
mkdir -p "$DEST/.config/agents/flows/ideas/proposed"
mkdir -p "$DEST/.config/agents/flows/ideas/approved"
mkdir -p "$DEST/.config/agents/flows/ideas/rejected"

if [[ "$USE_CLAUDE" == "true" || "$USE_CLAUDE" == "True" ]]; then
  # Create history/claude/ (not in template due to .gitkeep exclusion)
  mkdir -p "$DEST/.config/agents/history/claude"

  # harness/claude/ — the entry point .claude will symlink to
  mkdir -p "$DEST/.config/agents/harness/claude"
  ln -sf ../../flows/claude      "$DEST/.config/agents/harness/claude/flows"
  ln -sf ../../instructions/claude "$DEST/.config/agents/harness/claude/instructions"
  ln -sf ../../plans/claude       "$DEST/.config/agents/harness/claude/plans"
  ln -sf ../README.md             "$DEST/.config/agents/harness/claude/README.md"
  ln -sf ../../settings/claude.local.json "$DEST/.config/agents/harness/claude/settings.local.json"

  # instructions/claude/ — harness adapter
  mkdir -p "$DEST/.config/agents/instructions/claude"
  ln -sf ../AGENTS.md  "$DEST/.config/agents/instructions/claude/CLAUDE.md"
  ln -sf ../README.md  "$DEST/.config/agents/instructions/claude/README.md"

  # flows/claude/ — harness adapter
  mkdir -p "$DEST/.config/agents/flows/claude"
  ln -sf ../ideas      "$DEST/.config/agents/flows/claude/ideas"
  ln -sf ../README.md  "$DEST/.config/agents/flows/claude/README.md"

  # plans/claude/ — add README and history symlinks
  ln -sf ../README.md         "$DEST/.config/agents/plans/claude/README.md"
  ln -sf ../../history/claude "$DEST/.config/agents/plans/claude/history"

  # Root-level symlinks
  ln -sf .config/agents/harness/claude "$DEST/.claude"
  ln -sf .config/agents/instructions/AGENTS.md "$DEST/CLAUDE.md"
fi

# Mise: trust, pin tool versions, generate lockfile
mise trust --quiet
# Parse tool names from the generated [tools] section and pin each one
grep -E '^\s*"?[a-zA-Z]' "$DEST/.config/mise/config.toml" \
  | sed 's/\s*=.*//; s/^[[:space:]]*//; s/"//g' \
  | while read -r tool; do
      mise use "${tool}@latest" --pin
    done
mise lock

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
