---
type: reference
area: host-capabilities
tags: [claude-code, subagents, host-capabilities, frontmatter, plugins]
created: 2026-09-14
source: https://code.claude.com/docs/en/sub-agents + https://code.claude.com/docs/en/plugins-reference
domain: claude-code
retrieved: 2026-09-14
---

# Claude Code Subagent Contract

What Claude Code's subagent system actually guarantees, and what it costs
`hosts/claude-code.json`.

Branch of origin: `fix/guard-fails-closed-on-untrusted-dispatch-state`. Recorded
as research on 2026-09-14, with no code change at the time. §7 findings 1–3 were
corrected on 2026-09-16 in `9b3bf0a`. Findings 4–6 were never errors — two are
capabilities this host offers and this plugin declines, one is a hazard of the
distribution channel — and they now live in `adapters/claude-code/README.md`
with the condition for adopting each. §8 framed the open question as whether
the capability schema needed new vocabulary;
[[0001-host-adapters-as-directories-with-generated-agents]] answered it
differently, and that answer is what gave them a home.

## 1. Why this exists

`hosts/claude-code.json` was verified on 2026-09-07 against binary 2.1.234. The
installed binary is now **2.1.269**, and the manifest's own premise — that a
capability the host cannot enforce must be disclosed rather than assumed — makes
a stale capability row worse than an absent one: the renderer turns each row into
a claim in a generated agent file, and a false claim about enforcement is exactly
what this plugin exists to prevent.

This note records the contract as documented on 2026-09-14, with provenance per
claim, so the next person can tell what was read from documentation, what was
observed, and what is still assumed.

## 2. Provenance and confidence

| Source | What it settled |
| --- | --- |
| `https://code.claude.com/docs/en/sub-agents` | The full frontmatter table, resolution order, limitations |
| `https://code.claude.com/docs/en/plugins-reference` | The plugin-shipped agent restriction, namespacing, the supported-field list |
| Strings in `/home/bhave/.local/share/claude/versions/2.1.269` | That every key and env var named below exists in the installed build |

Confidence markers used in the tables: **D** documented in both pages or one page
plus a binary string; **d** documented in one page only; **?** documented but not
observed and not independently corroborated — treat as a starting point, the way
`hosts/cursor.json` is treated today.

Not done: no probe of a live subagent payload, no empirical test of the
`tools`/`disallowedTools` precedence, no test of `isolation: worktree`. Anything
marked **?** below deserves that before it becomes a capability row.

## 3. Frontmatter contract

### Required

| Field | Type | Notes | Conf |
| --- | --- | --- | --- |
| `name` | string | Lowercase and hyphens. **Cannot contain `:`** — reserved for plugin scoping. This is the value PreToolUse delivers as `agent_type`. | D |
| `description` | string | When to delegate. Counts against a 15,000-token budget shared by all subagent descriptions. | D |

`name` cannot contain `:` is load-bearing for us twice over. It confirms
`agent-role.schema.json`'s `^[a-z][a-z0-9-]{1,48}[a-z0-9]$` is correctly shaped,
and it is why `worker_git_guard.role_for()` splits on the last `:` — a plugin
agent is reported as `<plugin>:<agent>`, and the bare form only appears for a
project-local copy.

### Grant

| Field | Default | Values | Conf |
| --- | --- | --- | --- |
| `tools` | **omitted ⇒ inherits every tool available to subagents** | Tool names; MCP patterns `mcp__server`, `mcp__server__*`; `Agent` or `Agent(worker, researcher)` to allowlist which subagents may be spawned | D |
| `disallowedTools` | none | Applied **first**; `tools` then resolves against what remains. An entry carrying a specifier (`Bash(git push *)`) removes the **whole tool**, not the matching invocations. | d |

Two consequences worth stating plainly:

- Omitting `Agent` from `tools` is how you forbid spawning. That makes
  `must_not: spawn-agents` **host-enforced** on this host whenever `tools` is
  written. It was disclosed as mere instruction until `9b3bf0a`, which now
  derives the enforcement from the grant itself.
- A `disallowedTools` entry with a specifier is a trap for anyone who later tries
  to express "Bash but not `git push`" there. It would remove Bash entirely. The
  worker Git boundary has to stay in the PreToolUse hook; the denylist cannot
  express it.

### Model and reasoning

| Field | Values | Conf |
| --- | --- | --- |
| `model` | `sonnet`, `opus`, `haiku`, `fable`, a full id (`claude-opus-5`), or `inherit` | D |
| `effort` | `low`, `medium`, `high`, `xhigh`, `max` — availability depends on the model | D |

Resolution order: per-invocation `model` parameter → frontmatter → the
`CLAUDE_CODE_SUBAGENT_MODEL` env var → the parent's model. When `availableModels`
blocks the choice, a family alias substitutes the newest allowed member of that
family, and anything else falls back to the inherited model. Extended thinking is
inherited from the parent; **there is no per-subagent thinking setting**.

