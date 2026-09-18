---
title: Dependencies
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Dependencies

## Runtime

| Dependency | Purpose |
|---|---|
| Python 3 | Validation, generation, packaging, state, guards, tests. |
| Git | Root-owned source/history inspection and narrow commits. |
| Agent host | Executes root/orchestrator/workers. |
| Filesystem | Durable dispatch state, ledgers, generated artifacts, bundles. |
| JSON | Primary machine contract representation. |

## Python standard-library considerations

Python 3.11+ is preferred because `tomllib` is available for Codex TOML validation. On older Python versions the repository may use a fallback such as `tomli` when installed; parser-backed checks must not be assumed if no parser is present.

## Host-specific

### Claude Code

Used for plugin installation, agent execution, PreToolUse guards, manifest validation, and smoke installation. Hook registration is read at session start, so guard changes require a restart.

### Codex

Uses a built plugin bundle plus explicit `install.py` bootstrap to materialize custom agent TOMLs. Its documented PreToolUse information does not currently provide the worker identity used by Claude's write guard.

## CI tooling

GitHub Actions uses `actions/checkout`, `actions/setup-python`, and `actions/setup-node`; Node is used to install the Claude Code CLI for plugin validation/smoke installation.
