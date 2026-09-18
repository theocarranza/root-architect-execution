---
title: Runtime Workflows
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Runtime Workflows

## Root startup

```text
launch root as main thread
  -> observe available capabilities
  -> root_preflight records/verifies observation
  -> initialize queue/run only if preflight passed
  -> validate roles + generated agents for selected host
  -> establish ledger/baseline
```

Claude orchestration requires enough nesting depth for root -> orchestrator -> worker. The documented launch configuration sets `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2` before process start.

## Per-task execution

```text
Root
  | create schema-valid brief
  | open dispatch
  v
Implementer
  | TDD: RED -> implementation -> GREEN
  | structured report
  v
Root / check_return
  | valid?
  +-- no -> one corrective format retry
  |
  v
Spec Validator
  | plan compliance only, no shell
  v
Root
  | PASS?
  +-- no -> findings to same implementer
  |
  v
Quality Validator
  | defect search + permitted command reruns
  v
Root
  | PASS?
  +-- no -> findings to same implementer
  |
  v
close dispatch -> ledger -> stage owned paths -> diff check -> narrow commit
```

## Retry/escalation

Implementation failures remain attached to the same logical task. The protocol allows up to three failures before `blocked`. A stronger model/effort tier is selected only after recorded failure evidence; task renaming must not reset attempt accounting.

## Completion

Targeted evidence can justify an individual task, but completion requires the full recorded baseline and artifact-specific validators. Generated files, manifests, schemas, lockfiles, and installable bundles may require validators beyond ordinary tests.
