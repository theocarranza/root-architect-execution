# Codex and Shared Runtime Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task by task, subject to the repository's root → orchestrator → worker ownership rules. This document authorizes no execution by itself. Checkboxes record completed, evidenced work, not intentions.

**Goal:** Make the Codex workflow executable and verifiable, repair the shared contracts that can currently record false success, and give every other adapter an accurate, separately tested support boundary.

**Architecture:** Root owns the plan, Git, final acceptance, and communication with the operator. An orchestrator agent chooses and evaluates workers. A small deterministic runtime handles admission, dispatch records, exact result capture, permissions, and deadlines; it does not replace the orchestrator's judgment. Host adapters translate actual host events and controls into that shared runtime.

**Tech stack:** Existing Python scripts and JSON schemas; Python 3.12+; standard-library SQLite for transactional runtime records; generated TOML/Markdown agents; host-specific hooks and transports; `unittest` and the existing build/check commands.

**Specification and evidence:**

- [Original Codex runtime audit](../../../AI_Codex/Agent_Reports/2026-09-19-codex-adapter-runtime-audit.md), called **A** below.
- [Adversarial review](../../../AI_Codex/Agent_Reports/2026-09-19-codex-runtime-audit-adversarial-review.md), called **R** below; numbered findings are R1–R7.
- [Existing orchestration decision](../../../AI_Codex/Architecture/ADR/0003-orchestrated-worker-isolation.md). Preserve its intended agent hierarchy; explicitly supersede its disproven enforcement claims.

## Global constraints

- This is a planning deliverable. No implementation task is complete yet.
- Preserve the existing dirty tree and historical run evidence. Establish the implementation baseline before staging, generating, or migrating anything.
- Root delegates work to the orchestrator; only the orchestrator delegates worker tasks. Workers neither spawn agents nor contact the operator. Root remains able to stop a run and relay operator answers.
- The orchestrator is an agent. Code records and enforces decisions; it does not invent plans, judge code quality, or silently replace the orchestrator.
- Workers use predeclared templates. No model-authored agent definitions, invented provider identifiers, or unrecorded model escalation.
- Specification and quality reviews use separate fresh contexts. Specification review has no shell; quality review may run only its assigned verification commands.
- One dependent worker attempt may hold the workspace at a time, including attempts awaiting cancellation confirmation. Retries create new attempts rather than resetting history.
- Preserve raw worker text before parsing or judgment. Record invalid, empty, duplicate, late, and interrupted results explicitly.
- Required but unavailable controls block the governed run. Template generation may remain available with a clear `templates_only` status; it is not runtime acceptance.
- Documentation, source inspection, offline tests, installation checks, and live trials are different evidence. No one substitutes for another.
- A file hash does not authenticate its author. Same-user filesystem access and shell/socket access must be included in permission tests.
- Routine recovery stays within recorded attempt/time limits. Escalate to root only for a decision, permission, or prerequisite the runtime cannot resolve. Do not add repeated approval pauses to the work loop.
- Update the relevant documentation and regenerate affected artifacts within each task. Task 18 reconciles the whole documentation set; it is not an excuse to leave intermediate claims false.
- Run focused tests while implementing, then the full outcome checks at the integration boundary. Do not run live paid trials until execution scope and limits have been established.

## Design decisions

### One authoritative record, readable exports

Use one local SQLite database per workspace for run, task, attempt, preflight, event, and envelope records. State changes and raw envelope insertion commit together. This replaces the current independent mutable queue/dispatch/mailbox records as the source of truth.

The database lives in a controller-owned state directory outside product write paths. Its location is explicit in the launch record. Worker sandboxes must deny writes to that directory and access to privileged controller operations. Merely placing it outside the repository or setting file permissions is insufficient when agents share an operating-system identity.

Keep Markdown envelopes and JSON run/queue/dispatch snapshots as readable exports under `.root-architect/`. Existing guard entry points read the authoritative store through shared code, never these exports. Exports may be regenerated after a crash; they cannot authorize a dispatch. Legacy evidence remains untouched and is imported into a separate versioned store.

SQLite is chosen over ad hoc multi-file locking because queue transitions, envelope linkage, and workspace ownership need a single commit boundary. Use local storage, foreign keys, explicit transactions, and a bounded busy timeout. Network-filesystem state storage is unsupported until tested and declared separately.

### Capability facts are not enforcement claims

Each host profile records product, execution surface, version, distribution channel, and configuration digest. Each capability records these independently:

```json
{
  "availability": "unknown",
  "enforcement": "unknown",
  "scope": "worker",
  "evidence": []
}
```

`availability` is `supported`, `unsupported`, or `unknown`. `enforcement` is `host`, `controller`, `instruction`, or `unknown`. Evidence entries identify source, date, tested version/configuration, and artifact location. A documented field may be supported while its enforcement remains unverified. No boolean coercion may turn `unknown` into a supported or unsupported fact.

Separate delegation, nested delegation, delegation denial, allowed child types, tool restrictions, filesystem restrictions, startup injection, caller identity, result capture, child status, steering, and cancellation. Split read-only filesystem access from absence of a shell and absence of remote mutation tools.

### Runtime identity and state

Use separate identifiers for `run_id`, `task_id`, `attempt_id`, `provider_thread_id`, `parent_thread_id`, `provider_turn_id`, and `provider_event_id`. A run contains many tasks; a task contains immutable attempts. Worker role names are not task or attempt identifiers.

```text
Run:     admitted -> running -> completed | rejected | blocked | abandoned
Attempt: reserved -> starting -> active -> captured -> validated | invalid
                     |           |
                     |           +-> cancel_requested -> stopped | stop_unknown
                     +-> start_failed
```

`waiting_approval` and `waiting_input` are observed activity states, not evidence of failure. Timeout is a recorded event that requests cancellation; it is not proof the worker stopped. `stop_unknown` retains the workspace reservation and blocks replacement work. A late result is preserved without reopening a terminal attempt. A new attempt may start only after the old writer is confirmed stopped or its workspace is isolated from the replacement.

