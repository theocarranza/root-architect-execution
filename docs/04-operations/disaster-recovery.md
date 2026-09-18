---
title: Disaster Recovery
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Disaster Recovery

## Recovery model

The protocol is designed for interruption rather than high-availability service failover. Recovery depends on Git, the ledger, structured worker artifacts, and dispatch state.

## Session interruption

1. Inspect branch, `HEAD`, dirty paths, and owner-owned paths.
2. Read the governing plan and latest ledger/handoff.
3. Run `dispatch_state.py verify` and `active`.
4. Reconcile any open dispatch with recorded worker artifacts before closing/retrying it.
5. Re-run capability/preflight gates in the new host process.
6. Reuse unchanged-HEAD evidence only when explicitly recorded as reused.

## Corrupt dispatch state

Corrupt state is a safety event. Guards fail closed. Use `dispatch_state.py verify` to identify records, reconstruct status from the ledger/brief/worker artifacts, then repair or deliberately remove the bad record. Never delete state merely to unblock a write without reconciling the run.

## Lost generated/built artifacts

Regenerate them from `roles/`, `hosts/`, references, schemas, scripts, and adapter sources. `dist/` is recoverable and not authoritative.

## Recovery objectives

- **RPO:** latest recorded dispatch/verdict/ruling in the ledger and structured artifacts.
- **RTO:** time required to verify state, rebuild host artifacts if necessary, rerun preflight/capability gates, and resume the bounded task.
