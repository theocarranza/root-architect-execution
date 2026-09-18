---
title: Data Model
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Data Model

The project has no application database. Its persistent model is filesystem- and Git-based.

## Core entities

### Role declaration

Stored under `roles/*.json`. Conceptually contains role identity, vendor-neutral model tier, reasoning/effort, tool grants, mutation class, escalation path, and host-relevant requirements.

### Host declaration

Stored under `hosts/*.json`. Describes how a host maps model tiers/effort and which agent/hook capabilities it can express. Claims carry verification/provenance so unsupported or inherited knowledge can be surfaced.

### Brief

Schema: `schemas/brief.schema.json`.

Core fields documented by the contract include:

```json
{
  "task": "Task identifier and description",
  "attempt": 1,
  "max_attempts": 3,
  "role": "implementer",
  "model": "explicit model/tier mapping",
  "effort": "low",
  "read_paths": [],
  "write_paths": [],
  "interfaces": [],
  "acceptance": [{"command": "...", "expect": "..."}],
  "constraints": [],
  "owner_owned_paths": [],
  "expected_result": "..."
}
```

From attempt 2 onward, escalation must be justified by recorded evidence.

### Dispatch state

Stored under:

```text
<workspace>/.root-architect/state/dispatch-<run_id>.json
```

An `open` dispatch is the only active signal. The state binds a run identifier to the validated brief and lifecycle metadata. `dispatch_state.py` refuses a second concurrent open dispatch and `verify` scans current and archived records for corruption.

### Implementer report

Schema: `schemas/implementer-report.schema.json`. A `DONE` result must contain observed RED and GREEN evidence. Task/attempt/role identity must match the dispatch.

### Validator verdict

Schema: `schemas/validator-verdict.schema.json`. `PASS` corresponds to no findings. Spec validation cannot report rerun commands because that role has no shell. Quality findings require concrete failure scenarios.

### Checkpoint / ledger

Human-readable rather than JSON-schema controlled. Records progress, decisions, evidence reuse, model/effort, verdicts, reproductions, and checkpoint/commit information.

## Ownership

```text
Owner/Plan --> Root --> Brief + Dispatch State
                         |
                         v
                     Worker Return
                         |
                         v
                    Return Validator
                         |
                         v
                  Ledger + Git Commit
```

The root is the only authority allowed to convert worker evidence into repository history.
