---
title: Security Model
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Security Model

The project's primary security concern is execution authority: which agent may mutate which resources, and what evidence is required before authority advances.

## Least authority by role

- Root: plan, Git, ledger, dispatch, gates; must not write delegated product paths.
- Implementer: only brief-scoped writes; no Git mutation.
- Spec validator: read-only and no shell.
- Quality validator: read plus controlled command execution; no edits.
- Workers do not communicate directly with the owner or hand off to one another.

## Runtime enforcement

Claude Code PreToolUse guards enforce root write restrictions and worker Git/edit/shell restrictions using agent identity. Both namespaced plugin identities and bare project-local identities are recognized.

State errors fail closed: if an open-dispatch record cannot be trusted, protected root writes are denied.

## Supply-chain integrity

Generated agents and built bundles are checked against source. Host interface claims require provenance. Claude plugin manifests are validated against the built bundle, and smoke installation asks the actual host to enumerate installed roles/skill/hooks.

## Destructive operations

Push, release, tag, merge to `main`, force Git, destructive deletion, and similar owner-impacting operations require explicit owner approval according to the protocol.
