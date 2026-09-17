---
type: pattern
area: orchestration
tags: [pattern, orchestration, dispatch, nesting, fallback]
created: 2026-09-17
status: specified, not built - candidate to replace D12 rather than back it up
---

# Script Dispatch

The orchestrator *agent* decides what work to hand out; a deterministic *script*
performs the dispatch by launching each worker as a **separate process**, not as
a nested subagent.

Recorded 2026-09-17 as the specified fallback to
[[0003-orchestrated-worker-isolation]] D12. **Reclassified the same day**: the
one risk that made it a fallback was measured and did not hold, so it is now a
candidate to replace D12 rather than to back it up. Not currently built.

## Why it exists

D12 raises `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` to 2 so the orchestrator — a
subagent — can dispatch workers. That rests on an environment variable whose
default is a remotely-controlled feature value. Two situations defeat it: a
managed or hermetic environment where the operator cannot set variables at all,
and a ceiling that overrides it, which the [[Subagent Nesting Cap Re-Test]]
protocol exists to detect.

## Why it may be the better design outright

Three arguments, in increasing order of weight:

1. **It needs no nesting at all**, so the remotely-defaulted cap stops being a
   dependency rather than being worked around.
2. **A script cannot drift, be re-prompted, or be prompt-injected.** An LLM
   orchestrator can, and the orchestrator is the component whose whole job is to
   be the trustworthy boundary. On the isolation requirement as the operator
   stated it — that orchestration proceed independently of root — deterministic
   code is a stronger answer than a well-instructed agent.
3. **It is deterministically testable**, which is what makes a guarantee here
   worth stating at all.

Against that: what does the orchestrator actually decide? Root owns the plan,
the loop order is fixed, `check_return.py` already validates verdict shape, and
a verdict carries its own pass or fail. "Rejected, so escalate to root" is
mechanical. There is little judgment left to house in an agent — which is D7's
point, followed to its conclusion.

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

**Worker identity survives the switch. Measured 2026-09-17, and this was the
risk that held the pattern back.**

The concern was that this repository's `PreToolUse` hooks key on the
`agent_type` the host reports for a *dispatched subagent*, and a worker launched
as its own process is a main agent in its own session. If that identity were
absent, the write guard would silently stop distinguishing root from worker — a
guarantee quietly lost, which is the failure ADR 0003 exists to prevent,
reintroduced by the fix for a different problem.

A logging `PreToolUse` hook in a throwaway workspace, across four launch shapes:

| Launch shape | `agent_type` | `agent_id` |
| --- | --- | --- |
| main agent, no `--agent` | **absent** | absent |
| dispatched subagent | present | present |
| `--agent <project agent>` | **present** | absent |
| `--agent <plugin:agent>` | **present**, namespaced | absent |

Both guards read only `agent_type`, `cwd`, `tool_input` and `tool_name`; neither
reads `agent_id`. Every key they need is present in both process cases, and
`role_for()` already strips the plugin namespace with `rsplit(":", 1)[-1]`, so a
namespaced identity resolves to the same role either way.

Note what the first row means: an agent launched with no `--agent` carries no
identity at all. The guards' root-versus-worker separation therefore rests on
`--agent` being used, not on the process being a subagent — which is exactly the
property script dispatch needs.

**Still unmeasured, and narrower than it was:** whether a *plugin-shipped*
`hooks.json` registers in such a process. The probe used a project-level hook.
`smoke_install.py` proves plugin hooks register in an ordinary session and a
`--agent` process is an ordinary session, so this is a short inference — but it
is an inference, and it should be measured before the pattern ships.

**Second-order costs**, each real but ordinary: session lifecycle to manage,
worker output captured from a process rather than returned by a tool, slower
startup per worker, and authentication that has to work in a non-interactive
child process.

## What would have to be true to adopt it

1. ~~The nesting cap is unusable.~~ **No longer a precondition.** This pattern
   does not use nested delegation at all, so it is available whatever the cap
   says — and adopting it would remove D12's dependency on a remotely-defaulted
   environment variable rather than working around it.
2. ~~Worker identity reaches the guard.~~ **Measured and satisfied**, see above.
3. The launch mechanism is sourced for each host in scope, to D1's standard.
   Only `claude-code` is, today.
4. A plugin-shipped `hooks.json` is confirmed to register in a `--agent`
   process.

Item 2 was the one that could have made this pattern cost more than it saves.
It did not. What remains is item 3, which is portability work rather than a
risk to the pattern itself, and item 4, which is one probe.