A blocked run may resume through an explicit recorded resume operation after its prerequisite is resolved and admission is rechecked. Completed, rejected, or abandoned runs remain terminal; continuation creates a linked run. Resuming a run never resets a terminal attempt or loses its evidence.

Machine validation establishes whether a return is usable evidence. The orchestrator separately records an acceptance/rejection decision. Run completion requires all required decisions and root's final gate.

### Fixed families, generated variants

Keep one canonical declaration per worker family. Add named variants within that declaration, reusing the existing structured `model` and `reasoning` concepts. Generate separate host templates and an installation catalog from these variants. Do not duplicate role manifests or change model identifiers in shared schemas.

Initial selection preserves the current cheapest baseline unless a host/model compatibility check rejects it:

| Family | Named variants and portable settings |
| --- | --- |
| Implementation | `impl-executor-cheap` cheap/low; `impl-executor-mid` mid/medium; `impl-executor-strong` strong/high |
| Specification | `spec-validator-cheap` cheap/medium; `spec-validator-mid` mid/medium; `spec-validator-strong` strong/high |
| Quality | `quality-validator-cheap` cheap/medium; `quality-validator-mid` mid/medium; `quality-validator-strong` strong/high |

The original audit proposed starting validators at `mid`; there is no comparative evidence requiring that increase. Every variant still needs a host-specific compatibility check. Record requested tier/effort, selected template, resolved model/effort, and observed effective model/effort separately. An unknown effective value remains unknown.

### Codex launch boundary

Prefer native nested agents with trusted hooks and a controller connected to the same runtime. Task 3 must prove the exact capture, identity, and control paths before this is selected as supported. A separately launched App Server workflow is the fallback candidate if native plugin integration cannot provide those paths; it must start a new governed session rather than claim access to an unrelated existing chat.

Neither approach may collapse the orchestrator into a script or allow root to dispatch workers directly. If neither candidate meets a required control, the result is an explicit blocked capability, not a weaker implementation presented as complete.

## File and responsibility map

New paths in this table are proposed deliverables, not existing files.

| Area | Files | Responsibility |
| --- | --- | --- |
| Runtime contracts | `schemas/runtime-*.schema.json`, `scripts/runtime_contract.py` | Versioned records and validation; no host calls. |
| Storage | `scripts/runtime_store.py` | Transactions, uniqueness, append-only evidence, queries, read-only exports. |
| Policy | `scripts/runtime_policy.py` | Run admission, allowed actors/routes, template selection constraints, transition rules. |
| Service and commands | `scripts/runtime_service.py`, `scripts/runtime.py` | Authenticated local operations; command interface; no orchestration judgment. |
| Host bridge contract | `scripts/host_runtime.py`, `adapters/<host>/runtime.py` | Host probing, start/status/cancel/control and event translation. |
| Monitoring | `scripts/runtime_monitor.py` | Deadline processing, controller liveness, bounded cancellation and recovery. |
| Existing entry points | `root_preflight.py`, `job_queue.py`, `dispatch_state.py`, `mailbox.py`, `check_return.py` under `scripts/` | Compatibility commands over the common policy/store; no independent writable truth. |
| Templates | `roles/`, `hosts/`, `adapters/*/agent-interface.json`, `scripts/render_agents.py`, `scripts/validate_roles.py`, `scripts/validate_interfaces.py` | Family declarations, host facts, generated catalogs and disclosures. |
| Tests | `tests/test_runtime_*.py`, `tests/test_codex_*.py`, host-specific test files | Regression, concurrency, crash, contract, and negative permission coverage. |
| Live acceptance | `scripts/acceptance_runtime.py`, `tests/fixtures/runtime/` | Explicit, bounded host trials and evidence manifests; absent host is not a pass. |
| Migration | `scripts/migrate_runtime.py` | Inspect, import, compare, and retain legacy evidence. |

## Task order and tracking

| Task | Scope | Depends on |
| --- | --- | --- |
| 1 | Baseline, requirements, and threat boundary | — |
| 2 | Shared capability and host-runtime contract | 1 |
| 3 | Early Codex feasibility trial | 2 |
| 4 | Versioned runtime records | 2 |
| 5 | Transactional storage and protected service | 4 |
| 6 | Preflight and dispatch admission | 2, 5 |
| 7 | Envelope capture and return validation | 5 |
| 8 | Queue, attempts, and decision lifecycle | 6, 7 |
| 9 | Worker families and template variants | 2, 4 |
| 10 | Codex installation and startup | 3, 6, 9 |
| 11 | Codex permissions and role boundaries | 3, 5, 9, 10 |
| 12 | Codex dispatch and exact return capture | 7, 8, 10, 11 |
| 13 | Shared monitor, Codex recovery, operator stop | 12 |
| 14 | Claude Code-specific fixes | 2, 6–9, 13 |
| 15 | Gemini-specific fixes and product separation | 2, 6–9, 13 |
| 16 | Antigravity-specific fixes | 15 |
| 17 | Cursor-specific fixes | 2, 6–9, 13 |
| 18 | Documentation and architecture reconciliation | 10–17 |
| 19 | Migration, packaging, installation checks | 8–18 |
| 20 | Integrated acceptance and release evidence | 19 |

Tasks 3 and 4 can progress independently. After the common runtime stabilizes, Claude Code and Cursor work can proceed independently of the Gemini/Antigravity separation. Shared files have one owner at a time. A blocked host does not stop unrelated shared fixes, but prevents that host from being marked runtime-ready.

### Task 1 — Record the baseline and settle the required boundaries

**Files:** create `AI_Codex/Architecture/ADR/0004-runtime-evidence-and-admission.md`; update `docs/00-product/requirements.md` and `docs/05-security/threat-model.md`; add regression cases to `tests/test_runtime_regressions.py`.

