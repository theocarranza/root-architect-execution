# AI_Codex — root-architect-execution

Archetype **Software / Agile Project Vault** (`software-project`). The marker `.agent-continuity-vault.json` records it;
the `PreToolUse(Write)` naming hook and `/agent-continuity:vault-lint` both read
the same archetype spec, so scaffold, enforcement, and audit cannot disagree.

The original codex shape, refined: a project + knowledge-base hybrid for an agile/XP codebase. Status is encoded by ticket folder; knowledge accretes from resolved work.

Start at [[Agent_Orientation]].

## Taxonomy

- **Knowledge/** — Permanent distilled knowledge notes (patterns, domains, references) + the knowledge MOC
- **Tickets/Active/** — In-flight ticket ledgers
- **Tickets/Ready/** — Groomed, ready-to-start tickets
- **Tickets/Closed/** — Merged/closed, awaiting release
- **Tickets/Resolved/** — Shipped/archived ticket ledgers
- **Features/** — Feature specifications and implementation detail
- **Architecture/** — High-level architecture overviews (subfolders below for ADRs/patterns/etc.)
- **Architecture/ADR/** — Architecture Decision Records
- **Architecture/Patterns/** — Recurring design patterns
- **Architecture/Infrastructure/** — Structural/infra definitions
- **Architecture/Agent-Governance/** — Agent governance protocols and directives
- **Architecture/Protocols/** — Operational protocols
- **Agent_Sessions/** — Operational journal of agent sessions (doubly-linked chain)
- **Agent_Reports/** — Formal agent-generated reports
- **assets/** — Images and binary attachments
- **Meta/** — Templates, scripts, and vault plumbing

## Naming

| Folder | Filename style |
| --- | --- |
| `Agent_Sessions/**` | YYYY-MM-DD-HHMMSS-kebab-slug |
| `Agent_Reports/**` | YYYY-MM-DD-kebab-slug |
| `Tickets/**` | <id-or-type>-kebab-slug |
| `Features/**` | [<id>-]kebab-slug |
| `Knowledge/**` | Natural Title Case (Obsidian-native: filename is the display title) |
| `Architecture/ADR/**` | NNNN-kebab-title (Nygard ADR convention) |
| `Architecture/**` | Natural Title Case |

## Frontmatter

Location encodes status; frontmatter encodes what location cannot. A ticket under
`Tickets/Active/` *is* active — `status` is forbidden there precisely so the two
cannot drift.

| Folder | Required | Optional | Forbidden |
| --- | --- | --- | --- |
| `Tickets/**` | `type` | `ticket`, `area`, `stack`, `tags`, `created` | `status` |
| `Features/**` | `type` | `ticket`, `area`, `stack`, `tags`, `created` | `status` |
| `Agent_Sessions/**` | `date`, `type` | `tags`, `ticket` | — |
| `Knowledge/**` | `type` | `area`, `tags`, `created`, `source`, `domain`, `retrieved` | — |
| `Architecture/**` | `type` | `area`, `tags`, `created` | — |

## What lives elsewhere

- `.root-architect/` — run state for this plugin's own protocol: dispatch state,
  the ledger, worker review diffs. Gitignored, and deliberately so: it is the
  state of a run, not knowledge. What a run *taught* belongs here instead.
- The workspace vault (`AI_Codex/` at the parent workspace root, outside this
  repository) — cross-project knowledge shared by every project beside this one.
  This vault is scoped to this repository alone.
