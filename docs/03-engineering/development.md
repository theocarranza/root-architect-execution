---
title: Development Guide
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Development Guide

## Prerequisites

- Git
- Python 3.11+ recommended for full TOML-backed verification
- Claude Code CLI when validating/smoke-testing the Claude adapter
- A clone of the repository

## Repository workflow

Edit source declarations and mechanics, not generated output.

```text
role behavior       -> references/agents/*.md
role capabilities   -> roles/*.json
host capabilities   -> hosts/*.json
host mechanics      -> adapters/<host>/*
schemas/runtime     -> schemas/*, scripts/*
generated agents    -> regenerate; do not hand-edit
dist bundles        -> rebuild; do not hand-edit
```

## Changing a role

```sh
$EDITOR roles/impl-executor.json
python3 scripts/render_agents.py --host claude-code
python3 scripts/render_agents.py --host codex
python3 scripts/validate_roles.py
```

Rebuild affected host bundles after generation.

## Adding/changing a host

Create or update `hosts/<host>.json`, source every capability claim including unsupported capabilities, add/update `adapters/<host>/agent-interface.json`, render the host agents, validate interfaces, and add host-specific packaging/install tests. Unsupported capabilities must become explicit disclosures.

## Before committing

Run the full local outcome gate described in `testing.md`. A green unit suite alone is insufficient because generated artifacts and installable bundles can be stale or host-invalid while tests remain green.
