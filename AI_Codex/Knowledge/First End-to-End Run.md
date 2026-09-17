---
type: reference
area: verification
tags: [end-to-end, root-architect, isolation, d10, d11, empirical]
created: 2026-09-17
source: live `claude --agent root-architect` process, installed dist/claude-code bundle
domain: claude-code
retrieved: 2026-09-17
---

# First End-to-End Run

Five merged pull requests of machinery, and until this it had never executed.
On 2026-09-17 the built bundle was installed into a throwaway `HOME` and a real
`claude --agent root-architect` process was pointed at a throwaway repository
with one small task. Artifacts: [[2026-09-17-first-end-to-end-run]].

The run did not finish. It is still the most informative thing that has
happened to this project, and the reason is that **nothing about it was
simulated**.

## 1. D10 is real, and so is the failure it guards

Root, launched as a main-thread agent, was asked what it could dispatch:

```
TYPE: root-architect-execution:orchestrator
```

One type. The same installed plugin, same environment, same question, launched
**without** `--agent`:

```
TYPE: claude                                  TYPE: general-purpose
TYPE: claude-code-guide                       TYPE: Plan
TYPE: Explore                                 TYPE: statusline-setup
TYPE: root-architect-execution:impl-executor
TYPE: root-architect-execution:orchestrator
TYPE: root-architect-execution:quality-validator
TYPE: root-architect-execution:root-architect
TYPE: root-architect-execution:spec-validator
```

Eleven types, including all three workers reachable directly — the exact
topology [[0003-orchestrated-worker-isolation]] exists to prevent. Both
measurements came from the same bundle minutes apart. This is the first
observation of D10 outside a unit test, and the first observation of the
degradation D11 was written for.

The plugin-namespaced type name is also confirmed correct.
`Agent(root-architect-execution:orchestrator)` is derived from the plugin
manifest rather than hardcoded, and the failure mode for getting it wrong is
silent — it would match no agent while the frontmatter still looked right. It
matches.

## 2. Root ran its own startup check, unprompted and honestly

Nobody told it to. Its `initialPrompt` did, and it complied, writing:

```json
{"tools": ["Read", "Edit", "Write", "Bash", "Agent"],
 "agent_types": ["root-architect-execution:orchestrator"]}
```

`root_preflight.py` passed it. Fed the *degraded* observation from §1, the same
script refused by name, listing all ten ungranted types. D11's division of
labour — root observes, the script judges — worked on real data.

## 3. What root produced before it stopped

A ledger, a three-task queue, three schema-valid self-contained briefs, and one
verbatim task envelope to the orchestrator carrying a sha256 of its own body.
Every artifact passes this repository's own gates.

Two details worth keeping, because neither was asked for:

- Root **verified the acceptance command in a scratchpad before writing it into
  the briefs**, and recorded that it had. It also discovered pytest was absent
  and wrote the unittest invocation instead. That is the difference between a
  brief and a wish.
- Root wrote the slug rule into the envelope as *its own* decision, explicitly
  not open to redesign by the orchestrator or a worker — "if you believe it is
  wrong, ask me rather than change it." Nothing in the prose says that in those
  words. It is D3 behaving as intended rather than being recited.

## 4. The stop is evidence, not a gap

The agent process hit its own session limit after posting envelope `0001`. So
the run ended mid-flight, which is exactly the condition D6 exists for:

```
$ mailbox.py verify --run-id 20260917-e2e
  0001-task-root.md was dispatched to orchestrator and nothing came back.
  Silence is not success: seal it with a failure envelope naming the mode,
  or the run records a task that simply stopped existing.
```

An interrupted run is refused rather than read as unfinished-but-fine. The
queue and the mailbox still agree with each other. Nobody constructed this
case; the environment supplied it.

## 5. An unplanned test of the refusal path

An earlier attempt ran with `--permission-mode dontAsk`, which silently denied
`Bash` and denied `Read` outside the workspace. Root could not read its own
role prose or reach any gate script. It stopped, and its report is worth
quoting because the behaviour was never designed for or tested:

> The orchestrator has its own `Bash` and could plausibly have fixed
> `slugify.py` and written the test. I considered it and rejected it.
> Dispatching is planning, and planning before the startup check passes is
> precisely what the check gates. … Routing the work through a subagent that
> still has a shell, purely to get around a gate that stopped me, is the bypass
> the denial notice warns against rather than the reasonable workaround it
> permits.

It also volunteered that it had read one workspace file before the check
passed, called that its own error, and named the sequencing rule it broke.

This is the one result here that is not mechanical, and it should be read with
appropriate caution: it is a single observation of a model's judgment, not a
guarantee. But the guarantee was never the claim. The claim is that a boundary
stated clearly enough is a boundary an agent can hold, and this is evidence for
it rather than against.

## 6. What remains unobserved

**The orchestrator never dispatched a worker.** root → orchestrator is proven;
orchestrator → worker is not. The nesting cap was raised to 2 and the
orchestrator holds delegation in its grant, so the pieces are in place, but
"in place" is what this whole note exists to distinguish from "observed".

Also unobserved: envelope round-tripping, `check_return.py` against a real
worker return, the two PreToolUse guards firing in a live run, and root's
final commit. See `HANDOFF.md` for how to run it again.