- [ ] Record the starting commit, dirty-file hashes, current host versions, active legacy runs, and generated-bundle differences. Preserve the existing Gemini/Claude/shared changes and assign ownership before editing them.
- [x] Convert R1–R3 reproductions into tests: empty tools passing preflight, forged preflight identity/type, dispatch without admission, two active queue tasks, fake envelope, old report reused, and direct worker-to-root routing.
- [ ] Record the inherited baseline accurately: the review ran 263 tests with two Gemini bundle failures; rerun at implementation start rather than treating that count as permanent.
- [x] Write the architecture decision adopting the design above and superseding only the incorrect parts of decision 0003. Preserve historical evidence and its dates.
- [x] Distinguish compulsory execution controls from disclosed policy limitations. Required worker tool/delegation denial and protected evidence storage must block runtime acceptance if absent. Root's ordinary chat outside the governed launcher remains outside the enforcement claim.

**Validation:** `python3 -m unittest tests.test_runtime_regressions -v`. The new tests must demonstrate the current failures before repairs. Existing historical examples remain readable.

### Task 2 — Separate host identity, capability, and enforcement

**Files:** modify `schemas/host-capability.schema.json`, `schemas/agent-interface.schema.json`, `scripts/validate_interfaces.py`, and `scripts/render_agents.py`; create `scripts/host_runtime.py`, `tests/test_runtime_capabilities.py`, and `tests/test_host_runtime_contract.py`.

- [x] Introduce the capability shape above, explicit product/surface/version/channel identity, and evidence references. Provide a conservative conversion from existing booleans; unsupported inference becomes `unknown`.
- [x] Define a host bridge with these operations and schema-validated JSON results. A missing operation returns `unsupported_host_capability` with the specific capability, not an empty successful result.

```python
probe(launch_context: dict) -> dict
start(parent_thread_id: str, template_id: str, task_envelope_id: str,
      idempotency_key: str) -> dict
status(provider_thread_id: str) -> dict
follow_up(provider_thread_id: str, answer_envelope_id: str) -> dict
cancel(provider_thread_id: str) -> dict
events(cursor: str | None) -> dict
```

- [x] Define event results as an ordered `events` list plus `next_cursor`; each event identifies its source and child, including explicit unknowns. Do not invent provider event IDs where the host supplies none; record the adapter's deduplication key separately.
- [x] Update validators to check enforcement semantics and execution surface, not only matching `supported` booleans. A sample containing `readonly: true` cannot prove mutation denial.
- [ ] Move host-specific probing and payload parsing out of `root_preflight.py` into the corresponding adapter. Reject the current practice of fabricating an observed tool roster from the presence of local files.
- [x] Add fixture cases for documentation-only support, live support, contradictory evidence, unknown nesting, model/effort alias collapse, and plugin-versus-session behavior.

**Validation:** `python3 -m unittest tests.test_runtime_capabilities tests.test_host_runtime_contract -v`; `python3 scripts/validate_interfaces.py`. These checks validate claims without pretending to run any host.

### Task 3 — Prove the minimum viable Codex control path early

**Files:** create `scripts/acceptance_runtime.py`, `tests/fixtures/runtime/codex-probe.json`, and `AI_Codex/Agent_Reports/2026-09-19-codex-runtime-feasibility.md`; update `adapters/codex/agent-interface.json` with observed evidence.

- [ ] Build an isolated trial workspace and separate host configuration. Record the executable, version, plugin/configuration hashes, account access outcome, and explicit time/token limits before invoking a model.
- [ ] Exercise one root → orchestrator → worker cycle. Capture actual identities, tool names, hook payloads, final message representation, and the effective selected template/model/effort where exposed.
- [ ] Test `SubagentStop` capture, missing final text, duplicate events, status inspection, targeted follow-up, and cancellation acknowledgement. Determine whether capture can be committed before the orchestrator is allowed to validate the result.
- [ ] Test worker delegation disabled through supported Codex configuration, including the `agents.enabled` candidate; test no-shell specification review, remote mutation access, and parent permission overrides. Do not treat an agent obeying “do not do this” as a denial test.
- [ ] Test whether the controller can identify callers and protect its storage/control endpoint from the worker's shell. A writable state database or forgeable role flag fails the required boundary.
- [ ] Select native-session integration only if all required operations are proven. Otherwise run a bounded App Server launch trial for a newly controlled session. Record an explicit blocked result if neither path works; retain useful offline work and name the missing host capability.

**Proposed acceptance command:** `python3 scripts/acceptance_runtime.py --host codex --scenario capability-probe --require-live --max-seconds 300 --max-tokens 12000`. Implement these arguments here. If the host cannot enforce the token cap, refuse the live trial until an enforceable budget is supplied; never silently ignore it.

**Done when:** a durable decision names the exact transport and its evidence, or identifies the exact blocker. A blocked feasibility result does not complete dependent Codex implementation tasks.

### Task 4 — Define records that bind every result to one attempt

**Files:** create `schemas/runtime-run.schema.json`, `schemas/runtime-preflight.schema.json`, `schemas/runtime-attempt.schema.json`, `schemas/runtime-event.schema.json`, `schemas/runtime-envelope.schema.json`, `scripts/runtime_contract.py`, and `tests/test_runtime_contracts.py`; update `schemas/brief.schema.json` and `schemas/orchestrator-outcome.schema.json` for version 2 references.

- [x] Define version 2 records with strict types and rejected unknown fields. Separate run/task/attempt/provider identifiers, workspace/configuration fingerprints, principal identity, and the state transitions above.
- [x] Define `started_at`, `last_activity_at`, `deadline_at`, `last_envelope_id`, observed activity state, and controller lease expiry explicitly. Distinguish provider-observed progress from local bookkeeping updates and retain separate version 1 readers for historical data.
- [x] Define an envelope header containing `envelope_id`, `run_id`, `task_id`, `attempt_id`, `kind`, `from`, `to`, `captured_by`, `capture_source`, `reply_to`, `body_sha256`, `created_at`, and provider correlation fields. Nullable task/attempt values are allowed only for run-level messages.
- [x] Keep business authorship separate from physical capture: worker authors a report, the controller captures it for the orchestrator. Neither a worker nor the orchestrator may forge controller origin.
- [x] Define valid routes: root→orchestrator task/answer; orchestrator→root question/outcome; orchestrator→worker task/answer; worker→orchestrator report/question; controller-origin failure/lifecycle records addressed to the responsible parent. Reject other pairs.
- [x] Make blocked outcomes require a reason and referenced question/failure evidence. Make accepted outcomes reference validated attempts and orchestrator decisions, rather than trusting counts or filenames.
- [x] Add schema tests for null/list/scalar input, missing correlation, mismatched attempts, invented templates, wrong routes, and strings in boolean fields.

