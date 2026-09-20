---
type: adr
area: orchestration
tags: [adr, runtime, admission, evidence, security]
created: 2026-09-20
status: accepted-in-progress
---

# 0004 — Runtime evidence and admission

## Status

Accepted in progress on 2026-09-20. This preserves ADR 0003's topology and historical record, but supersedes its disproven claim that version-1 preflight, queue, and mailbox files enforce a governed run.

The 2026-09-19 audit and adversarial review found that those independent files can record false success. Their dated observations remain historical evidence and are not rewritten.

## Context

ADR 0003 correctly establishes root to orchestrator to worker routing and preserves the orchestrator's judgment. The legacy implementation does not establish all of those boundaries: an empty Codex tool set can pass preflight; a truthy, mismatched preflight file can be reused; `dispatch_state.py open` can bypass admission; queues only detect two active tasks later; a filename can stand in for an invalid envelope; a report can be reused for another task; and a worker can route directly to root.

A hash proves matching bytes, not who wrote them or which task they answer. Files reachable by the same operating-system identity cannot therefore be authoritative admission or result evidence.

## Decision

Use one controller-owned transactional runtime record for runs, admission, tasks, immutable attempts, captured envelopes, events, decisions, and workspace reservations. Markdown envelopes and JSON state/queue snapshots remain readable exports only; they cannot admit, dispatch, or complete work.

Admission requires explicit host, run, controller session, installed-catalog digest, effective-configuration digest, and capability evidence. `passed` is a literal boolean. Missing, stale, malformed, mismatched, unavailable, or unknown required evidence rejects or blocks the run. Every entry point, including compatibility commands and resume, uses this boundary.

Capture each result as raw bytes before validation and bind it to exactly one run, task, and immutable attempt. Keep business author, physical capturer, route, kind, reply relationship, content hash, and provider correlation distinct. Reusing a role, filename, hash, or report cannot satisfy a new task.

Valid routes are root-to-orchestrator task/answer, orchestrator-to-root question/outcome, orchestrator-to-worker task/answer, and worker-to-orchestrator report/question. Controller lifecycle/failure records go to the responsible parent. Workers never send directly to root.

Only one attempt may reserve a workspace. A timeout requests cancellation but does not prove a stop; the reservation remains held until stopping is confirmed or the replacement is isolated.

Required execution controls are not policy preferences. The selected host must prove required dispatch availability, worker tool/delegation denial, and controller evidence/control protection. If it cannot, its governed runtime is blocked. Templates may be `templates_only`; that is not runtime acceptance.

## Scope of the claim

This governs sessions launched through the governed runtime. An ordinary root chat outside that launcher is outside this enforcement claim. Documentation, unit tests, bundle generation, installation, and live host trials are separate evidence types.

## Consequences

Tasks 2 through 7 add capability facts, version-2 records, the controller store/service, common admission, and captured-envelope validation. The new regression suite intentionally fails against legacy code and turns green only as those later tasks close its paths.

ADR 0003 remains authoritative for the topology, the orchestrator as an agent, and raw worker text. Its version-1 enforcement claims are superseded here.

## Evidence

- `AI_Codex/Agent_Reports/2026-09-19-codex-adapter-runtime-audit.md`
- `AI_Codex/Agent_Reports/2026-09-19-codex-runtime-audit-adversarial-review.md`
- `docs/superpowers/plans/2026-09-19-codex-and-shared-runtime-remediation.md`
- `tests/test_runtime_regressions.py` (intentionally red before later runtime repairs)
