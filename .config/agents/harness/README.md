# harness/

Base configuration for coding agent harnesses.

## Purpose

This directory holds harness-specific configuration that each coding agent needs to function -- plan files, prompt caches, session state, and other runtime artifacts.

Each harness gets its own subdirectory:

```text
harness/
├── claude/
│   └── plans/
├── cursor/
└── ...
```

## Dynamic Symlinking

Harnesses often expect their configuration at specific paths in the repo root (e.g., `.claude/`, `.cursor/`). A setup script can dynamically symlink from this structure to the harness-expected paths, keeping the repo root clean while centralizing agent configuration here.
