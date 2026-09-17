---
type: adr
area: orchestration
tags: [adr, orchestration, isolation, host-interfaces, provenance]
created: 2026-09-17
---

# 0003 — Orchestrated worker isolation

## Status

Accepted, in progress — 2026-09-17. Supersedes nothing. Constrains
[[0001-host-adapters-as-directories-with-generated-agents]] by inserting work
before its step 3: the interface files change what a bundle must contain, so
migrating first would move files this ADR redefines.

Sequencing status, against the five phases below:

0. Branch reset after PR #2 merged — **done**.
1. Interface files and their gate — **done** (this change).
2. Role dependence checked against sourced capability — **done** (this change).
3. The root agent as a main-thread agent — **done**. The research replaced the
   decision it was meant to confirm (see D11) and surfaced the nesting cap,
   resolved as D12; the build followed on 2026-09-17.
4. Orchestrator, workers, mailbox — **done**. The mailbox is built and its four
   properties are enforced and mutation-tested. The orchestrator role exists,
   renders, and registers on the host. The job queue is built, and `verify`
   cross-checks it against the mailbox so the two records cannot drift
   unnoticed. Root is built: it renders as a main-thread agent with a
   host-enforced dispatch scope (D10), and `root_preflight.py` refuses a
   session where that scope did not bind (D11).
5. `thermos-claude` disposition — **done**: PR #1 closed unmerged, 2026-09-17.

> **Run 2026-09-17.** The topology was exercised for the first time by a real
> `claude --agent root-architect` process against an installed bundle. D10 and
> D11 are now empirically confirmed rather than unit-tested: root saw exactly
> `root-architect-execution:orchestrator` as its dispatchable type, the same
> bundle launched without `--agent` saw eleven types including all three
> workers, and `root_preflight.py` passed the first observation and refused the
> second. The run stopped at the agent process's own session limit after the
> task envelope was posted, so **orchestrator → worker remains unobserved**.
> Findings: [[First End-to-End Run]]. Next steps: `HANDOFF.md`.

## Context

Two review sessions, four reviewer passes, one pull request. The subject was
whether a reviewer agent was read-only. Every position taken rested on
inference about what the host supports, and two of them were confidently
wrong in different directions. Nothing in either repository could settle it,
because no artifact described what any host actually offers.

The pull request's central claim — "read-only by construction, not by
request" — was false as written: its `mcp__github__*` grant spans a server
whose tools include `merge_pull_request` and `push_files`. That is the failure
mode this project exists to reject, committed in the document asserting the
guarantee.

Separately, the operator's isolation requirement was misread during design.
The requirement is that **orchestration proceeds independently of the root
session**, so root cannot interfere; root relays operator answers and nothing
else. Work does not flow root → worker. It flows root → orchestrator →
workers, and the orchestrator owns dispatch.

## Decision

**D1 — `adapters/<host>/agent-interface.json` declares what a host offers, per
claim, with provenance.** Levels, weakest to strongest: `unsourced`,
`corpus-derived`, `empirically-verified`, `first-party-source`,
`first-party-doc`. A claim may be relied upon only at the strength of its
weakest source, and `unsourced` bears no weight at all.

`first-party-*` requires the source's own words verbatim; a paraphrase is
where inference re-enters. `corpus-derived` requires a sample size, because
a corpus shows what is **used**, never what is **supported**. This project
asserted otherwise mid-design — reading the absence of a `tools` key across
13 Cursor agent files as absence from Cursor's interface — and was corrected
by the operator. The enum exists so that mistake is unrepresentable.

**D2 — The capability gating the topology is nested delegation**, not tool
restriction. A host supports this architecture iff an agent that was itself
dispatched can dispatch in turn.