**Validation:** `python3 -m unittest tests.test_runtime_contracts -v`. Example invariant: an envelope for attempt `a1` cannot validate as the answer to `a2`, even when both use the same worker role.

### Task 5 — Commit evidence and state together through one protected service

**Files:** create `scripts/runtime_store.py`, `scripts/runtime_service.py`, `scripts/runtime.py`, `tests/test_runtime_store.py`, and `tests/test_runtime_service.py`.

- [x] Implement tables for runs, preflights, tasks, attempts, envelopes, events, decisions, and workspace reservations. Store raw message bytes as immutable binary data; record hashes and source metadata in the same transaction.
- [x] Enable foreign keys; use `BEGIN IMMEDIATE` for state-changing operations, a bounded lock timeout, uniqueness constraints, and a schema version. Reject filesystem state roots that fail the supported local-storage check.
- [x] Enforce unique provider-result/deduplication keys. Repeating an identical event returns the original record; repeating its identity with different content blocks the run and preserves the conflict.
- [x] Implement append-only event/envelope tables, explicit correction records, and generated JSON/Markdown exports. Never read exports as authoritative state.
- [ ] Implement service authentication from the proven host/controller identity path. Do not accept `--role`, `persisted_by`, environment variables, or a caller-provided session ID as authentication. Keep privileged credentials out of worker prompts, environment, readable files, and inherited connections.
- [ ] Prove worker denial for database writes, control-socket access, and credential access. Where the host cannot enforce this, return an unsupported boundary rather than relying on file mode bits.
- [x] Add process-level tests: simultaneous writers, forced exit before/after commit, disk-full/write failure, duplicate event delivery, partial export, restart, and conflicting result identity.

**Validation:** `python3 -m unittest tests.test_runtime_store tests.test_runtime_service -v`.

```python
assert captured_envelope_exists == committed_attempt_transition_exists
assert identical_event_replay_creates_new_envelope is False
assert worker_can_modify_authoritative_state is False
```

These assertions describe required observations; tests must induce the failures rather than populate passing booleans.

### Task 6 — Replace the false preflight guarantee and close alternate entry points

**Files:** modify `scripts/root_preflight.py`, `scripts/dispatch_state.py`, `scripts/job_queue.py`; create `scripts/runtime_policy.py` and `tests/test_runtime_admission.py`; update `references/agents/root-architect.md`.

- [ ] Require explicit host, workspace, run, controller session, installed catalog digest, and effective configuration digest for admission. Remove the silent `claude-code` default from mutation paths.
- [ ] Validate `passed` as a literal boolean and bind the record to its run/host/session/configuration. Reject stale, forged, missing, mismatched, and unsupported records before storing an admitted run.
- [ ] Check actual dispatch availability independently from permitted child selection. An empty tool map must fail required delegation; unrelated visible built-ins must not falsely invalidate a controller-enforced selection policy.
- [ ] Make `dispatch_state.py open`, queue creation, service dispatch, and resumed execution call the same admission policy. Compatibility commands cannot bypass it by directly writing JSON.
- [ ] Limit model observations to supplemental evidence. Require the selected transport's actual capability observations for required boundaries; file existence alone never establishes an active hook or registered agent.
- [ ] Invalidate/recheck admission when configuration, templates, permissions, hook trust, or controlling session changes. An old passing record must not authorize a new process silently.
- [ ] Make diagnostics host-specific, including exact failed capability and recovery action. A Codex failure must not recommend `claude --agent`.

**Validation:** `python3 -m unittest tests.test_runtime_admission -v`, including the original R1 counterexamples and every supported dispatch entry point.

### Task 7 — Preserve and validate real returns, including bad ones

**Files:** modify `scripts/mailbox.py`, `scripts/check_return.py`, `schemas/envelope.schema.json`, and `schemas/orchestrator-outcome.schema.json`; create `tests/test_runtime_envelopes.py` and `tests/test_runtime_returns.py`.

- [ ] Make mailbox mutation a service operation. Preserve legacy listing/verification as explicitly legacy commands; do not let `post --persisted-by orchestrator` mint trusted evidence.
- [x] Capture final message text using a declared encoding without trimming, fence repair, newline conversion, or model paraphrase. Retain raw provider metadata separately from the portable text body.
- [x] Validate record identity, sender/recipient route, kind, `reply_to`, body hash, selected template, and task/attempt linkage before accepting a result for a task.
- [ ] Require `check_return.py` in governed runs to load a captured envelope by identity. Reject extra prose/multiple fences under the strict return contract; keep malformed original bytes before any format-correction request.
- [x] Validate top-level JSON type before cross-field checks. Reject wrong model/effort claims against recorded effective configuration where observable, and never infer effective configuration from the worker's own report.
- [x] Make task-report pairing one-to-one per attempt. A repeated role name or reused report must not satisfy a later task. Reject wrong-kind and wrong-run envelopes even when files and hashes exist.
- [x] Distinguish a worker's reported failure from a controller's missing-result failure. Record test command output, exit status, and tested-tree fingerprints as execution evidence, not solely worker-written pass counts.

**Validation:** `python3 -m unittest tests.test_runtime_envelopes tests.test_runtime_returns -v`. Include fake files, body-only corruption, body-plus-hash replacement attempts, mismatched recipients, empty output, and two tasks assigned to the same role.

### Task 8 — Make queue and dispatch one lifecycle

**Files:** modify `scripts/job_queue.py`, `scripts/dispatch_state.py`, `scripts/runtime_policy.py`, and `scripts/runtime_store.py`; create `tests/test_runtime_lifecycle.py`.

