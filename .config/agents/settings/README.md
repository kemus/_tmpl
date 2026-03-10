# settings/

Per-harness user-local settings.

## Purpose

This directory holds settings files that are specific to an individual user's environment -- editor preferences, local overrides, machine-specific paths, and other non-shared configuration.

Each harness gets its own subdirectory:

```text
settings/
├── claude/
│   └── settings.local.json
├── cursor/
│   └── settings.json
└── ...
```

## settings/ vs configs/

- **settings/** -- user-local, often gitignored, machine-specific preferences
- **configs/** -- project-level configuration, committed to the repo and shared across contributors
