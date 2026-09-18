---
title: Data Privacy
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Data Privacy

The repository is not a user-data service and defines no centralized persistence of personal data. Runtime artifacts can nevertheless contain sensitive project information.

## Potentially sensitive artifacts

- Implementation plans and task briefs.
- Source paths and code excerpts.
- Worker reports/findings.
- Ledger/session notes.
- Host settings and local plugin paths.
- Command output and test failures.

## Handling rules

Keep secrets out of briefs, ledgers, committed fixtures, generated agents, and documentation. Pass credentials through the host/environment mechanisms intended for secrets rather than embedding them in agent contracts.

Owner-owned dirty paths must be preserved and reported rather than overwritten. A task requiring credentials or destructive work outside its brief is an owner escalation condition.

## Retention

Dispatch state and ledger retention is project-local policy. Historical notes should not be deleted without explicit approval because they form part of the audit/recovery trail.

## External transmission

Agent hosts may send task context to their configured model providers according to those hosts' own policies. The protocol should therefore keep handoffs bounded to resolved inputs and necessary paths rather than forwarding entire transcripts.
