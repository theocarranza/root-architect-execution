---
type: reference
area: product-architecture
tags: [claude-code, main-thread-agent, root-architect, isolation, product-shape]
created: 2026-09-17
source: https://code.claude.com/docs/en/sub-agents + https://code.claude.com/docs/en/plugins-reference
domain: claude-code
retrieved: 2026-09-17
---

# Root as a Main-Thread Agent

What it means — for the product, not just the config — that the root architect
ships as a Claude Code agent launched as the main thread rather than as a skill
invoked inside an ordinary session.

Recorded 2026-09-17 during the architecture pass that produced
[[0003-orchestrated-worker-isolation]] (D10). Written as research; no code change
at the time. The operator asked for this specifically, because the consequences
below are the product decision, and the frontmatter is only its expression.

## 1. The decision

The root architect is an agent definition launched as the main thread —
`claude --agent root-architect`, or the equivalent `agent` setting — not a skill
a session invokes.

## 2. Why it is forced, not preferred

`tools: Agent(orchestrator)` is the only mechanism that makes the
root → orchestrator → workers topology **enforced** rather than etiquette, and
the host documents that it binds only for main-thread agents:

> The type list inside parentheses applies only to agents running as the main
> thread with `claude --agent`. In subagent definitions, the list is ignored.

`initialPrompt` is documented as *"only used when agent runs as main session via
`--agent` or `agent` setting."* Claude Code treats a main-thread agent as a
distinct execution mode, and the guarantees this architecture depends on exist
only inside that mode.

> **Corrected 2026-09-17, while building D10.** This paragraph originally
> bracketed `omitClaudeMd` with `initialPrompt` as *"only used"* in main-session
> mode. That is backwards, and the correction is in the doc's own words, already
> recorded in `adapters/claude-code/agent-interface.json`: *"Ignored when agent
> runs as main session via --agent or agent setting."* The two fields are scoped
> in opposite directions — one exists only for a main-thread agent, the other
> exists for everything except one. §3's CLAUDE.md paragraph rested on the wrong
> half and is corrected there too.

## 3. What this means for the product

### It becomes a mode, not a command

The operator doesn't install a plugin and type a slash command — they start a
session **as** the root architect. There is no "use root-architect for this one
task" mid-conversation. The whole session is under its constraints or none of it
is.

### Discoverability drops, and that is the trade

A plugin agent appears in the `@`-mention typeahead. A main-thread agent must be
chosen at launch and will not be found by browsing. The product has to be
something an operator deliberately starts. That suits a root that owns plan, Git
and ledger, and it rules out casual adoption.

### Root's frontmatter becomes the security boundary

A short, auditable, testable artifact — a declared tool list, checkable by
`render_agents --check` against the host's interface file. This is precisely the
part that `thermos-claude` PR #1 asserted in prose and could not back.

### It forecloses the thermos shape entirely

Thermos is a skill that orchestrates from inside whatever session invokes it.
Under this decision that shape is unreachable: root cannot be a skill. For
`thermos-claude` to run under this architecture, its orchestrator skill must
become an orchestrator *agent* that root spawns. PR #1 is not a step toward
that — it is a refinement of the shape being abandoned.

### The fallback must fail closed

If the plugin is installed and invoked without `--agent`, `Agent(orchestrator)`
does not bind and root can spawn anything. **That degradation is invisible.** The
product must detect at startup that it is not the main thread and refuse to
orchestrate, rather than proceeding with the boundary as convention.

Silently degraded isolation is worse than none, because the ledger would then
record a guarantee that was never in force — the exact failure this architecture
exists to prevent.

### CLAUDE.md becomes a deliberate choice

A main-thread agent loads user, project and local CLAUDE.md, and **has no way
not to**. Root inherits whatever the operator's repo says, which can conflict
with its own protocol.

> **Corrected 2026-09-17.** This said `omitClaudeMd: true` was "the setting
> adopted for root". It cannot be: the field is *"Ignored when agent runs as
> main session via --agent or agent setting"*, which is precisely how root runs.
> The escape hatch this section described does not exist for the one agent it
> was described for.

So this is a live constraint on the product rather than a setting. Root's
protocol has to survive an operator CLAUDE.md it did not write and cannot
suppress — which argues for root's own instructions being specific enough to win
a conflict, and for treating a contradiction between the two as something root
raises with the operator rather than resolves silently. The relevant field for
workers is unaffected: a dispatched agent's `omitClaudeMd: true` does what it
says. Requires v2.1.271+. Managed policy files load regardless, everywhere.

## 4. Consequences for the adapter work

A host supports this product shape only if it can express "this agent may spawn
only this other agent." That is a per-host capability question, answered in
`adapters/<host>/agent-interface.json` with provenance, never inferred. See
[[Claude Code Subagent Contract]] §3 for the field-level contract on this host.

## 5. Provenance of this note

First-party documentation, fetched 2026-09-17:

- `https://code.claude.com/docs/en/sub-agents` — `Agent(type)` main-thread
  restriction; `initialPrompt` main-session scoping; `omitClaudeMd` default,
  its main-session exclusion, and the managed-policy exception.
- `https://code.claude.com/docs/en/plugins-reference` — plugin-shipped agent
  field support.

§3's product consequences are reasoned from those documented mechanics, not
quoted from them. They are design judgment and should be read as such; the
mechanics they rest on are sourced above and are the part that must not drift.
