---
title: Roadmap
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Roadmap

## Current state — 2026-09-17

The repository handoff reports:

- Orchestrated worker isolation ADR work complete.
- Host-adapter work complete for the implemented Claude/Codex path, with Cursor still blocked on sourcing/re-verification.
- 216 tests reported across Python 3.10–3.13 in the handoff.
- Ten-command contributor outcome gate.
- Byte-gated Claude Code and Codex bundles.
- Root half of the first end-to-end run observed.

## Immediate milestone

Finish a live end-to-end run and observe:

1. Orchestrator dispatching a worker.
2. Worker report returning through the envelope/return gate.
3. Root and worker PreToolUse guards firing during a live run.
4. Root final narrow commit.

## Next host milestone

Resolve Cursor capability sourcing before implementing/claiming a production adapter. The project's design explicitly prefers an `unsourced`/blocked capability over inference.

## Documentation/operability milestone

Keep this `docs/` interface synchronized with role/schema/host changes and consider adding a documentation drift check to the outcome gate.
