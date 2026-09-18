---
title: Glossary
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Glossary

| Term | Meaning |
|---|---|
| Root | Main-thread architect session that owns plan authority, Git, ledger, gates, and dispatch decisions. |
| Orchestrator | Delegated coordination role used by the root architecture to reach workers while preserving nesting/isolation boundaries. |
| Implementer | `impl-executor`; write-scoped worker implementing one bounded task under TDD. |
| Spec validator | Read-only, no-shell worker that judges the candidate diff against the governing task/plan. |
| Quality validator | Read-and-run worker that looks for defects and can rerun named commands. |
| Brief | Schema-validated JSON dispatch contract containing task, attempt, model/effort, read/write paths, interfaces, acceptance commands, constraints, and expected result. |
| Dispatch | One active bounded worker assignment represented by durable state. |
| Ledger | Human-readable durable progress/checkpoint record owned by root. |
| Return gate | `check_return.py` validation of a worker's structured response and cross-field invariants. |
| Capability gate | Validation that declared roles can be expressed by the selected host and generated files match declarations. |
| Outcome gate | Full repository validation required before work is treated as complete. |
| Host | Agent runtime such as Claude Code, Codex, or Cursor. |
| Adapter | Host-specific manifests, hooks/install mechanics, generated agents, and interface declaration. |
| Mutation class | Role-level statement of allowed mutation, e.g. write-scoped, read-only, or read-and-run. |
| RED/GREEN | TDD evidence that a test failed before the implementation and passed after it. |
| Owner-owned path | Dirty or protected path that a worker/root task must not overwrite without owner resolution. |
| Fail closed | Treating missing trust/evidence as a reason to block mutation rather than permit it. |
