# flows/

Structured workflows for agentic coding sessions.

## Purpose

Flows define repeatable, multi-stage workflows that guide an agent through complex tasks. Each flow consists of ordered stages that build on each other to produce a well-reasoned outcome.

## Ideas Pipeline

The `ideas/` subdirectory tracks feature ideas through a simple pipeline:

```text
ideas/
├── proposed/    # New ideas awaiting review
├── approved/    # Ideas accepted for implementation
└── rejected/    # Ideas declined (with rationale)
```

### Idea File Naming

Idea files follow the naming convention `idea-NNNN.md`, where `NNNN` is a zero-padded sequential number:

```text
ideas/proposed/idea-0001.md
ideas/proposed/idea-0002.md
```

## Flow Stages

A typical flow progresses through these stages:

1. **Research** -- gather context, read relevant code, understand the problem space
2. **Vision** -- define what success looks like and the high-level approach
3. **Goals** -- break the vision into concrete, measurable objectives
4. **Plan** -- design the implementation strategy and file-level changes
5. **Execute** -- implement the plan, committing at each logical unit
6. **Verify** -- run tests, linters, and manual checks to confirm correctness
7. **Review** -- reflect on the outcome and capture lessons learned

Not every flow uses every stage. Tailor the stages to the complexity of the task.
