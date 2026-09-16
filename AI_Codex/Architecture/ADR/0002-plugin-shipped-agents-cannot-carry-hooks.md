---
type: adr
area: host-adapters
tags: [adr, claude-code, hooks, distribution, enforcement]
created: 2026-09-16
---

# 0002 — Plugin-shipped agents cannot carry hooks

## Status

Accepted — 2026-09-16. Records a constraint imposed by the host, not a choice
this project made; it is accepted in the sense that the architecture already
depends on working around it. Supersedes nothing. The manifest correction it
describes landed in `9b3bf0a`.

## Context

`hosts/claude-code.json` declared `scoped_hooks` as `supported: true, field:
"hooks"` from 2026-09-07 until 2026-09-16, and the renderer turns every
capability row into a claim inside a generated agent file. The claim was false
for everything this project distributes.

`plugins-reference` states it plainly:

> "For security reasons, `hooks`, `mcpServers`, and `permissionMode` are not
> supported for plugin-shipped agents."

The field exists. It works for a hand-written agent in `.claude/agents/`. It is
ignored for an agent delivered by a plugin — and this project ships as a plugin,
through a marketplace manifest, which is the only installation path its own
README documents.

What makes this worth an ADR rather than a line in a manifest is that it is not
a fact to look up once. It removes an entire design option permanently, for as
long as the distribution channel stays what it is. Any future design that
reaches for a per-agent hook — to scope a guard to one role, to give the
implementer a different Git boundary than the validators, to attach a
`PreToolUse` matcher that only fires for one `agent_type` — is designing against
a capability this project cannot use. [[Claude Code Subagent Contract]] §4
records the full supported-field list for a plugin agent; `hooks` is absent from
it, alongside `mcpServers` and `permissionMode`.

The constraint is also why the plugin's enforcement story looks the way it does,
which was previously an undocumented accident of implementation rather than a
recorded decision:

- `hooks/hooks.json` registers **session-wide** hooks, not per-agent ones.
- Both guards therefore key on the `agent_type` that `PreToolUse` carries, and
  must distinguish root from worker at runtime rather than being installed
  differently per role.
- `worker_git_guard.role_for()` splits on the last `:` precisely because a
  plugin-delivered agent is reported as `<plugin>:<agent>`, while a
  project-local copy reports the bare name.

None of that is a workaround anyone chose for its elegance. It is the only shape
available.

## Decision

Treat the absence of per-agent hooks as a fixed architectural constraint on the
Claude Code adapter, and design enforcement around session-wide hooks keyed on
reported agent identity.

1. **`scoped_hooks` stays `supported: false` for `claude-code`** while this
   project ships as a plugin, with the plugin restriction as its `verified`
   reason. It is not a capability to re-test on the next release; only a change
   of distribution channel, or of the restriction itself, would revisit it.

2. **Enforcement that must differ per role is expressed in a session-wide hook
   that reads `agent_type`,** never by attaching a hook to an agent definition.

3. **A host adapter that *does* support per-agent hooks may use them** — the
   constraint is Claude-Code-plugin-specific and must not be generalised into
   the portable layer. `hosts/<host>.json` keeps the boolean per host for
   exactly this reason.

4. **Any future design reaching for per-agent hooks must state its distribution
   assumption explicitly.** If the answer is "only if we stop shipping as a
   plugin", that is a channel decision with its own consequences, not a
   frontmatter change.

## Consequences

**What this costs.** The guards cannot be scoped by construction, so they carry
the whole burden of telling root from worker at runtime, on every write. A bug
in that identification is a bug in the only enforcement boundary the project
has — which is why the branch that introduced this ADR spent seven commits on
the guards failing closed.

It also means the hazard in [[Claude Code Subagent Contract]] §5 is
unmitigable from inside the plugin. Plugin scope is the **lowest** precedence, so
a project-local `.claude/agents/impl-executor.md` shadows the generated agent
while still reporting `agent_type: impl-executor`. The session-wide guard keeps
firing on the name, but the grant it believes it is protecting belongs to
somebody else's file. Per-agent hooks would not have fixed that either — a
shadowed agent would carry the shadowing file's hooks — so the constraint does
not create the hazard, but it does remove the most obvious place to have caught
it.

**What it buys, honestly.** One hook file covers agents this project did not
generate, including a shadowing copy and any hand-written agent that happens to
use one of these role names. A per-agent hook would only ever have protected the
agents shipped with it.

**What is explicitly not decided here.** Whether to adopt `isolation: worktree`
(§7 finding 4), which is the other host capability that could contain a worker's
blast radius and which a plugin agent *is* permitted to set. That is a separate
decision, and [[0001-host-adapters-as-directories-with-generated-agents]] argues
it belongs in an adapter directory rather than a capability boolean.

Whether the capability schema should distinguish "unsupported" from "supported
but unusable through our channel" is also left open. Today both render as
`supported: false` with the reason in the `verified` note, which is accurate but
flattens a real distinction — a different distribution channel would revive this
one and not the others.