- [x] Reserve the workspace and create the attempt before calling the host. Record the launch idempotency key, selected template, deadline, and intended parent.
- [x] Record successful child creation or start failure without guessing a child ID. On crash between launch and acknowledgement, reconcile by the launch key; do not launch another child until the first is found or proven absent.
- [x] Enforce one active/reserved/cancelling dependent attempt across runs for that workspace in the database, including direct calls that bypass `next`.
- [x] Commit captured envelope and attempt transition together. No terminal result may point at a missing, invalid, or unrelated envelope.
- [x] Keep machine validation separate from orchestrator judgment. Require the orchestrator's recorded decision before progressing to a validator, repair, or outcome.
- [x] Add a new immutable attempt for a repair or model escalation. Permit at most one format correction per worker return and preserve the original evidence; keep it distinct from an implementation attempt.
- [x] Validate final outcomes against required implementation/specification/quality decisions. Root's final outcome gate remains separate from the orchestrator's recommendation.

**Validation:** `python3 -m unittest tests.test_runtime_lifecycle -v`. Include simultaneous reservation, report replay, terminal-state reversal, crash after host start, and accepted outcome with a missing validator.

### Task 9 — Generate named worker variants without duplicating families

**Files:** modify `schemas/agent-role.schema.json`, `roles/*.json`, `scripts/render_agents.py`, `scripts/validate_roles.py`, `adapters/codex/install.py`, and `schemas/brief.schema.json`; create `schemas/template-catalog.schema.json` and `tests/test_runtime_templates.py`.

- [ ] Add family-contained named variants using the table above; retain one declaration per logical position. Reuse existing model/effort structures rather than introducing conflicting copies.
- [ ] Render the catalog and agent files from the same selection function. Preserve explicit model and effort in Codex variants; never rely on spawn overrides to defeat fixed template values.
- [ ] Make installer, interface validator, smoke expectations, and guard role resolution use the generated catalog. Remove hard-coded three-worker-name lists that would bypass or reject variants.
- [ ] Record family, selected template, requested/resolved/effective settings and catalog hash throughout brief, attempt, capture metadata, and outcome. Missing effective values do not become invented observations.
- [ ] Validate selected model/effort combinations per host. When host tiers collapse to the same model or effort, disclose it and avoid counting that selection as a real escalation.
- [ ] Require a recorded reason before changing tier after failure. Undeclared templates and dynamic definitions fail admission.
- [ ] Define compatibility aliases for old worker names as fixed catalog entries during migration; they cannot silently select a stronger variant or bypass permissions.

**Validation:** `python3 -m unittest tests.test_runtime_templates -v`; role/render/interface checks for every declared host. Compare installed catalog and file hashes, not merely the number of generated files.

### Task 10 — Codex: install a complete bundle and establish startup

**Files:** modify `adapters/codex/install.py`, `adapters/codex/layout.json`, `adapters/codex/manifest.template.json`, and `adapters/codex/README.md`; create `adapters/codex/runtime.py`, `adapters/codex/launch.py`, `adapters/codex/hooks/hooks.json`, `adapters/codex/hooks/session_start.py`, and `tests/test_codex_startup.py`.

- [ ] Implement the launch contract selected in Task 3. Bind the ordinary main session to root protocol without pretending a custom-agent file automatically becomes the main session.
- [ ] Ship the hook programs, role references, runtime scripts, schemas, and catalog. Resolve installed paths through the installed bundle root; quote paths with spaces and run correctly from an unrelated working directory.
- [ ] Inject concise developer context on `startup`, `resume`, `clear`, and `compact`; record an idempotent bootstrap event for the governed session. Avoid promoting child sessions to root.
- [ ] Make the independent launcher/service admission reject missing, disabled, changed, or untrusted hook configuration when hooks are required by the chosen transport. A skipped hook is not expected to reject itself.
- [ ] Document the host's hook trust step without bypassing it or changing user policy automatically. Detect revoked trust and configuration changes on resumed runs.
- [ ] Make installation idempotent, preserve unrelated agents, detect name collisions/overrides, and verify the files Codex actually resolves. Separate package install, template materialization, hook trust, and session restart results.

**Validation:** `python3 -m unittest tests.test_codex_startup -v`; isolated installation with no source checkout on the path; live startup scenarios later in Task 20.

### Task 11 — Codex: enforce worker and controller boundaries

**Files:** modify `adapters/codex/runtime.py`, `hosts/codex.json`, `adapters/codex/agent-interface.json`, and `scripts/render_agents.py`; create `tests/test_codex_permissions.py` and `tests/fixtures/runtime/codex-permissions.json`.

- [ ] Apply the delegation-denial mechanism proven in Task 3 to every worker variant; retain delegation for the orchestrator. Reject dynamic template creation and undeclared child types at the controller boundary.
- [ ] Restrict specification review to reading/searching without a shell; restrict quality review commands and implementer writes to their assigned grants. Include remote tools and inherited connectors, not just local filesystem tools.
- [ ] Restrict evidence-store and privileged control access independently of product write access. Never hand workers a credential that can create task decisions or impersonate root/orchestrator.
- [ ] Test effective sandbox/permissions after parent overrides and role-file precedence. Block the governed run if a required restriction was weakened.
- [ ] Preserve Codex's identity limitation honestly. Do not globally deny `apply_patch` using guessed worker identity. Any patch-admission design must bind the path and before/after digest and separately cover shell-based writes.
- [ ] Add adversarial live requests: worker spawns another agent, worker writes evidence, specification validator runs a shell, quality validator mutates a product file, and root bypasses the recorded orchestrator selection. Record denial by the host/controller, not a polite model refusal.

**Validation:** `python3 -m unittest tests.test_codex_permissions -v`; Task 20's permission trial is required before claiming enforcement.

### Task 12 — Codex: connect native dispatch and result capture

**Files:** modify `adapters/codex/runtime.py`; create `adapters/codex/hooks/subagent_lifecycle.py`, `tests/test_codex_capture.py`, and sanitized fixtures under `tests/fixtures/runtime/codex/`.

