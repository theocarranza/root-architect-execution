---
title: System Context
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# System Context

## Context

The system is a repository-distributed execution protocol installed into an agent host. It does not run as a conventional long-lived server. Its runtime consists of a root agent session, nested delegated agents, local Python gate/state scripts, Git, host hook events, and filesystem artifacts.

```text
+------------------+
|   Human Owner    |
+--------+---------+
         |
         | goals / approvals / exceptions
         v
+------------------------------+
| Root Architect (main thread) |
| plan + Git + ledger + gates  |
+----+--------------------+----+
     |                    |
     | structured briefs  | Git/checkpoints
     v                    v
+------------+       +------------------+
|Orchestrator|       | Project Checkout |
+-----+------+       | + .root-architect|
      |              +------------------+
      | dispatch
      v
+------------------+     +------------------+     +-------------------+
| impl-executor    | --> | spec-validator   | --> | quality-validator |
| bounded writes   |     | read-only        |     | read + run        |
+------------------+     +------------------+     +-------------------+
      ^                         ^                         ^
      |                         |                         |
      +-------------------------+-------------------------+
                     host agent runtime

Declarations/build path:
roles/*.json + hosts/*.json + references/agents/*.md
                    |
                    v
          scripts/render_agents.py
                    |
                    v
        adapters/<host>/agents/*
                    |
                    v
          scripts/build_adapter.py
                    |
                    v
              dist/<host>/
```

## External dependencies

The protocol relies on the selected agent host, Python 3, Git, filesystem permissions, JSON/TOML parsing, and host-specific plugin/agent mechanics. Claude Code additionally provides identity-aware PreToolUse hooks used by the runtime guards; Codex currently cannot provide the same documented worker identity guarantee, so that boundary is review/instruction based there.
