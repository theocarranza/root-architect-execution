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
3. The root agent as a main-thread agent — **not started**, and blocked on an
   unsourced prerequisite recorded under Risks.
4. Orchestrator, workers, mailbox — **not started**.
5. `thermos-claude` disposition — **done**: PR #1 closed unmerged, 2026-09-17.

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

**D9 — Workers never write their own envelopes.** This resolves a
contradiction that broke the closed pull request: a worker constrained enough
to be trusted holds no write tool, so it *cannot* write a handoff. Cursor's
answer is that the dispatching script captures the worker's final message and
persists it. The worker returns a report; the orchestrator writes the file.
The constraint and the protocol stop fighting.

**D10 — Root ships as a main-thread agent.** Full consequences, including what
this means for the product rather than the configuration, are recorded in
[[Root as a Main-Thread Agent]].

## Evidence base

Sourced 2026-09-17. Nested delegation, which is D2's gate:

| Host | Nested | Gate | Provenance |
|---|---|---|---|
| claude-code | yes | `Agent` in the dispatched agent's own allowlist | first-party doc |
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

**D10's fail-closed check is unsourced.** Root must detect at startup that it
is not the main thread and refuse to orchestrate, because
`tools: Agent(orchestrator)` silently does not bind outside that mode. No
mechanism by which a running agent can observe whether it is the main thread
was found in either Claude Code reference. It is recorded in that host's
interface file as `main_thread_self_detection`, `supported: false`,
`unsourced`. Phase 3 opens by sourcing it. If no mechanism exists, D10's
enforcement is weaker than stated and this ADR is amended to say so rather
than shipping the claim.

**Cursor counsels against this shape**, quoted above. Our motive is isolation
rather than decomposition depth, which is not what that warning addresses —
but the warning is on the record here rather than discovered later.

**The topology is three levels deep.** Every level is a place a report can be
summarized, and D5 exists because summarizing is exactly how a worker's
finding reaches the operator distorted.