- [ ] Implement Task 2's bridge using the transport selected in Task 3. Translate actual payloads; keep provider field names out of shared policy.
- [ ] Persist task envelope and reservation before dispatch. Correlate the returned child identity to the parent/run/task/attempt/catalog entry.
- [ ] Capture the native final result through the controller before exposing a validation operation to the orchestrator. If the transport cannot prove this ordering, block acceptance and retain the raw event for diagnosis.
- [ ] Handle nullable final messages, duplicate stop events, multiple turns, reconnects, out-of-order events, and partial streaming. A commentary item or intermediate turn is not automatically the final task result.
- [ ] Route worker questions through the orchestrator and root answers back through envelopes. Root receives preserved worker evidence by reference; it does not rewrite the worker report.
- [ ] Validate orchestrator outcomes through the same capture path. A root-facing summary alone cannot close a run.

**Validation:** `python3 -m unittest tests.test_codex_capture -v`; replay sanitized real payloads from Task 3, including duplicates and interruption cases.

### Task 13 — Monitor both levels and recover without duplicate writers

**Files:** create `scripts/runtime_monitor.py`, `tests/test_runtime_monitor.py`, and `tests/test_codex_recovery.py`; modify `adapters/codex/runtime.py` and `scripts/runtime_service.py`.

- [ ] Run monitoring in the controller process, independently of an agent choosing to poll. Track controller heartbeat separately from worker activity; never manufacture worker progress by touching queue timestamps.
- [ ] Use a persisted per-run monitoring policy. Initial defaults: five-second observation interval, 60-second controller lease, one targeted status follow-up, and a 30-second cancellation-acknowledgement grace period. Task execution deadlines and budget limits are explicit launch inputs, not hidden defaults.
- [ ] Distinguish active, approval-waiting, input-waiting, completed, stopped, and unknown observations. Preserve actual provider errors before classifying transport, authentication, quota, rate limit, or model access failures.
- [ ] On a worker deadline, record the deadline event, request status once where supported, and request cancellation if still unresolved. Do not start a replacement until stop confirmation or workspace isolation is established.
- [ ] On an orchestrator deadline, stop further worker dispatch, preserve worker state, and notify root through a failure/question envelope. A dead root session cannot display a message immediately; retain it for reconnect and expose it in runtime status.
- [ ] On operator stop, prevent new reservations immediately, request bounded cancellation of descendants and their active commands, and record unresolved live writers. Never mark them stopped solely because cancellation was requested; a child that leaves a writing subprocess behind has not released the workspace safely.
- [ ] On restart, reconcile provider children and unfinished reservations before new work. Preserve late output as a late-result event; never turn it into success for a newer attempt.

**Validation:** `python3 -m unittest tests.test_runtime_monitor tests.test_codex_recovery -v`; deterministic clock tests plus actual live cancellation/reconnect scenarios in Task 20.

### Task 14 — Claude Code: repair launch, scope, and evidence integration

**Files:** modify `hosts/claude-code.json`, `adapters/claude-code/agent-interface.json`, `adapters/claude-code/hooks/claude_session_bootstrap.py`, `adapters/claude-code/hooks/root_write_guard.py`, `adapters/claude-code/hooks/worker_git_guard.py`, `adapters/claude-code/hooks/hooks.json`, `adapters/claude-code/layout.json`, and `adapters/claude-code/README.md`; create `adapters/claude-code/runtime.py` and `tests/test_claude_runtime.py`.

- [ ] Reconcile the existing uncommitted Claude changes against this plan. Refresh evidence for the installed product/version and plugin distribution channel before preserving a claimed guarantee.
- [ ] Verify actual root launch selection, namespaced agent resolution, nested delegation prerequisites, and orchestrator worker access. Startup tool observation alone is insufficient to prove the next depth can dispatch.
- [ ] Keep plugin-wide hook enforcement separate from unsupported per-agent plugin hooks. Verify agent identity on every relevant write, shell, delegation, capture, and control operation.
- [ ] Replace keyword/transcript-based bootstrap inference with explicit governed launch identity. Use installed-root paths and `--host claude-code`; cover fresh sessions without an existing `.root-architect` directory and resumed sessions.
- [ ] Update guards to resolve worker families/variants from the catalog and read the authoritative runtime store. Missing/unknown identity must not inherit a privileged role. Preserve legitimate implementer writes while rejecting root/worker violations.
- [ ] Detect higher-precedence agent overrides and verify effective template/model/tools rather than trusting the plugin's files. Exercise shell-based Git and file writes, not only Edit/Write tools.
- [ ] Integrate capture, status, cancellation, and monitor events with the shared runtime. If worktree isolation is adopted, verify path resolution, evidence access, and both guards inside it; a worktree alone does not enforce the brief's paths.

**Validation:** `python3 -m unittest tests.test_claude_runtime -v`; generated/bundle checks; installed nested cycle and negative permission tests. Preserve historical partial trials without relabelling them as full completion.

### Task 15 — Gemini: untangle product identity and remove false runtime probes

**Files:** modify `hosts/gemini.json`, `adapters/gemini/agent-interface.json`, `adapters/gemini/README.md`, `adapters/gemini/layout.json`, its manifest/skill templates, hooks, and `tests/test_gemini_bootstrap_hook.py` / `tests/test_gemini_write_guard.py`; create `tests/test_gemini_runtime.py`.

- [ ] Identify the actual installed executable, product, execution surface, registration paths, and event schemas. Current Gemini records cite Antigravity material while the separate Antigravity interface says the products are not interchangeable; resolve that contradiction before granting support.
- [ ] Assign Antigravity-specific mappings/hooks to Task 16. Preserve the legacy `gemini` bundle through an explicit compatibility notice and migration path; do not silently rename a user's installation.
- [ ] Source Gemini CLI facts independently. Keep unavailable features `unknown`/`unsupported`; do not copy Antigravity tools, fields, hook syntax, or model aliases into a Gemini profile by analogy.
- [ ] Replace `interrogate_runtime()`'s file-search/text-match inference with real adapter observations. Finding `orchestrator.md` or a hook command string is not proof of registration or enforcement.
- [ ] Correct bootstrap host selection and installed-root resolution. Stop unconditional root-role injection into every invocation; bind bootstrap to the governed root session and preserve distinct worker/orchestrator instructions.
- [ ] Fix the current stale generated-bundle failure through the builder's owned-output manifest. Preview obsolete generated files, preserve unrelated files, and regenerate only after the layout/product identity decision is settled.
- [ ] Implement the shared host bridge only for capabilities proven on Gemini CLI. If nesting or required denial cannot be established, ship accurate template-only/blocked status and a bounded follow-up capability task, not a counterfeit passing probe.