> **Amended 2026-09-17, after Phase 3 research.** On Claude Code this is not a
> host capability at all. It is a runtime cap, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`,
> whose default comes from a **remotely-controlled feature value**
> (`maxSubagentSpawnDepthFromGrowthBook`). It can differ between environments
> and change with no local change whatsoever. Measured at **1** in the
> environment this was written in, where a dispatched subagent receives no
> `Agent` tool at all. A capability that can be revoked remotely cannot be
> declared once and relied on; see Risks.

**D3 — Topology is Operator → Root → Orchestrator → Workers.** Root holds the
task and the operator channel. It does not dispatch, gather, or synthesize.

**D4 — The mailbox is filesystem envelopes** on hosts that have no native one.
Antigravity does have one (`send_message`, with queued when-idle delivery), so
there the envelope is a portability shim over something the host does better;
the adapter must not reimplement it.

**D5 — Envelopes are verbatim and append-only.** Cursor's `orchestrate` states
the reason plainly: *"Don't enrich or sanitize; the planner needs the worker's
words unfiltered."*

**D6 — Silence is never success.** A worker that terminates without an envelope
gets a synthetic failure envelope naming the failure mode, written by the
orchestrator.

**D7 — The dispatch loop is deterministic code, not agent judgment.** Cursor's
rationale, adopted: *"Long-running agent loops drift; a script with a JSON
state file keeps its footing."* It also makes the boundary testable, which is
the only thing that makes a guarantee here worth stating.

**D8 — Workers hold no delegation; the orchestrator does.** Derived from D2
plus the worker criteria: constrained grant, independent model and effort,
fresh context, no nested delegation.

The orchestrator is an **agent**, not a script, and the distinction is not
incidental. It receives each worker's output and judges it, decides what to
delegate next, sends questions to root through the mailbox, and decides on the
answers it receives. D7's deterministic code is the job queue it drives — the
mechanics of ordering, state and retry bookkeeping — not a substitute for that
judgment. Reading D7 as "the orchestrator is a script" inverts the design.

**D9 — Workers never write their own envelopes.** This resolves a
contradiction that broke the closed pull request: a worker constrained enough
to be trusted holds no write tool, so it *cannot* write a handoff. Cursor's
answer is that the dispatching script captures the worker's final message and
persists it. The worker returns a report; the orchestrator writes the file.
The constraint and the protocol stop fighting.

**D10 — Root ships as a main-thread agent.** Full consequences, including what
this means for the product rather than the configuration, are recorded in
[[Root as a Main-Thread Agent]].

> **Built 2026-09-17.** `roles/root-architect.json` declares `kind: root` and a
> `launch` block naming the one type root may dispatch; the renderer turns that
> into `tools: ..., Agent(<plugin>:orchestrator)` on a host that declares it can
> express the scope. Three consequences were only visible once it existed:
>
> - Every derivation in this repository that reasoned about delegation assumed
>   the role was dispatched, and said so in a comment. Root is not, and a
>   dispatched delegator needs NESTED delegation where root needs only
>   delegation. The interface gate caught its own stale assumption by refusing
>   root on Cursor for resting on nesting root does not use.
> - The type name is derived from the plugin manifest, because a wrong one
>   fails silently: it matches no agent, and root's frontmatter still looks
>   entirely correct.
> - `omitClaudeMd` is not available to root. The knowledge note claimed it was;
>   the doc's own words say it is *ignored* for a main-session agent. Corrected
>   there. Root inherits the operator's CLAUDE.md and cannot suppress it, which
>   is a product constraint rather than a setting.

**D11 — The fail-closed check asks about capability, not identity.** Phase 3
set out to find a way for root to answer *"am I the main thread?"*. It cannot:
a dispatched subagent's environment is byte-identical to its parent's, all 49
`CLAUDE_*` variables included, and the host tracks `agentDepth` internally
without surfacing it.

The question was the wrong one. What root needs to know is not its identity but
whether the guarantee it is about to claim actually holds — and **that is
observable**. An agent can see its own toolset. So root checks, at startup,
that `Agent` is present and that the only dispatchable type is the
orchestrator. If `Agent` is missing, the depth cap or the launch mode has
already taken it away. If other types are reachable, `Agent(orchestrator)` did
not bind. Either way the boundary is not in force, and root refuses to
orchestrate.

This is weaker than a host guarantee: it relies on the agent reading its own
context honestly rather than on the runtime refusing. It is nonetheless a real
check against the real failure, and it degrades in the safe direction — every
way of losing the capability also makes the check fail.

> **Built 2026-09-17** as `scripts/root_preflight.py`, on one division of
> labour: **root supplies the observation, the script supplies the verdict.** A
> check whose subject also decides whether it passed is not a check, and a
> judgment written down is a judgment that can be tested — which the same
> judgment held in an agent's head never can be.
>
> It is a gate rather than advice because `job_queue.init` refuses a run with no
> passing record for it. Skipping the check therefore does not produce a run
> that merely lacks a record; it produces no run.
>
> Scope is exactly the two questions above. The rest of the observed toolset is
> recorded verbatim and not judged: hosts add tools of their own, so "observed
> something ungranted" would fire on ordinary sessions, and a check that cries
> wolf is a check somebody turns off. A refusal is written to disk as well as a
> pass, so a refused run and an unchecked one do not look the same afterwards.

## Evidence base

Sourced 2026-09-17. Nested delegation, which is D2's gate:

| Host | Nested | Gate | Provenance |
|---|---|---|---|
| claude-code | yes | `Agent` in the allowlist **and** the nesting cap raised — see D12 | empirically verified |
| antigravity | yes | `invoke_subagent` in the dispatched agent's own allowlist | first-party changelog |
| codex | yes | none found | first-party source |
| cursor | **unknown** | — | **unsourced** |

Cursor's prose documentation is unreachable from this environment and its SDK
reference describes only main-agent-to-subagent dispatch. Its guidance
discourages the shape — *"Deeply nested agents calling agents calling agents
chains. One level of sub-agents is almost always enough"* — but counsel is not
a capability statement and must not be read as either a yes or a no. Under D1,
no role requiring nesting may target Cursor until this is sourced.

Codex restricts capability through a sandbox profile reached from a role's
config layer rather than through a tool list. A portable role vocabulary that
knows only about allowlists will express that host badly.

## Consequences

`scripts/validate_interfaces.py` joins the outcome gate. It refuses a role that
depends on an unsourced capability, and refuses drift between an interface file
and the `hosts/*.json` the renderer reads — the renderer trusts the manifest,
so that drift is what decides whether a generated agent states a guarantee or a
disclosure.

A role that withholds delegation on a host with no tool allowlist is **not** an
error: `render_agents` already discloses that the grant is an instruction only.
Disclosing an unenforceable guarantee is this repository's existing answer, and
the new gate was corrected during implementation for rejecting it.

## Risks

**The topology needs a raised nesting cap, and that is now an install
prerequisite.** Measured 2026-09-17: at the default
`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`, a dispatched subagent asking for the
`Agent` tool is told *"No such tool available: Agent. Agent is disabled for
this session, in subagents as well as here."* An orchestrator is a subagent, so
at depth 1 it cannot dispatch workers and root → orchestrator → workers
collapses.

**D12 — The cap is raised to 2 as a documented install prerequisite.** Chosen
by the operator over the two alternatives (workers as separate processes
driven by D7's dispatch script; or two levels with root dispatching directly,
abandoning D3). Verified before adoption rather than after, by an A/B probe of
two fresh `claude -p` processes differing only in that variable: at 2 the
dispatched subagent holds `Agent`; at 1 it does not. The variable is read at
process start, so exporting it into a running session does nothing.

What makes this acceptable despite resting on an environment variable is D11.
Root checks the capability at startup and refuses to orchestrate without it, so
an unset prerequisite stops the run with a reason rather than silently
producing an unisolated one. A fragile prerequisite that announces itself is a
different risk from one that degrades quietly.

What it does not fix: the variable's default remains a remotely-controlled
feature value. An environment where the operator cannot set variables at all
has no path under D12. The fallback there is specified in
[[Script Dispatch]] — the envelope protocol is deliberately independent of how
a worker is launched, so D5, D6 and D9 hold either way and that migration
rewrites dispatch while leaving the protocol intact.

That pattern's one unmeasured risk — whether a worker launched as its own
process still reports the `agent_type` this repository's guards key on — **was
measured on 2026-09-17 and does not hold**. Identity travels with `--agent`,
not with being a subagent, so the guards keep working either way. The fallback
is therefore known viable rather than merely plausible.

It remains a fallback. A revision of that note briefly argued it could replace
D12 by moving dispatch into a script; the operator corrected it. **The
orchestrator is an agent** — it judges what workers return, chooses what to
delegate next, puts questions to root and decides on the answers. D7's
deterministic code is the job queue beneath it. Script dispatch changes only how
a worker is launched, and is reached for only when nesting is unavailable.

**A remotely-defaulted cap cannot be declared once.** Because the default is a
feature value rather than a release constant, an interface file recording
"nested delegation: yes" can become false without any version changing. The
interface records the measurement and its date; it cannot promise the
measurement still holds. Any check that matters must run at startup, which is
what D11 does.

**D10's identity check has no mechanism** — see D11, which replaces it with a
capability check. The negative is empirically verified for environment
variables specifically; an undocumented API or hook payload field could still
carry the information.

**Root is the sensor in its own check**, and an instrument cannot catch a sensor
that lies. What D11 catches is every *accidental* way the boundary goes missing,
which is every way it has actually gone missing so far and the only way it goes
missing without somebody choosing to. The module says so in its own words rather
than leaving a reader to infer the limit.

**Root inherits the operator's CLAUDE.md with no way to suppress it**, per the
D10 note above. Root's own instructions have to be specific enough to win a
conflict with it, and a contradiction between the two is something root raises
with the operator rather than resolving silently.

**Cursor counsels against this shape**, quoted above. Our motive is isolation
rather than decomposition depth, which is not what that warning addresses —
but the warning is on the record here rather than discovered later.

**The topology is three levels deep.** Every level is a place a report can be
summarized, and D5 exists because summarizing is exactly how a worker's
finding reaches the operator distorted.
