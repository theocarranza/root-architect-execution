---
type: protocol
area: host-capabilities
tags: [protocol, claude-code, nesting, subagents, re-test]
created: 2026-09-17
domain: claude-code
---

# Subagent Nesting Cap Re-Test

How to re-measure whether Claude Code still allows two levels of agent nesting,
and why this one measurement needs a standing protocol when the others do not.

## Why this needs re-testing at all

Every other claim in `adapters/claude-code/agent-interface.json` is stable
between releases: a documented frontmatter field does not stop existing without
a version change. This one does.

`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` has no release-constant default. Absent
an explicit setting the value comes from `maxSubagentSpawnDepthFromGrowthBook`,
a remotely-controlled feature value. So the capability
[[0003-orchestrated-worker-isolation]] D12 depends on can change with **no local
change at all** — no upgrade, no config edit, nothing a diff would show.

An interface file records a measurement and its date. It cannot promise the
measurement still holds. This protocol is how the measurement gets refreshed.

## When to run it

- Before trusting `nested delegation: yes` for `claude-code` after any gap in
  work longer than a few weeks.
- On any new environment: a web session, a different machine, a CI runner, a
  managed or hermetic environment. The measured value differed per environment
  when first recorded.
- Whenever an orchestrator reports that it holds no `Agent` tool, which is the
  symptom this protocol explains.

## The probe

Two fresh processes differing in exactly one variable. Fresh matters: the value
is read at process start, so exporting it into a running session proves
nothing.

```bash
# Should print HAVE_AGENT
CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2 claude -p \
  'Use the Agent tool with subagent_type "general-purpose" and this exact prompt:
   "Report only whether the Agent tool is in your toolset: answer HAVE_AGENT or
   NO_AGENT, one word." Then reply with only what the subagent said.' \
  --output-format text

# Should print NO_AGENT
CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1 claude -p '<same prompt>' --output-format text
```

**Run both.** The second is not ceremony: without it, a `HAVE_AGENT` proves only
that nesting works somehow, not that this variable is what governs it. A one-
sided probe would pass identically if the cap were being set by something else
entirely, and the install prerequisite would then be advice we could not
support.

## Reading the result

| Outcome | Meaning |
| --- | --- |
| `2`→HAVE_AGENT, `1`→NO_AGENT | As recorded. D12 holds, the prerequisite works. |
| Both HAVE_AGENT | The floor moved above 1. The prerequisite is now redundant, not wrong — leave it set, and record the new floor. |
| Both NO_AGENT | **D12 has failed.** Either the variable stopped governing the cap, or a ceiling now overrides it. Orchestration cannot run; ADR 0003's fallback (dispatch by script, workers as separate processes) becomes the live option. |
| `2`→NO_AGENT, `1`→HAVE_AGENT | Inverted, which should be impossible. Suspect the probe, not the host: check that both processes really started fresh and that no wrapper is rewriting the environment. |

## After running it

Update the `delegation.nested.provenance` block in
`adapters/claude-code/agent-interface.json` with the new date and the observed
pair, keeping the level at `empirically-verified`. Do not silently leave an old
date in place next to a fresh belief — the date is the part that tells the next
reader how much to trust the claim.

If the outcome is `Both NO_AGENT`, amend ADR 0003 before doing anything else.
Continuing to ship a plugin whose ledger claims an isolation guarantee the host
has withdrawn is precisely the failure that ADR exists to prevent.

## Provenance

The original measurement, 2026-09-17: `2`→`HAVE_AGENT`, `1`→`NO_AGENT`, in a
Claude Code web session where the ambient default was `1`. The refusal message
on the other path — where the tool is offered and then refused rather than
withheld — is carried in the installed binary under the ids
`subagent_depth_cap` and `depth_limit`:

> Subagent nesting limit reached (depth …). Complete this task directly using
> your tools instead of spawning another agent. If the user explicitly requested
> deeper nesting, ask them to raise CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH
