# root-architect-execution

A Claude Code plugin for running an implementation plan from a root session that
owns the plan, Git, and the ledger, and delegates every line of product code to
cheaper isolated workers.

It is the `root-architect-execution` skill plus the machinery the skill used to
only describe: schema-declared agent roles, generated host agent files, and two
PreToolUse hooks that enforce the two rules prose never managed to.

## Install

### Codex

Codex plugin installation copies the bundle but does not automatically
materialize this repository's custom agent TOMLs. After installing, activate
the agents explicitly:

```bash
codex plugin add /path/to/root-architect-execution
python3 /path/to/root-architect-execution/scripts/install_codex.py \
  --target .codex/agents \
  --plugin-root /path/to/root-architect-execution
```

The bootstrap is idempotent, resolves references to the installed plugin copy,
and never writes generated agents into the source repository.
Codex does not document worker identity in `PreToolUse`, so root-versus-worker
write separation is instructional and enforced by root's diff review. Claude's
identity-aware write guard remains active.

The plugin ships its own marketplace manifest, so installing is two commands:
register the marketplace, then install from it.

```bash
# From a local clone
claude plugin marketplace add /path/to/root-architect-execution
claude plugin install root-architect-execution@root-architect-execution

# Or straight from the repo
claude plugin marketplace add <owner>/<repo>
claude plugin install root-architect-execution@root-architect-execution
```

`--scope` decides who gets it: `user` (default, every project), `project`
(committed to the repo you are in, so the team shares it), or `local` (this
checkout only, uncommitted). It is accepted by both commands.

**Restart Claude Code afterwards.** Skills and agents load on demand, but the two
PreToolUse hooks are read at session start, so until you restart, the guards are
installed and not enforcing.

Verify:

```bash
claude plugin list                      # root-architect-execution, enabled, 0.1.1
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_roles.py"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_agents.py" --host claude-code --check
```

The last two are the capability gate. They are worth running once after install:
they confirm the agent roles resolve on this host and that `agents/` still
matches `roles/` and `hosts/`, which is the thing the protocol refuses to start
without.

### Updating

```bash
claude plugin update root-architect-execution
```

The install cache is **version-keyed** — `~/.claude/plugins/cache/root-architect-execution/root-architect-execution/<version>/`
— and it is a copy, not a symlink. So editing a local clone changes nothing in an
installed session: bump the version, reinstall or update, and restart. If the new
version directory is not there, the update did not land.

### Developing against a local clone

`claude plugin marketplace add <path>` on a directory source points at the
working tree rather than caching a copy of it, so a clone can serve as its own
marketplace while you work on it. Two things still bite:

- Hooks are read at session start, so hook changes need a restart regardless.
- `.claude-plugin/plugin.json` and the entry in `.claude-plugin/marketplace.json`
  each carry a version and they must agree. `plugin.json` wins at install time
  and the marketplace entry is silently ignored, so drift is invisible until
  something installs the wrong thing. `claude plugin validate .` catches it.

## Install prerequisite: the nesting cap

