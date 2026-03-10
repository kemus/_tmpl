# Agents

Harness-agnostic configuration for coding agents, organized by concern and symlinked into each harness's expected paths.

## Structure

- `settings/` — Settings files (per-harness config like `claude.local.json`)
- `flows/` — Workflows and staged pipelines (ideas, etc.)
- `harness/` — Per-harness directories assembled from symlinks into the above
- `history/` — Archived plan files from past sessions
- `instructions/` — System prompts and instruction files (`AGENTS.md`, `CLAUDE.md`, etc.)
- `plans/` — Ephemeral plan files generated during agent sessions
