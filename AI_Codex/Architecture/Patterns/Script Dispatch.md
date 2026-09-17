---
type: pattern
area: orchestration
tags: [pattern, orchestration, dispatch, nesting, fallback]
created: 2026-09-17
status: specified, not built
---

# Script Dispatch

The orchestrator *agent* decides what work to hand out; a deterministic *script*
performs the dispatch by launching each worker as a **separate process**, not as
a nested subagent.

Recorded 2026-09-17 as the specified fallback to
[[0003-orchestrated-worker-isolation]] D12. Not currently built. Written down
now, while the reasoning is intact, so that the environment that forces the
switch does not also force a rushed re-derivation of it.

## Why it exists

D12 raises `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` to 2 so the orchestrator — a
subagent — can dispatch workers. That rests on an environment variable whose
default is a remotely-controlled feature value. Two situations defeat it:

- A managed, hermetic or locked-down environment where the operator cannot set
  environment variables at all.
- A ceiling that overrides the variable, which the
  [[Subagent Nesting Cap Re-Test]] protocol is written to detect.

In either case D12 has no path and this pattern is the live option.

## Why it is not merely a workaround

[[0003-orchestrated-worker-isolation]] D7 already decided that the dispatch loop
is deterministic code rather than agent judgment, adopting Cursor's reasoning
verbatim: *"Long-running agent loops drift; a script with a JSON state file
keeps its footing."*

This pattern is D7 followed all the way. Once dispatch is a script, the script
may as well launch processes; nesting depth stops being a constraint because a
freshly launched process starts at depth 0 with its own budget. The cap becomes
irrelevant rather than raised.

Cursor's own `orchestrate` plugin is this pattern in production: the planner
writes `plan.json`, `scripts/cli.ts` performs the spawns, and each worker's
final message is persisted verbatim to `handoffs/<task-name>.md`.

## What stays identical

The whole envelope protocol. This is the property that makes the fallback cheap
and it is deliberate, not luck — none of these decisions mentions how a worker
is launched:

- **D4** filesystem envelopes
- **D5** verbatim and append-only
- **D6** synthetic failure envelope when a worker dies silent
- **D9** workers never write their own envelopes; the dispatcher persists the
  returned report

Switching to this pattern rewrites dispatch and leaves the protocol untouched.
That is why D12 was safe to adopt first: the cheap option does not lock
anything in.

## What changes, and the part that bites

**Launch mechanism is per host**, which is the pattern's real cost:

| Host | Mechanism | Provenance |
| --- | --- | --- |
| claude-code | `claude -p --agent <worker>` as a subprocess | empirically verified 2026-09-17 — the nesting-cap probe used exactly this, and the launched process could itself dispatch |
| codex | `codex exec`, with the worker's role config layer | unsourced — `docs/exec.md` is a stub behind blocked egress |
| cursor | Cloud agents through the SDK; sub-agents are cloud-only at v1 | first-party, `cursor/plugins@e31650e` |
| antigravity | `agy` CLI, mechanism unread | unsourced |

**Worker identity stops being a subagent fact, and that breaks a guard.** This
repository's `PreToolUse` hooks key on the `agent_type` the host reports for a
*dispatched subagent*. A worker launched as its own process is a main agent in
its own session, so it is not obvious that the same identity reaches the guard —
and the identity-aware write separation is the enforcement that
[[Claude Code Subagent Contract]] treats as load-bearing.

**This must be probed before the pattern is adopted, not after.** If the
identity is absent, the write guard silently stops distinguishing root from
worker, which is a guarantee quietly lost — the failure mode ADR 0003 exists to
prevent, reintroduced by the fix for a different problem. Status: unsourced.

**Second-order costs**, each real but ordinary: session lifecycle to manage,
worker output captured from a process rather than returned by a tool, slower
startup per worker, and authentication that has to work in a non-interactive
child process.

## What would have to be true to adopt it

1. The nesting cap is unusable — the re-test protocol reports `Both NO_AGENT`,
   or the target environment forbids setting the variable.
2. Worker identity in `PreToolUse` has been probed for a separately-launched
   process, and either reaches the guard or has a replacement that does.
3. The launch mechanism is sourced for each host in scope, to D1's standard.

Item 2 is the one that could make this pattern cost more than it saves, and it
is the one nobody has measured.