Orchestration needs two levels of agent nesting — root dispatches the
orchestrator, the orchestrator dispatches workers. Claude Code caps nesting at
`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, and at the cap the `Agent` tool is
withheld from the dispatched agent's toolset **entirely**, rather than offered
and refused. So an orchestrator at the cap does not fail loudly; it simply has
no way to dispatch.

```bash
export CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2
```

Two things worth knowing about that variable:

- **It is read at process start.** Exporting it into a session already running
  does nothing. Set it before launching.
- **Its default is not a release constant.** Absent an explicit setting the
  value comes from a remotely-controlled feature flag, so it can differ between
  a local session and a web one, and can change with no local change at all.
  Measured at `1` in a Claude Code web session on 2026-09-17.

Verified rather than assumed, by an A/B probe of two fresh `claude -p`
processes differing only in that variable: at `2` the dispatched subagent holds
`Agent`, at `1` it does not.

You do not have to remember this. Root checks the capability at startup and
refuses to orchestrate without it, so a missing prerequisite stops the run with
a reason instead of quietly producing an unisolated one.

## Starting a session as root

Root is a **mode, not a command**. There is no slash command that turns an
ordinary session into a root-architect one, because the boundary root's
isolation rests on — `Agent(<plugin>:orchestrator)`, restricting root to
dispatching the orchestrator and nothing else — binds only for an agent running
as the main thread:

```bash
CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2 claude --agent root-architect
```

Launched any other way, that line is ignored and root can dispatch anything.
The session looks and feels identical, which is the whole problem, so root's
first act is a startup check:

```bash
# Root writes down what it can actually see, then has it judged.
python3 scripts/root_preflight.py --run-id <run-id> --observed observed.json
```

Root supplies the observation; the script supplies the verdict. `job_queue init`
refuses a run with no passing record, so skipping the check does not produce a
run that merely lacks one — it produces no run.

What that check cannot do is catch a root that misreports what it sees. It
catches every *accidental* way the boundary goes missing, which is every way it
has actually gone missing.

## Layout

| Path | What it is |
| --- | --- |
| `SKILL.md` | The protocol: architecture, gates, state, per-task loop, stop conditions |
| `roles/*.json` | Every agent — the three workers, the orchestrator, and root — as model tier, reasoning strength, tool grant, mutation class |
| `hosts/*.json` | What each host can actually express, with the date and evidence behind every claim |
| `agents/*.md` | **Generated.** The Claude Code agent files |
| `dist/<host>/` | **Generated.** `claude-code/` is a built, byte-gated bundle; `codex/` and `cursor/` are still reference agent copies |
| `adapters/<host>/` | How one host's bundle is assembled — `layout.json` today, host mechanics as ADR 0001 proceeds |
| `references/agents/*.md` | The role prose, written once and pointed at, never copied |
| `references/contracts.md` | The four shapes the loop passes around |
| `schemas/*.json` | Real JSON Schemas for roles, hosts, briefs, reports, verdicts, dispatch state |
| `scripts/` | Capability gate, interface gate, renderer, return gate, dispatch state, mailbox, job queue, startup check |
| `hooks/` | The two guards |
| `tests/` | `python3 -m unittest discover -s tests -t .` |

## The commands root runs

```bash
# Capability gate — before dispatching anything
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_roles.py"

# Open a dispatch from a schema-checked brief; the guards read this file
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py" open \
  --brief /tmp/brief.json --run-id 20260907-task-3

# Return gate — before treating a worker's reply as a result
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_return.py" \
  --role implementer --file /tmp/return.txt --task "..." --attempt 1

# Recovery — which state file is untrusted, and why
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py" verify
```

When contributing to *this* repo, the outcome gate is these nine, and none of
them is optional:

```bash
python3 -m unittest discover -s tests -t .
python3 scripts/render_agents.py --host claude-code --check
python3 scripts/render_agents.py --host codex --check
python3 scripts/build_adapter.py --host claude-code --check
python3 scripts/validate_interfaces.py
python3 scripts/validate_roles.py
python3 scripts/smoke_install.py --host claude-code
claude plugin validate .
python3.11 -m unittest discover -s tests -t .   # any 3.11+, for tomllib
```

Each of the ones after the suite exists because the suite alone has been green
over a real defect:

- The tests do not read `.claude-plugin/`, so a manifest that disagrees with
  itself passes them cleanly. A version bump moved `plugin.json` and left the
  marketplace entry behind, and only `claude plugin validate` noticed.
- `--check` is per host. A `hosts/codex.json` change leaves `agents/` in sync
  and `dist/codex/` stale.
- `smoke_install.py` is the only gate that runs the **host** against the
  artifact. Everything above reasons about files; this installs the built
  bundle into a throwaway `HOME` and asks Claude Code to enumerate what it
  found, failing unless every role in `roles/` came back as an agent, the skill
  came back as a skill, and every event in `hooks/hooks.json` came back
  registered with its script actually present. A bundle can be byte-perfect and
  still not load — a manifest the host parses but rejects, a skill folder whose
  name stopped matching its frontmatter — and no file comparison catches that.
  It never touches your own plugin config, so it is safe to run locally.
- `build_adapter.py --check` covers the *bundle*, not just the agent files. It
  rebuilds into a temporary directory and compares byte for byte, because a
  path-to-hash manifest proves a bundle is internally consistent and not that
  it agrees with the source it came from — a bundle built from stale sources
  hashes perfectly. Change anything under `scripts/`, `schemas/`, `hooks/` or
  `references/` and `dist/claude-code/` is stale until you rebuild it.
- `validate_interfaces.py` is the only gate that asks where a claim *came
  from*. Every other gate checks that files agree with each other; this one
  checks that what they agree on was ever sourced. Each
  `adapters/<host>/agent-interface.json` records what that host offers with
  per-claim provenance, and the gate refuses a role that depends on anything
  marked `unsourced` — plus any drift between an interface and the
  `hosts/*.json` the renderer actually reads. It exists because two review
  sessions and four reviewer passes once argued about `disallowedTools`
  precedence and MCP tool namespacing entirely from inference, reached two
  confident and partly wrong conclusions, and nothing in the repository could
  settle it. Absence from a corpus is not absence from an interface, and the
  `unsourced` level is how that distinction stays writable.
- The Codex agents are TOML, and `tomllib` is 3.11+. On a 3.10 interpreter with
  no `tomli` installed, every parser-backed assertion **skips** — so a
  generated manifest that no TOML parser would accept can ship green. Install
  `tomli`, or run the suite once on 3.11+. The suite prints an explicit skip
  naming what went unverified rather than passing silently.

That last point is the outcome gate's own rule applied to this repo: a test
suite only checks what it was written to check, and generated output is exactly
the kind of artifact it can miss.

`.github/workflows/outcome-gate.yml` runs all of them on every push and pull
request, so the gate no longer depends on a contributor remembering it. Run
them locally anyway — CI is the backstop, not the first line. The workflow
refuses to run as root: the five tests that prove an unreadable dispatch state
denies do it with `chmod 000`, root bypasses permission bits, and a suite that
skips them still reports `OK`. A gate that silently covers only
part of the suite is the fail-open this repo's guards exist to close.

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

`hosts/cursor.json` is carried from the reference project and marked
inherited; the capability gate prints a warning for it until someone
re-verifies it against that host's own documentation. `hosts/codex.json` was
re-verified against the Codex subagent and hooks documentation and codex-cli
0.147.0, and `hosts/claude-code.json` against the Claude Code subagent and
plugin references — see [[Claude Code Subagent Contract]] in the vault for the
latter, with provenance per claim. A host is flagged by the gate when its
`source` begins `INHERITED`, so the warning and this paragraph cannot drift
apart silently.
