---
title: Product Requirements
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-20
---

# Product Requirements

## Must

- Root SHALL own the governing plan, Git mutation, ledger/checkpoints, dispatch lifecycle, and final outcome decision.
- Product-code implementation SHALL be delegated to a write-scoped implementer.
- Specification validation SHALL use a fresh read-only/no-shell validator.
- Quality validation SHALL use a different fresh read-and-run validator.
- Roles SHALL be declared in `roles/*.json` and generated for hosts rather than duplicated manually.
- Host capabilities SHALL be declared and provenance-checked.
- Briefs, implementer reports, validator verdicts, role definitions, host definitions, and dispatch state SHALL conform to their schemas/contracts.
- A governed run SHALL be admitted by one authoritative controller record bound to its run, host, controller session, installed catalog, and effective configuration. A filename, role name, or truthy field is not admission evidence.
- Required dispatch capability, worker delegation/tool denial, and protected controller evidence storage SHALL be proven for the selected host before that host is described as runtime-ready. Missing proof blocks runtime acceptance.
- Each worker result SHALL be captured and bound to exactly one run, task, and immutable attempt before validation. A report for the same worker role cannot answer a different task.
- Governed message routes SHALL be root to orchestrator, orchestrator to worker, worker to orchestrator, and orchestrator to root. A worker SHALL NOT route a report or question directly to root.
- A queue transition SHALL refuse a second active task, rather than merely detecting it during later verification.
- Readable mailbox and state exports SHALL NOT authorize dispatches or results; the controller-owned record is authoritative.
- A malformed worker return SHALL receive at most one format-correction retry before stopping.
- A `DONE` implementer report SHALL contain observed RED and GREEN test evidence.
- Root SHALL NOT advance past a failed gate.
- Workers SHALL NOT commit.
- Only one dependent dispatch SHALL be open at a time.
- Unreadable, unparseable, or invalid dispatch state SHALL fail closed for protected root writes.
- Generated agent files and built bundles SHALL be reproducible and drift-checked.
- The repository outcome gate SHALL run on pushes to `master` and pull requests.

## Should

- Start workers at the cheapest plausible model/effort tier and record evidence before escalation.
- Reuse evidence from unchanged `HEAD` when explicitly marked as reused.
- Run the narrowest defensible reachable test set during task work, then run the full recorded baseline/outcome validation before completion.
- Keep handoffs compact: resolved inputs, decisions, paths, hashes, and structured results rather than accumulated transcripts.
- Keep progress recorded frequently enough to survive session/quota interruption.

## Could

- Add fully sourced host adapters beyond Claude Code and Codex.
- Add richer machine-readable ledger/checkpoint schemas.
- Add telemetry around gate timing, retries, model escalation, and failure categories.

## Won't / outside current design

- Worker-to-worker delegation.
- Unbounded retries.
- Root fallback implementation when a required role is unavailable.
- Automatic destructive Git/release operations without explicit owner approval.
- Claims of host-enforced isolation when the host cannot expose the necessary identity/capability.
- Enforcement claims for an ordinary root chat outside the governed launcher. It remains outside this runtime boundary.
