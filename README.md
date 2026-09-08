# root-architect-execution

A Claude Code plugin for running an implementation plan from a root session that
owns the plan, Git, and the ledger, and delegates every line of product code to
cheaper isolated workers.

It is the `root-architect-execution` skill plus the machinery the skill used to
only describe: schema-declared agent roles, generated host agent files, and two
PreToolUse hooks that enforce the two rules prose never managed to.

## Layout

| Path | What it is |
| --- | --- |
| `SKILL.md` | The protocol: architecture, gates, state, per-task loop, stop conditions |
| `roles/*.json` | The three worker roles — model tier, reasoning strength, tool grant, mutation class |
| `hosts/*.json` | What each host can actually express, with the date and evidence behind every claim |
| `agents/*.md` | **Generated.** The Claude Code agent files |
| `dist/<host>/` | **Generated.** Reference copies for other hosts |
| `references/agents/*.md` | The role prose, written once and pointed at, never copied |
| `references/contracts.md` | The four shapes the loop passes around |
| `schemas/*.json` | Real JSON Schemas for roles, hosts, briefs, reports, verdicts, dispatch state |
| `scripts/` | Capability gate, renderer, return gate, dispatch state |
| `hooks/` | The two guards |
| `tests/` | `python3 -m unittest discover -s tests -t .` |

## The three commands root runs

```bash
# Capability gate — before dispatching anything
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_roles.py"

# Open a dispatch from a schema-checked brief; the guards read this file
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py" open \
  --brief /tmp/brief.json --run-id 20260907-task-3

# Return gate — before treating a worker's reply as a result
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_return.py" \
  --role implementer --file /tmp/return.txt --task "..." --attempt 1
```

## What the hooks enforce

**`root_write_guard.py`** refuses a root-session `Edit`/`Write` on a path the
open dispatch owns. Root writing product code around a stalled worker is a
failed delegation with the evidence trail deleted — no RED count, no diff for
the validators, no attempt recorded. The guard is narrow about what it protects:
it fires only from the root session, and only on the open dispatch's own
`write_paths`.

It also fails closed on state it cannot trust. A dispatch record that is
unreadable, unparseable, or structurally invalid blocks the write instead of
reading as "no delegation open", and so does finding state files when
`dispatch_state` cannot be imported at all — otherwise deleting `scripts/` would
switch the guard off. The deny names the offending file and points at
`dispatch_state.py verify`, which reports every record and exits non-zero if any
is corrupt.

Malformed *hook input* is the deliberate exception: it allows. A payload the
guard cannot parse or make sense of is not evidence that a delegation is open,
and blocking on it would break every write in every project that installs this
plugin. Untrustworthy state denies; unreadable input allows.

**`worker_git_guard.py`** refuses Git mutation inside a worker, refuses any
shell at all inside the read-only validator, and refuses edits inside either
validator. Read-only Git inspection stays allowed.

Both are keyed on the `agent_type` the PreToolUse payload carries, which arrives
namespaced as `root-architect-execution:impl-executor` for a plugin-provided
agent and bare for a project-local copy. Both forms are recognised, so the
guards also cover a project that vendors these agent files directly.

## Changing a role

Never edit `agents/` or `dist/` by hand — the capability gate fails on drift,
because a hand-edited agent file silently disagrees with the manifest every
checkpoint quotes.

```bash
$EDITOR roles/impl-executor.json
python3 scripts/render_agents.py --host claude-code
python3 scripts/validate_roles.py
```

## Adding a host

See [references/agents/README.md](references/agents/README.md). The short
version: write `hosts/<name>.json`, give every capability a `verified` note —
including every `supported: false` — render, and gate. A capability the host
cannot express becomes a disclosure in the generated file, never a silent drop.

`hosts/codex.json` and `hosts/cursor.json` are carried from the reference
project and marked inherited; the capability gate prints a warning for them
until someone re-verifies them against those hosts' own documentation.
