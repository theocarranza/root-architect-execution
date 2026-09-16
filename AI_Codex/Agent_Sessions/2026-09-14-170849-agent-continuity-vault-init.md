---
date: 2026-09-14
type: session
timestamp: 2026-09-14T17:08:49-03:00
project: root-architect-execution
branch: fix/guard-fails-closed-on-untrusted-dispatch-state
status: active
tags: [agent-session, root-architect-execution, vault, agent-continuity, host-adapters]
next: null
---

# Agent Session Log (root-architect-execution)

Continues [[2026-09-08-115328-guard-fail-open-repair-codex-host]], which the
8-hour workspace session gate had left open since 2026-09-08 rather than closing
on task completion. That workstream did complete; this log records the close.

## Carried forward from the previous session

The uncommitted tree that log describes is now landed and published:

- `904f9aa` — the four remaining write-guard fail-opens
- `bcc8e1a` — Codex host support with explicit agent materialization
- `a7ca713` — the seven defects a branch-wide adversarial review found

Pushed to `theocarranza/root-architect-execution` (private), branch
`fix/guard-fails-closed-on-untrusted-dispatch-state`. Nothing is open against
that workstream. Full detail in
`.root-architect/ledger/2026-09-08-codex-host-support.md` under "Step G5" and
"Commit prep".

## Session intent

Two threads, in order:

1. **Adopt `AI_Codex/` as an agent-continuity `software-project` vault.** It held
   three session logs and no marker, so it was a session folder rather than a
   vault. Scaffold the archetype skeleton into it, add the marker, migrate the
   legacy logs onto the spec's naming and frontmatter, and track it in git — the
   project's reasoning currently lives entirely in gitignored paths and does not
   survive a clone.

2. **Host adapters and an architecture review.** The Claude subagent contract was
   re-read from official documentation this session (`sub-agents` and
   `plugins-reference`, cross-checked against strings in the installed 2.1.269
   binary) and contradicts `hosts/claude-code.json` in ways that matter — most
   sharply, plugin-shipped agents ignore `hooks`, which the manifest records as
   a supported capability. Filed in full at
   `.root-architect/ledger/2026-09-14-claude-subagent-contract.md` — the complete
   frontmatter contract with per-claim provenance, the plugin-shipped
   restriction, precedence, limitations, and six errors or gaps in
   `hosts/claude-code.json`.

   That ledger is gitignored. The contract half of it is host knowledge rather
   than run state, so it still wants to land at
   [[Claude Code Subagent Contract]] under `Knowledge/`, with the plugin-agent
   hook restriction as an `Architecture/ADR/` entry — a constraint to design
   around, not a fact to look up. Recorded as a move, not a duplication.

   The open decision: extend `host-capability.schema.json` to model unused
   capabilities and scope hazards, or correct the factual errors within the
   existing six-boolean shape first.

   **Resolved, partly.** After reviewing `orchestration-quality-control/adapters/`
   as prior art, the answer turned out not to be a schema question at all: the
   three findings that would not fit the capability booleans are *mechanics*, and
   mechanics are files, not fields. Recorded as
   [[0001-host-adapters-as-directories-with-generated-agents]] — adopt their
   adapter-directory-and-build shape, keep our generate-and-verify content, and
   make a `--check` over the built bundle a precondition of the migration rather
   than a follow-up. The §7 corrections still land first, in the current shape.

## Decisions taken

- Vault archetype `software-project`, adopting the existing `AI_Codex/` folder
  rather than creating a second `AI_Codex*` one. Autodetect globs `AI_Codex*/`
  and breaks on the first match, so a second folder would have been created and
  then silently ignored.
- The vault is tracked in git. The `.gitignore` entry for `AI_Codex/` is removed;
  `.root-architect/` stays ignored, since it is run state rather than knowledge.
- `git config --global --add safe.directory` for this repo. It was the only
  `agent-stack` plugin missing from a list that already covered its siblings, and
  its absence made every plain `git` call fail, which the session gate read as a
  detached HEAD and turned into blocked writes.