**Validation:** `python3 -m unittest tests.test_gemini_runtime tests.test_gemini_bootstrap_hook tests.test_gemini_write_guard -v`; rebuild/check the correct bundle; trial against the explicitly identified Gemini product.

### Task 16 — Antigravity: make its separate contract executable or explicitly limited

**Files:** modify `adapters/antigravity/agent-interface.json`; create `hosts/antigravity.json`, `adapters/antigravity/runtime.py`, `adapters/antigravity/layout.json`, `adapters/antigravity/manifest.template.json`, `adapters/antigravity/README.md`, host-correct hooks, and `tests/test_antigravity_runtime.py` only as supported by verified registration mechanics.

- [ ] Transfer product-specific content identified in Task 15 with preserved provenance. Keep agent definitions generated from shared families and prevent two host IDs from accidentally registering the same bundle.
- [ ] Verify `mainAgent` and `subagent` independently. Do not assert that both must be true merely because a local fixture expects it; test root and dispatched-agent discovery separately.
- [ ] Replace unknown-caller fallback-to-root in the transferred delegation guard. Reject privileged requests without verified caller identity; deny unknown worker variants through the generated catalog.
- [ ] Verify actual hook input/output shape. Exercise malformed `toolCall`, non-object arguments, empty subagent arrays, namespaced identities, and alternate shell/write paths. Parsing the wrong shape must not become permission to proceed.
- [ ] Separate spawn, message, status, and cancellation capabilities. A native `send_message` channel may transport an envelope reference, but does not replace durable task-bound result capture or prove append-only evidence.
- [ ] Verify inherited tools/customizations, worker delegation denial, and model/effort resolution. Preserve unsupported effort and collapsed tier facts rather than reporting fictitious escalation.
- [ ] Build/install a host-specific bundle and connect the shared runtime. If only source-level evidence is obtainable, retain that status and leave live acceptance unchecked.

**Validation:** `python3 -m unittest tests.test_antigravity_runtime -v`; dedicated build/install checks and a real root→orchestrator→worker trial when the host is available.

### Task 17 — Cursor: stop conflating plugin, local, and hosted execution

**Files:** modify `hosts/cursor.json`, `adapters/cursor/agent-interface.json`, and generated Cursor agents; create `adapters/cursor/README.md`, `tests/test_cursor_runtime.py`, and `adapters/cursor/runtime.py` for the selected supported surface. Add layout/installer files only if their registration contract is verified.

- [ ] Separate plugin agent-file facts from hosted and local runtime interfaces. Record which surface each claim and test covers.
- [ ] Remove claims that inherited model syntax or `readonly` is enforced when the interface evidence only shows examples. Verify accepted model/effort syntax, model resolution, shell restrictions, and remote write tools independently.
- [ ] Probe nested delegation on the selected surface. Until proven, do not offer a runnable root template whose only permitted child is an unavailable orchestrator.
- [ ] If native nesting is unavailable, test an explicitly separate worker-process transport controlled by the orchestrator agent. Do not flatten the hierarchy into root→worker or call a scheduler an orchestrator.
- [ ] Implement registered-template verification, result capture, child control, and protected state access only on the proven surface. Report local/hosted mismatches as unsupported capability errors.
- [ ] Provide a precise installation path and ownership manifest if packaging is supported; otherwise label the deliverable as templates/research with no install/runtime claim.

**Validation:** `python3 -m unittest tests.test_cursor_runtime -v`; no silent skip for unsupported nesting. Live acceptance is surface-specific and cannot be borrowed from another Cursor interface.

### Task 18 — Reconcile the whole protocol and documentation

**Files:** update `SKILL.md`, `skills/root-architect-execution/SKILL.md`, `references/agents/*.md`, `references/contracts.md`, `README.md`, and relevant files under `docs/00-product/`, `docs/01-architecture/`, `docs/02-design/`, `docs/03-engineering/`, `docs/04-operations/`, `docs/05-security/`, `docs/06-delivery/`, and `docs/07-guides/`; add `tests/test_runtime_documentation.py` for generated-contract consistency.

- [ ] Choose `SKILL.md` as canonical protocol prose and derive packaged copies plus explicit host overlays. Eliminate independent hand-edited workflow copies.
- [ ] Replace direct-root-to-worker diagrams everywhere, including requirements, data-model ownership, architecture, and operator guides. Explain that runtime code records/controls and the orchestrator judges.
- [ ] Correct orchestrator command grants to include the actual queue/runtime operations and eliminate the need to manually create body files. Separate raw capture responsibility from model judgment.
- [ ] Document the new authoritative store, legacy imports, readable exports, startup trust, unknown identity, cancellation uncertainty, and late-result recovery.
- [ ] Replace global “hardware-enforced,” “workers cannot write,” “append-only,” and “boundary holds” claims with the exact tested actor/tool/storage boundary. Explain that absent shell tools, read-only filesystems, and restricted remote tools are separate guarantees.
- [ ] Publish one support table by host product/surface/version: templates, installation, startup, nesting, denial, capture, monitoring, and live acceptance. Unknown/unavailable cells remain visible.
- [ ] Add dated amendments linking the old audits/decision to the implemented resolution; retain original historical reports. Keep model pricing/quality claims out unless separately evidenced.

**Validation:** `python3 -m unittest tests.test_runtime_documentation -v`; rendered skill equality, link checks, command examples checked against parsers, and manual review of the ownership/support table.

