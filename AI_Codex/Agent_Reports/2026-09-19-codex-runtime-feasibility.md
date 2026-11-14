---
type: agent-report
area: codex-runtime-feasibility
created: 2026-09-20
status: blocked
---

# Codex runtime feasibility

## Decision

**Blocked: no transport is selected.** Native-session integration is not
supported because this task has no live evidence for correlated root,
orchestrator, and worker identities; exact return capture; status, follow-up,
and cancellation controls; or enforced worker boundaries. An App Server launch
is also not selected: this task did not run one and therefore cannot claim its
controls for a new governed session.

The immediate blockers are stricter: no verified Codex transport can enforce
the requested time or token cap. The acceptance runner refuses `--require-live`
rather than launching a model with an advisory or ignored limit.

## Offline evidence

The runner records only local executable discovery and hashes of repository
Codex declarations. It does not read user configuration, account data, plugin
state, prompts, transcripts, or tokens. It does not execute the Codex binary,
start a session, invoke a model, install anything, or alter configuration.
`tests/fixtures/runtime/codex-probe.json` is an intentionally blocked record:
all identities are `unknown`, events are `not_run`, and the event list is empty.

## Commands and results

Red, before implementation:

```
python3 -m unittest tests.test_acceptance_runtime -v
```

Result: failed because `scripts/acceptance_runtime.py` and the fixture did not
exist.

Green, after implementation:

```
python3 -m unittest tests.test_acceptance_runtime -v
python3 scripts/acceptance_runtime.py --host codex --scenario capability-probe --require-live --max-seconds 300 --max-tokens 12000
```

Expected result: tests pass; the second command exits 2 and prints a structured
`blocked` / `not_run` record. It makes no model call.

## Evidence limits and next control evidence

This result is not a live-host pass. A future bounded trial must first prove,
on the selected transport, enforceable time and token limits, then capture the
exact identity, event, final-message, status, follow-up, cancellation, worker
delegation denial, and controller-storage boundary evidence required by Task 3.
