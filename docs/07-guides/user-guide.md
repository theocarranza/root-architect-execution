---
title: User Guide
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# User Guide

## Claude Code quick start

Build/install the Claude adapter, restart the host, and ensure the nesting prerequisite is set before launch.

Launch root as the main-thread agent rather than trying to convert an ordinary session into root mode:

```sh
CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2 \
claude --agent root-architect
```

Root should perform its startup/preflight and capability gates before dispatching work.

## What a normal run looks like

You give root a task governed by an implementation plan. Root creates a bounded brief, opens durable dispatch state, delegates implementation, validates the structured return, obtains independent spec and quality verdicts, closes the dispatch, records a checkpoint, and creates a narrow commit. It repeats for dependent tasks and runs the full outcome gate before declaring the outcome complete.

## What the owner should expect to be asked

Root should only escalate unresolved architectural conflicts, overlap with owner-owned dirty work, credentials/destructive work outside the brief, three failed attempts, a failing prior-outcome gate, or quota/resource conditions.

## Codex

Set `RAE_HOST=codex`, point `PLUGIN_ROOT` at the installed plugin, validate roles for Codex, and run the bundled installer to materialize `.codex/agents`. Be aware that root-vs-worker write isolation is not hook-enforced to the same degree as Claude because the necessary worker identity is not documented in the Codex PreToolUse payload.
