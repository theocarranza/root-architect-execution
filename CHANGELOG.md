# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-09-17

### Added
- **Root / Worker Separation Architecture**:
  - `root-architect` role owning planning, git commits/push, and the execution ledger.
  - `orchestrator` role managing task queues, worker dispatch, and mailbox operations.
  - `impl-executor` role restricted from direct commits and focused on isolated implementation.
  - `spec-validator` and `quality-validator` roles providing independent, two-tier verification before return acceptance.
- **Fail-Closed Write Guards & Dispatch State**:
  - `hooks/root_write_guard.py` PreToolUse hook enforcing that the root architect cannot write implementation files while a dispatch is active.
  - `scripts/dispatch_state.py` for durable, tamper-evident dispatch state tracking with fail-closed semantics on corrupted or unreadable states.
  - `scripts/check_return.py` for envelope return shape validation and evidence gate enforcement.
- **Durable Mailbox & Job Queue**:
  - `scripts/mailbox.py` enforcing at-least-once delivery, ordering guarantees, correlation IDs, and durable message envelopes.
  - `scripts/job_queue.py` providing task lifecycle management synchronized with mailbox transactions.
  - `scripts/root_preflight.py` preflight check enforcing environment configuration, tool scoping, and nesting cap prerequisites.
- **Multi-Host Adapters & Provenance-Backed Interfaces (ADR 0001 & ADR 0003)**:
  - `adapters/claude-code` and `adapters/codex` with layout definitions and manifest generation templates.
  - `scripts/build_adapter.py` byte-gated bundle assembler compiling into `dist/claude-code` and `dist/codex`.
  - Host interface provenance schemas (`schemas/agent-interface.schema.json`) and validator (`scripts/validate_interfaces.py`) ensuring no host claims unsupported capabilities without first-party or empirical backing.
  - Documented subagent nesting cap requirement (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2`).
- **Outcome Gate & CI**:
  - Ten-command outcome gate validating roles, generated agents, bundle byte-equality, interface provenance, unit tests, and plugin smoke installation.
  - Comprehensive GitHub Actions CI workflow (`.github/workflows/outcome-gate.yml`) testing Python 3.11, 3.12, and 3.13 with real TOML parsing and root execution refusal.
  - 216 unit and contract tests across Python 3.10–3.13.
- **Documentation & Knowledge Vault**:
  - Complete documentation suite under `docs/` covering Product, Architecture, Design, Engineering, Operations, Security, Delivery, and User Guides.
  - `AI_Codex` vault with Architecture Decision Records (ADR 0001, ADR 0003), knowledge bases, and session handoffs.
  - Initial end-to-end run report (`AI_Codex/Agent_Reports/2026-09-17-first-end-to-end-run`).

### Security
- Write guard fails closed: any permission error, unreadable dispatch file, or invalid JSON schema denies writes rather than failing open.
- Refused CI execution under root uid (`id -u == 0`) to ensure chmod permission-bit security tests cannot be silently bypassed.
- Strict separation of git privileges preventing worker subagents from creating unverified commits.

### Fixed
- Fixed schema error reporting so sibling schemas identify themselves rather than naming the caller schema.
- Fixed write guard crash and edge cases when dispatch state is unreadable or malformed.
- Resolved symlink traversal loop detection across Python versions.
