---
title: Observability
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Observability

The project uses auditable artifacts rather than a centralized telemetry service.

## Observable state

- Dispatch JSON under `.root-architect/state/`.
- Root ledger/checkpoints.
- Worker reports and validator verdicts.
- Git branch, `HEAD`, staged diff, and narrow commits.
- Gate command exit codes and stderr/stdout.
- CI job results.
- Generated/built artifact comparisons.
- Host installation enumeration from smoke tests.

## Required recording

Root should write a progress note at each dispatch, worker verdict, reproduction, and ruling rather than only at final checkpoint. This makes interruption recoverable and prevents repeated investigation.

## Evidence labels

Reused evidence from an unchanged `HEAD` must be explicitly marked as reused. Model and effort actually applied must be recorded; if a host cannot set effort, record that limitation rather than a fictional level.

## Health indicators

A healthy run has exactly one or zero open dispatches, schema-valid state, matching generated/built artifacts, passing host-interface provenance, valid worker returns, and a passing full outcome gate before completion.
