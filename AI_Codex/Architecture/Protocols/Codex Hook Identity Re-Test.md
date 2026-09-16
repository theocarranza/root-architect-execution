---
type: protocol
area: host-capabilities
tags: [codex, hooks, enforcement, re-test, dated-capability-gap]
created: 2026-09-16
---

# Codex Hook Identity Re-Test

How to re-check the claim that **Codex cannot distinguish root from worker
during `PreToolUse`**, and what would have to be true before the boundary is
allowed to become hook-enforced there.

This is a **dated capability gap, not a permanent design assumption.** It is
written down so it gets re-tested on evidence rather than inherited as folklore.
`bcc8e1a` references this checklist in its commit message; it previously existed
only in `.root-architect/ledger/2026-09-08-codex-host-support.md`, which is
gitignored, so nobody cloning the repository could read the thing the commit
pointed at.

## Baseline, 2026-09-08

Official Codex hook documentation describes worker identity on `SubagentStart`
and `SubagentStop`, but documents no `agent_type`, `agent_id`, or other
trustworthy worker-correlation key on `PreToolUse`.

Documented-shape probes therefore give root and a writable worker
**indistinguishable `apply_patch` payloads**. That leaves no useful hook policy:

| Policy | Result |
| --- | --- |
| Global deny | Blocks the implementer from the exact files delegated to it — the workflow becomes unusable |
| Global allow | Cannot constrain root at all |

So `hosts/codex.json` records `scoped_hooks: supported: false`, and the
root-versus-worker write boundary is disclosed in every generated Codex agent as
instructional and diff-reviewed rather than enforced.

Validator read-only isolation is **not** in this category: `sandbox_mode =
"read-only"` is independently host-enforced and must be preserved regardless of
how this re-test turns out.

## When to run this

Before either of:

- the next Codex CLI or plugin release that touches hooks or subagents, or
- any change to this project's hook architecture that would rely on Codex
  identity.

## Checklist

1. Re-read the official Codex hooks and custom-subagent documentation.
2. Check whether `PreToolUse` has gained `agent_type`, `agent_id`, parent/child
   session identity, or a documented correlation with `SubagentStart`.
3. **Capture real payloads** from a disposable installed plugin session — root,
   `impl-executor`, `spec-validator` and `quality-validator` — and read them.
   Do not infer capability from field names appearing in documentation.
4. Accept hook enforcement **only if** the correlation is documented, stable,
   and covered by tests proving all three on the same delegated path:
   - root deny
   - implementer allow
   - validator deny
5. Until every part of 4 holds, keep the separation explicitly instructional and
   diff-reviewed, and keep `sandbox_mode = "read-only"` on the validator roles.

## If it passes

`hosts/codex.json` gains `scoped_hooks: supported: true` with the observed
payload as its `verified` evidence, the Codex-specific disclosure in
`scripts/render_agents.py` is removed, and `dist/codex/` regenerates. The
capability gate and `--check` will refuse to let those drift apart.

Note that `apply_patch` is already present in the worker guard's validator deny
sets and in the hook matcher, so the policy is stated in one place for whichever
host grows the identity signal first. That was deliberate — see `bcc8e1a`.

## Related

- [[Claude Code Subagent Contract]] — the equivalent contract for the other
  host, where identity *is* available and the constraint is different
- [[0002-plugin-shipped-agents-cannot-carry-hooks]] — why Claude Code reaches
  the same session-wide-hooks shape by a completely different route