### Task 19 — Migrate safely and make packaging checks reflect reality

**Files:** create `scripts/migrate_runtime.py` and `tests/test_runtime_migration.py`; modify `scripts/build_adapter.py`, `scripts/smoke_install.py`, `.github/workflows/outcome-gate.yml`, and host installers/layouts.

- [ ] Implement `migrate_runtime.py inspect`, `import`, and `verify` subcommands. `inspect` changes nothing; `import` creates a new versioned store with recorded source hashes; `verify` compares all preserved bodies and links.
- [ ] Import historical records as legacy/unverified where identity is missing. Never invent provider IDs, reconstruct lost raw returns, or upgrade a historical preflight to a verified live admission.
- [ ] For active legacy runs, require child reconciliation and fresh admission before continuation. Keep unknown live writers blocked and preserve all historical files for rollback.
- [ ] Make the builder declare owned outputs and detect missing/extra/drifted files. Safe cleanup may remove only confirmed generated outputs in the isolated build target; preserve unknown user files.
- [ ] Refactor smoke checks around each adapter's actual manifest, hook format, supported catalog, and installation surface. Remove Claude-only inventory assumptions from shared checks. A successful installation check must not claim hooks fired.
- [ ] Include native-library/storage availability and clean installed-bundle execution in dependency checks. Source-relative imports must not leak into installed behavior.
- [ ] Verify the repository's actual default branch and align the outcome workflow; the current workflow names `master` while this checkout is on `main`. Do not infer the remote default from the local branch alone.
- [ ] Add offline contract/build/migration checks to normal automation and a separate explicit live-host acceptance job. Missing credentials/host access yields blocked/not-run evidence, never a green runtime result.

**Validation:** `python3 -m unittest tests.test_runtime_migration -v`; `python3 scripts/build_adapter.py --all --check`; isolated install/uninstall/idempotence checks preserving unrelated agents and legacy data.

### Task 20 — Run the acceptance matrix and publish only proven support

**Files:** extend `scripts/acceptance_runtime.py` and `tests/fixtures/runtime/`; create a dated acceptance report under `AI_Codex/Agent_Reports/` with sanitized evidence manifests; update `docs/06-delivery/release-process.md` and the support table.

- [ ] Run the full offline suite, lint, role/interface/schema checks, generated-agent checks, all declared bundle checks, migrations, and isolated install checks on the supported Python/platform matrix.
- [ ] Run an installed Codex cycle from a consuming project with no source checkout: root launch, orchestrator, implementation, independent specification review, independent quality review, outcome, and root final gate.
- [ ] Run startup/resume/clear/compaction with trusted, disabled, changed, missing, and untrusted hook configurations. Confirm independent run admission rather than relying on hook prose.
- [ ] Run every negative permission case from Task 11; test overriding a template/configuration mid-run and deny continued execution until admission is refreshed.
- [ ] Run malformed/empty/duplicate/wrong-task/wrong-kind/tampered/late returns, report reuse, simultaneous dispatch, and crash between event receipt and state commit. Check the preserved bytes and task linkage.
- [ ] Run worker stall, orchestrator stall, controller crash, operator stop, approval/input wait, unavailable model, quota/rate-limit/transport failure fixtures, cancellation without acknowledgement, and process restart. Use real host events for claims about real host behavior.
- [ ] Run a recorded model escalation and verify the selected installed variant and effective settings. Simulated configuration resolution is not a live escalation result.
- [ ] Run independent live acceptance for Claude Code, Gemini, Antigravity, and the selected Cursor surface where available. Record unavailable/blocked hosts separately; do not let one host's success certify another.
- [ ] Have a fresh reviewer check the task-scoped changes and evidence against A and R. Repair findings within scope, rerun affected checks, and record exactly what remains blocked.
- [ ] Publish a final evidence manifest containing source/bundle/catalog/configuration hashes, host version/surface, commands and exit codes, scenario results, run/task/attempt/provider correlations, effective settings, and retained artifact hashes. Redact credentials and unnecessary session details.

**Final completion rule:** Codex is runtime-ready only when its required positive and negative live trials pass. Shared correctness fixes need passing regression/concurrency/crash checks. Each other adapter has its own status; unresolved platform limits remain explicit and unchecked rather than disappearing from the plan.

## Traceability to the reports

| Report issue | Tasks |
| --- | --- |
| A: missing startup and root identity | 2, 3, 6, 10, 20 |
| A: hard-coded models and required named templates; R7 schema correction | 4, 9, 20 |
| A: absent result bridge; R3 unauthenticated/reused evidence | 4, 5, 7, 12, 20 |
| A: absent monitoring; R6 undefined controller/capture/recovery ordering | 2, 3, 8, 12, 13, 20 |
| A: unenforced write boundary; R5 missing worker tool-denial acceptance | 1–3, 5, 11, 20 |
| R1: false preflight passes and bypass | 1, 4, 6, 20 |
| R2: queue transitions admit inconsistent state | 1, 5, 8, 20 |
| R4: untrusted hook cannot reject its own absence | 3, 6, 10, 20 |
| Conflicting topology, grants, timestamps, installation/provenance claims | 1, 2, 14–19 |
| Existing Gemini bundle failures and Gemini/Antigravity conflation | 15, 16, 19 |
| Claude scope/identity/override limitations | 14, 20 |
| Cursor unsupported/inherited guarantees and mixed surfaces | 17, 20 |

## Working rules for implementation

For each task, record the owner, scoped files, test command/output, evidence location, remaining limitations, and reviewed commit when one exists. Check a task off only when its acceptance conditions are met; do not count a plan, generated template, or mocked host as a live result. Keep blocked tasks open with the precise missing prerequisite and continue independent work.

Use one fresh consolidated review boundary per task. Request a scoped re-review only after that reviewer identifies a significant issue and its fix is complete; do not schedule separate specification and quality review passes by default.

Implementation may use delegated workers or an inline task loop, while preserving the same root-owned Git and review gates. This planning session does not select workers, start implementation, install plugins, or run live models.