The existing manifest note — "an unset field inherits and must never be left
unset" — survives this re-reading intact.

### Execution

| Field | Default | Values | Conf |
| --- | --- | --- | --- |
| `maxTurns` | unlimited | positive integer; output is marked *partial* when reached | D |
| `isolation` | none | `worktree` only — own git checkout, git commands validated against escaping to the main checkout | D |
| `background` | `false` | `true` pins the agent to background | D |
| `memory` | none | `user` \| `project` \| `local` | D |
| `skills` | none | skill names preloaded into context at startup | D |
| `color` | none | red, blue, green, yellow, purple, orange, pink, cyan | d |
| `initialPrompt` | none | auto-submitted first turn when run as a main session via `--agent` | d |
| `experimental` | none | `{cacheTtl: "5m" \| "1h"}` | d |

## 4. The plugin-shipped restriction

Quoted from `plugins-reference`:

> "For security reasons, `hooks`, `mcpServers`, and `permissionMode` are not
> supported for plugin-shipped agents."

The same page enumerates what a plugin agent *does* support: `name`,
`description`, `model`, `effort`, `maxTurns`, `tools`, `disallowedTools`,
`skills`, `memory`, `background`, `isolation` — and notes the only valid
`isolation` value is `"worktree"`.

This is the single most consequential finding in this note. **We ship as a
plugin.** Every row in `hosts/claude-code.json` is therefore constrained by this
list, and `scoped_hooks` is not a capability we can ever exercise from the
channel we distribute through.

## 5. Precedence

Highest to lowest: managed settings (`~/.claude/managed/`) → the `--agents` CLI
flag → project `.claude/agents/` → user `~/.claude/agents/` → **plugin
`agents/` (lowest)**. Same `name` in a higher scope wins outright. Within
`.claude/agents/`, nested directories are scanned recursively and the definition
closest to the working directory wins. Confidence **d** — `plugins-reference` did
not state the ordering; only `sub-agents` did.

The hazard this creates for us is specific and worth naming. A project-local
`.claude/agents/impl-executor.md` silently overrides the plugin's, while still
reporting `agent_type: impl-executor`. `worker_git_guard` keys on that name, so
the guard keeps firing — but the grant it believes it is guarding is somebody
else's file, with whatever tools and model that file declares. The capability
gate (`validate_roles.py --check`) compares `agents/` against `roles/`; it has no
visibility into a higher-precedence override.

## 6. Limitations

**Context.** Non-fork subagents start with a fresh, isolated context window. They
do **not** inherit conversation history, previous tool calls, skills already
invoked, files already read, output style, auto memory, or the parent's context
window size. They **do** inherit `CLAUDE.md`, git status, and the parent's
extended-thinking state. Fork subagents inherit everything including full message
history.

This is the mechanism the loop already depends on for "fresh agent", and it is
stronger than the plugin currently claims. It is also why `memory` must stay
unset: `memory: project` would give a validator persistent recall across
dispatches and quietly destroy the independence the two review gates rest on.

**Nesting and concurrency.** `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` defaults to
3 layers below the main conversation; at the limit the `Agent` tool is withheld
(forks error instead). `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` defaults to 20.
Setting the depth var to `1` disables nesting entirely. Both strings are present
in 2.1.269.

**Tools always removed from every subagent.** `AskUserQuestion`,
`EnterPlanMode`, `ExitPlanMode` (unless `permissionMode: plan`),
`EndConversation`, `ScheduleWakeup`, `TaskOutput`, `WaitForMcpServers`,
`Workflow`.

`AskUserQuestion` being unconditionally removed makes `must_not: ask-owner`
host-enforced here. We disclose it as an instruction. That is an understatement,
and understating enforcement is its own kind of dishonesty in a file whose
purpose is to state enforcement accurately.

**Background subagents** additionally lose every built-in except Read, Grep,
Glob, Bash, PowerShell, Edit, Write, NotebookEdit, WebFetch, WebSearch,
TodoWrite, Skill, ToolSearch, EnterWorktree, ExitWorktree, Monitor, TaskStop,
SendMessage, Artifact — all MCP tools are kept.

**Execution and permissions.** A subagent cannot change its own permission
settings, `CLAUDE.md`, or configuration mid-run. The parent's `permissions.allow`
and `permissions.deny` still apply. `cd` does not persist between tool calls and
does not affect the parent. A subagent starts in the parent's working directory.

**Failure modes.** API errors (rate limit, overload, server error) cut the
subagent off; partial output is returned if any text was produced, and the full
error is reported if only tool calls were. If a model is unavailable and a
fallback chain is configured, the subagent retries down the chain.

