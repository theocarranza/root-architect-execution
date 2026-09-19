# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-19

### Added
- **Gemini / Antigravity Host Adapter**:
  - Full adapter layout, interface contract, and manifest templates under `adapters/gemini`.
  - Compile and generate Markdown agent definitions for Gemini in `adapters/gemini/agents/`.
  - Registered support in `hosts/gemini.json` with provenance-backed capability declarations.
- **Turn-1 Session Bootstrap Lifecycle Hooks**:
  - `adapters/gemini/hooks/gemini_session_bootstrap.py`: `PreInvocation` hook for Gemini injecting operational directives and Root Architect protocol on turn 1.
  - `adapters/claude-code/hooks/claude_session_bootstrap.py`: `SessionStart` hook for Claude Code injecting root protocol and operational guidelines.
- **Hardware-Enforced Subagent & Write Boundaries for Gemini**:
  - `adapters/gemini/hooks/gemini_subagent_guard.py`: `PreToolUse` hook intercepting `define_subagent` (hard denial) and restricting `invoke_subagent` strictly to `orchestrator`.
  - `adapters/gemini/hooks/root_write_guard.py`: `PreToolUse` hook physically blocking file modifications (`write_to_file`, `replace_file_content`) and mutating shell execution (`run_command`) targeting files delegated under active dispatches.
  - `scripts/root_preflight.py`: Added autonomous runtime interrogation (`--auto`) to verify registered hardware hooks and reject toolsets carrying `define_subagent`.
- **Automated Multi-Host Release Pipeline**:
  - `.github/workflows/release.yml`: Automated CI/CD workflow triggering on tag push (`v*`) and manual dispatch to test, package, checksum, and publish GitHub releases.
  - Generates standalone multi-host distribution archives (`root-architect-execution-claude-code.zip`, `root-architect-execution-codex.zip`, `root-architect-execution-gemini.zip`) and `checksums.txt` (sha256).

### Changed
- **Clean Distribution Bundling (`dist/`)**:
  - Added `dist/` to `.gitignore` and untracked pre-compiled bundle files from git tracking.
  - Distribution bundles are now cleanly compiled on demand during testing and releases.
  - `scripts/build_adapter.py`: Added `--all` flag to compile all adapters in a single pass, and updated `--check` to auto-build missing bundles before comparison.
- **Cursor Architecture Alignment**:
  - Migrated Cursor agent artifacts from `dist/cursor` to `adapters/cursor/agents/`, resolving legacy tracking anomalies.
- **Outcome Gate & Build Tooling**:
  - `.github/workflows/outcome-gate.yml`: Consolidated multi-host bundle checks into `build_adapter.py --all --check`.
  - `tools/lint.py` and `tools/hooks/pre-commit`: Updated to rebuild all host adapters via `--all`.
  - `tests/test_plugin.py`: Added `setUpModule()` to compile distribution bundles on demand when running clean checkouts.

### Security
- Hard mechanical denial on `define_subagent` preventing the root session from manufacturing arbitrary subagents on the fly.
- Hard restriction on `invoke_subagent` preventing root from bypassing the orchestrator layer and directly invoking workers.
- Fail-closed write blocking during active dispatches on Gemini runtime.

### Fixed
- Fixed runtime guard discovery in `scripts/root_preflight.py` to resolve repository and bundle roots in CI environments where user home is clean.

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
