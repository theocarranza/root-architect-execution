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
they confirm the three agent roles resolve on this host and that `agents/` still
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

When contributing to *this* repo, the outcome gate is these five, and none of
them is optional:

```bash
python3 -m unittest discover -s tests -t .
python3 scripts/render_agents.py --host claude-code --check
python3 scripts/render_agents.py --host codex --check
claude plugin validate .
python3.11 -m unittest discover -s tests -t .   # any 3.11+, for tomllib
```

Each of the last three exists because the suite alone has been green over a
real defect:

- The tests do not read `.claude-plugin/`, so a manifest that disagrees with
  itself passes them cleanly. A version bump moved `plugin.json` and left the
  marketplace entry behind, and only `claude plugin validate` noticed.
- `--check` is per host. A `hosts/codex.json` change leaves `agents/` in sync
  and `dist/codex/` stale.
- The Codex agents are TOML, and `tomllib` is 3.11+. On a 3.10 interpreter with
  no `tomli` installed, every parser-backed assertion **skips** — so a
  generated manifest that no TOML parser would accept can ship green. Install
  `tomli`, or run the suite once on 3.11+. The suite prints an explicit skip
  naming what went unverified rather than passing silently.

That last point is the outcome gate's own rule applied to this repo: a test
suite only checks what it was written to check, and generated output is exactly
the kind of artifact it can miss.

`.github/workflows/outcome-gate.yml` runs all five on every push and pull
request, so the gate no longer depends on a contributor remembering it. Run
them locally anyway — CI is the backstop, not the first line. The workflow
refuses to run as root: the five tests that prove an unreadable dispatch state
denies do it with `chmod 000`, root bypasses permission bits, and a suite that
skips them still reports `OK`. A gate that passes on 120 of 125 tests without
saying so is the fail-open this repo's guards exist to close.

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