**Transcripts.** Stored per subagent at
`~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`,
auto-cleaned after `cleanupPeriodDays` (default 30). Built-in Explore and Plan
are one-shot and non-resumable.

**Output scanning.** Since 2.1.210 subagent output is scanned before the parent
reads it. It does not remove or reword; it backslash-escapes instruction-shaped
patterns and inserts marker lines. Worth knowing because `check_return.py` parses
a fenced JSON block out of exactly that text — escaping inside the fence is a
plausible future source of malformed-return retries.

## 7. Errors and gaps in `hosts/claude-code.json`

Six, ordered by how wrong they are. **1–3 are fixed (`9b3bf0a`). 4–6 are not errors but declined capabilities and a channel hazard; they are now recorded in `adapters/claude-code/README.md`, with the conditions for adopting each.**

1. **FIXED — `scoped_hooks` was `supported: true, field: "hooks"`, and is false for this plugin.**
   Plugin-shipped agents ignore `hooks`. The row's own `verified` note already
   explains that we use session-wide hooks keyed on `agent_type` instead — so the
   note is right and the boolean contradicts it. The renderer reads the boolean.
   Must become `false`, with the plugin restriction as the reason.

2. **FIXED — `must_not: ask-owner` is host-enforced, not instructional.**
   `AskUserQuestion` is stripped from every subagent unconditionally.

3. **FIXED — `must_not: spawn-agents` is host-enforced** whenever `tools` is written
   without `Agent`, and additionally bounded by the depth cap. We disclose it as
   compliance-only.

4. **`isolation: worktree` is unmodeled.** It does not scope writes to a brief's
   `write_paths`, so "Write scope is **never** host-enforced anywhere" stays
   literally true — but a worktree contains the blast radius to a throwaway
   checkout, which is materially more than the instruction we ship. This is the
   largest available improvement to the weakest boundary in the protocol.

5. **`maxTurns`, `memory`, `skills`, `background` are unmodeled.** `memory` is
   the dangerous one (§6). `maxTurns` would bound a worker that never returns.
   `skills` could replace the `Read ${CLAUDE_PLUGIN_ROOT}/references/agents/...`
   indirection with a preloaded role prose.

6. **Plugin scope is lowest precedence**, so a project-local file can shadow a
   generated agent while keeping its `agent_type`. Not expressible as a
   capability boolean at all; it is a scope hazard, and today nothing in the
   repo mentions it.

## 8. What this implies for the adapter work

The schema models six booleans of the form "does the host enforce X, and in which
field". Findings 4, 5 and 6 do not fit that shape:

- 4 and 5 are **capabilities the host has that we do not use** — the manifest has
  no vocabulary for "available, deliberately unused, here is why".
- 6 is a **scope hazard** — a property of the distribution channel, not of a
  field.

So the open decision is genuine and not cosmetic:

**(a)** Extend `host-capability.schema.json` with an `unused_capabilities` block
and a `hazards` block, and teach `disclosures()` to render both. Bigger change;
makes the manifest able to state the whole truth; every host manifest then has to
be revisited.

**(b)** Correct findings 1–3 inside the existing six-boolean shape now, and leave
4–6 recorded here until the adapter redesign. Smaller, lands the three factual
errors immediately, leaves the manifest silent about things it cannot currently
express.

Recommendation: **(b) first, then (a)**. (b) was taken on 2026-09-16 in
`9b3bf0a`; (a) is still open. Findings 1–3 are wrong statements being
rendered into shipped agent files today; 4–6 are omissions. Fixing a false claim
does not need to wait for a schema that can hold a richer truth. Note also that
correcting finding 1 changes generated output — the `scoped_hooks` disclosure
line appears in every generated agent for every host where it is false — so
`dist/` and `agents/` regenerate, and that is the first change on this branch
that will not be byte-identical.

[[0001-host-adapters-as-directories-with-generated-agents]] later resolved the
shape question: the three findings that would not fit the capability booleans are
*mechanics*, and mechanics are files rather than fields. That ADR sequences the
§7 corrections first, in the current shape, independently of the migration.

## 9. Provenance of this note

Moved here from `.root-architect/ledger/2026-09-14-claude-subagent-contract.md`,
which is gitignored as run state and did not survive a clone. §3–§7 are host
knowledge rather than run state, so by the vault decision of 2026-09-14 they
belong in the tracked vault. A move, not a duplication — the ledger copy is not
the canonical one any more.

Section numbering is preserved deliberately: the §7 reference in
[[0001-host-adapters-as-directories-with-generated-agents]] resolves against this
note.

Still outstanding from the original §9: the plugin-agent hook restriction (§4)
wants an `Architecture/ADR/` entry of its own, because it is a constraint the
architecture has to be designed around rather than a fact to look up.
