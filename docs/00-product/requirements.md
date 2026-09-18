---
title: Product Requirements
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
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
