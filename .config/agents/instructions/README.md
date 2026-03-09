# instructions/

Instruction files for coding agent harnesses.

## Purpose

This directory holds instruction files that provide context and conventions to coding agents. Instructions are parallel across harnesses -- the same guidance is available regardless of which harness is active.

## Convention

Instructions follow the naming pattern `AGENTS.<PATH>.md`, where `<PATH>` maps to a directory in the project:

```text
instructions/
├── AGENTS.md              # Root-level instructions (applies to entire project)
├── AGENTS.src.md          # Instructions for src/
├── AGENTS.src.api.md      # Instructions for src/api/
└── ...
```

## Symlinking

A setup script symlinks instruction files to the paths each harness expects. For example, `AGENTS.md` might be symlinked to the repo root, while `AGENTS.src.md` is symlinked into `src/`.
