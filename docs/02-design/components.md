---
title: Component Design
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Component Design

## Declaration layer

`roles/` defines what agents are allowed to be. `hosts/` defines what a runtime can express. `references/agents/` defines role behavior in prose. `schemas/` makes those declarations and runtime messages machine-checkable.

## Generation layer

`render_agents.py` combines role declarations, host capabilities, and referenced role prose into host-native agent definitions. Claude Code receives Markdown/frontmatter-style agent files; Codex receives TOML agent definitions. Cursor is maintained as a reference/generated path pending complete sourcing.

## Packaging layer

`build_adapter.py` assembles source-controlled adapter mechanics and generated artifacts into `dist/<host>`. The build check compares a fresh build byte-for-byte with committed distribution output.

## Runtime-control layer

`root_preflight.py` protects the main-thread/root boundary before run initialization. `dispatch_state.py` maintains the single active dispatch. Guard hooks re-read that durable state on each relevant tool call.

## Return-validation layer

`check_return.py` extracts exactly one JSON result (fenced or raw JSON), validates it against the role's schema, then applies invariants that JSON Schema alone cannot express.

## Host enforcement

Claude Code's PreToolUse event can distinguish namespaced agent identity and therefore enforce root-vs-worker mutation restrictions. The guards recognize both plugin namespaced and bare/project-local forms. Codex lacks the documented worker identity needed for equivalent hook enforcement, so the adapter must not claim that guarantee.

## CI layer

The GitHub Actions outcome gate tests Python versions with real TOML parsing, rejects execution as root where permission-bit tests would otherwise skip, validates generated artifacts/bundles/interfaces, runs the unit suite, validates the Claude plugin manifest, and smoke-installs the built bundle.
