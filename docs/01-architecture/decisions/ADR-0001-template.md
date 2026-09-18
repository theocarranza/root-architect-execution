---
title: ADR-0001 Documentation Template
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# ADR-0001: Host adapters are generated from shared role declarations

## Status

Accepted as an architectural pattern reflected by the repository.

## Context

The protocol must support multiple agent hosts without duplicating role semantics. Host runtimes differ in agent-file format, model naming, reasoning controls, hook capabilities, plugin layout, and installation mechanics. Hand-maintaining one role definition per host would create silent behavioral drift.

## Decision

Keep role intent vendor-neutral in `roles/*.json`, host capabilities/mappings in `hosts/*.json`, and role prose in `references/agents/*.md`. Generate host-specific agent files with `scripts/render_agents.py`, then package installable adapters with `scripts/build_adapter.py`.

Generated agent files and `dist/` are derived artifacts and are never authoritative hand-edit targets.

Host-specific interface claims must include provenance and pass `scripts/validate_interfaces.py`. If a host cannot enforce a capability, the generated representation must disclose the limitation rather than imply equivalence.

## Consequences

### Positive

- One source of truth for role semantics.
- Reproducible host artifacts.
- Explicit capability degradation.
- CI can detect stale generated/built output byte-for-byte.
- New hosts have a defined integration path.

### Trade-offs

- Development requires regeneration/rebuild after declaration changes.
- What is reviewed in source is not literally the final installed artifact, so byte-comparison and smoke-install gates are required.
- Some guarantees remain host-specific; notably Claude can use identity-aware write guards while Codex currently relies on instruction/review for that boundary.

## Validation

A host adapter is acceptable only when role validation, rendering checks, bundle checks, interface provenance validation, host-specific manifest/install checks, and the test suite pass.
