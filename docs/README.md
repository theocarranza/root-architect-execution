---
title: Root Architect Execution Documentation
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Root Architect Execution Documentation

This directory is the documentation interface for `root-architect-execution`, a multi-agent execution protocol and plugin bundle in which the root session owns the implementation plan, Git history, durable execution state, and acceptance gates while isolated workers implement and independently validate bounded tasks.

## Documentation map

```text
docs/
|-- README.md
|-- 00-product/
|   |-- vision.md
|   |-- requirements.md
|   `-- glossary.md
|-- 01-architecture/
|   |-- system-context.md
|   |-- architecture.md
|   |-- data-model.md
|   `-- decisions/
|       `-- ADR-0001-template.md
|-- 02-design/
|   |-- api.md
|   |-- components.md
|   `-- workflows.md
|-- 03-engineering/
|   |-- development.md
|   |-- testing.md
|   |-- coding-standards.md
|   `-- dependencies.md
|-- 04-operations/
|   |-- deployment.md
|   |-- environments.md
|   |-- observability.md
|   |-- runbook.md
|   `-- disaster-recovery.md
|-- 05-security/
|   |-- security.md
|   |-- threat-model.md
|   `-- data-privacy.md
|-- 06-delivery/
|   |-- roadmap.md
|   |-- release-process.md
|   `-- changelog.md
|-- 07-guides/
|   |-- onboarding.md
|   |-- user-guide.md
|   `-- troubleshooting.md
`-- _templates/
    |-- product.md
    |-- architecture.md
    |-- adr.md
    |-- api.md
    |-- engineering.md
    |-- operations.md
    |-- security.md
    |-- delivery.md
    `-- guide.md
```

## Canonical source hierarchy

When documentation and execution inputs disagree, the protocol's authority order is: latest owner instruction, governing implementation plan, the `SKILL.md` protocol, then supporting ADRs and reports. Generated agent files and `dist/` bundles are derived artifacts and must not be hand-edited.

## Source basis

These documents were derived from the repository's `README.md`, `SKILL.md`, `HANDOFF.md`, `references/contracts.md`, `references/agents/README.md`, role/host/schema conventions, scripts described by the repository, and the CI outcome gate. Where a live behavior has not yet been observed end-to-end, the documentation says so rather than treating the intended contract as production evidence.
