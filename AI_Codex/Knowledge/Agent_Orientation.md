---
type: orientation
tags: [orientation]
created: 2026-09-14
---

# Agent Orientation

Read this first. It says where things are; the README says how they are shaped.

## What this repository is

A Claude Code plugin implementing the root-architect execution protocol: a root
session keeps the plan, Git and the ledger, while schema-declared isolated
workers implement and review. Two PreToolUse hooks enforce what prose only
asked for — root cannot edit a path it has delegated, and workers cannot touch
Git.

The load-bearing idea is that **a capability the host cannot enforce is
disclosed, never assumed**. `roles/*.json` declare a role once; `hosts/*.json`
declare what each host can actually enforce; `scripts/render_agents.py`
generates per-host agent files and writes an honest "Enforcement" section for
everything the host will not enforce.

## Where to look

| Question | Where |
| --- | --- |
| What is the protocol? | `SKILL.md` at the repo root |
| What does a role grant? | `roles/*.json`, prose in `references/agents/` |
| What does a host enforce? | `hosts/*.json` |
| Why was something decided? | `Architecture/ADR/` here |
| What happened in a run? | `Agent_Sessions/` here; run state in `.root-architect/` |
| What is in flight? | `Tickets/Active/` here |

## Commands

| Command | Purpose |
| --- | --- |
| `/agent-continuity:init-workspace` | Scaffold the CLAUDE.md tree. |
| `/agent-continuity:init-vault` | Scaffold this vault skeleton. |
| `/agent-continuity:init-rules` | Drop starter `.agent/rules/*.md` templates. |
| `/agent-continuity:mine-bases` | Backfill frontmatter + Base dashboards (software-project). |
| `/agent-continuity:query-vault` | Read-only live query of the vault via the Obsidian CLI. |
| `/agent-continuity:canvas-map` | Generate an Architecture Canvas relationship map. |
| `/agent-continuity:research-ingest` | Ingest a URL into a source-stamped reference note. |
| `/agent-continuity:vault-lint` | Audit the vault against its archetype spec. |

## Session protocol

Sessions chain through `next:`. The workspace session gate blocks writes when the
newest open session for the current branch is older than 8 hours — close it by
pointing `next:` at a successor, then open a new one. The gate reads frontmatter
(`timestamp`, `branch`, `status`), not filenames.
