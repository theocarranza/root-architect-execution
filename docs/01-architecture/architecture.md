---
title: Architecture
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Architecture

## Architectural style

The repository is a contract-driven, host-adapted orchestration system. Its architecture separates five concerns: authority, execution, validation, durable state, and packaging.

## Major components

| Component | Responsibility |
|---|---|
| `SKILL.md` | Canonical execution protocol: authority, gates, loop, routing, stop conditions. |
| `roles/*.json` | Vendor-neutral role capabilities, model tier, effort, tools, mutation class. |
| `hosts/*.json` | Host capability matrix and evidence/provenance. |
| `references/agents/*.md` | Single-source role prose. |
| `schemas/*.json` | Machine contracts for roles, hosts, briefs, reports, verdicts, and state. |
| `scripts/render_agents.py` | Materializes role+host declarations into host agent files. |
| `scripts/build_adapter.py` | Builds byte-gated installable host bundles. |
| `scripts/validate_roles.py` | Capability/declaration/generated-output gate. |
| `scripts/validate_interfaces.py` | Verifies host-interface claims are sourced and aligned. |
| `scripts/dispatch_state.py` | Opens, closes, inspects, and verifies durable dispatch state. |
| `scripts/check_return.py` | Validates worker returns plus cross-field invariants. |
| guard hooks | Enforce root write boundaries and worker Git/shell/edit boundaries where host identity is available. |
| `scripts/root_preflight.py` | Records/judges root startup capability before queue initialization. |
| `scripts/job_queue.py` / mailbox machinery | Coordinates run/task state and handoff artifacts. |
| `dist/<host>/` | Built installation artifacts; never hand-edited. |
| CI outcome gate | Runs deterministic, generation, bundle, interface, manifest, and install checks. |

## Runtime state machine

```text
START
  |
  v
ROOT PREFLIGHT ----fail----> BLOCKED
  |
 pass
  v
CAPABILITY GATE ---fail----> BLOCKED
  |
  v
WRITE BRIEF
  |
  v
OPEN DISPATCH -----invalid/concurrent----> BLOCKED
  |
  v
IMPLEMENTER
  |
  v
RETURN GATE -------malformed----> one corrective retry ---> STOP if still bad
  |
 DONE with RED/GREEN
  v
SPEC VALIDATOR ----FAIL----> same implementer / attempt accounting
  |
 PASS
  v
QUALITY VALIDATOR -FAIL----> same implementer / attempt accounting
  |
 PASS
  v
CLOSE DISPATCH
  |
  v
CHECKPOINT + NARROW COMMIT
  |
  +---- more tasks ---> WRITE BRIEF
  |
  v
FULL OUTCOME GATE --fail----> BLOCKED / remediate
  |
 pass
  v
COMPLETE
```

## Key invariants

1. Root cannot legitimately replace a failed worker by editing the delegated product paths.
2. Workers do not own Git history.
3. Spec and quality approval are independent fresh contexts.
4. Worker output is mechanically validated before root treats it as evidence.
5. Durable state is the source of active-dispatch truth.
6. Generated artifacts must equal what declarations would regenerate.
7. Host guarantees are only as strong as sourced host capabilities.
