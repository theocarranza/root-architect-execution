# adapters/claude-code

How this host's bundle is assembled, and what this host can do that we
deliberately do not use.

`layout.json` declares source → destination for every piece of the bundle.
`scripts/build_adapter.py` reads it and knows nothing about Claude Code
specifically; `--check` rebuilds into a temporary directory and compares byte
for byte against `dist/claude-code/`, so the bundle cannot drift from the
sources it claims to come from.

Sources resolve against this directory first and the repository root second.
That ordering is why ADR 0001 step 3 was a `git mv`: the layout entry
`"hooks/": "hooks/"` did not change, the adapter copy simply started winning.

## What lives here

| | |
|---|---|
| `hooks/` | The two PreToolUse guards and their wiring. Moved from the repository root by ADR 0001 step 3 |
| `manifest.template.json` | Becomes `.claude-plugin/plugin.json` in the bundle |
| `marketplace.template.json` | Becomes `.claude-plugin/marketplace.json` in the bundle |
| `agent-interface.json` | What this host offers, per claim, with provenance |
| `layout.json` | Where each piece lands |

No agent files are authored here. They are generated from `roles/` into
`agents/`, and ADR 0001's rule that no host-specific copy of a role is ever
hand-written is what keeps this directory from becoming the drift table that
rule exists to prevent.

## Why the bundle is the plugin, and the repository root is not

`bundle_root` is `.` because `marketplace.template.json` declares
`"source": "./"`. Claude Code installs a marketplace directory source directly,
so this host needs no installer — a fact [[0001-host-adapters-as-directories-with-generated-agents]]
calls "luck, not design", since Codex needs `adapters/codex/install.py` and
Cursor has no install path at all. A host that nests its plugin inside the
bundle sets `bundle_root` to that subdirectory instead.

Since the manifests moved in here, `dist/claude-code/` is the only loadable
plugin. Develop against it — `claude plugin marketplace add ./dist/claude-code`
— and rebuild after editing a source.

One sharp edge, found while making this move: `claude plugin validate .`
at the repository root does **not** fail now. It switches from validating the
marketplace manifest to validating components, and exits 0 either way. So the
command that exists to catch a manifest disagreeing with itself keeps reporting
success while no longer looking at a manifest. CI greps for the
`Validating marketplace manifest` line for that reason, and the suite asserts
the name-and-version agreement directly rather than trusting the CLI's mode.

### Two scripts that run from two places

`root_write_guard.py` needs `dispatch_state.py`, and `render_agents.py` needs
the plugin name. Both live at one path in this tree and a different one in an
installed bundle, so both name **two positions in order** rather than searching
upward. A search would find any directory called `scripts/`; the guard fails
closed on an import error, so a wrong hit would not be a clean failure, it would
be a guard denying every write with a baffling reason.

## Capabilities available here that we do not use

[[Claude Code Subagent Contract]] §7 records six problems with
`hosts/claude-code.json`. Findings 1–3 were factual errors and are fixed. The
rest are not errors — they are things this host offers and this plugin declines.
The capability schema has no vocabulary for "available, deliberately unused,
here is why", which is exactly the argument ADR 0001 makes for adapter
directories, so they are recorded here instead of forced into a boolean.

### `isolation: worktree` — available, unused (finding 4)

A plugin-shipped agent **is** permitted to set it, and it gives the worker its
own git checkout with git commands validated against escaping to the main one.

It does **not** scope writes to a brief's `write_paths`, so the disclosure
"Write scope is **never** host-enforced anywhere" stays literally true. But it
would contain the blast radius of a misbehaving implementer to a throwaway
checkout, which is materially more than the instruction we ship today. §7 calls
this "the largest available improvement to the weakest boundary in the
protocol", and that judgement stands.

Not adopted yet because nobody has tested what it does to the two guards. Both
key on paths resolved against the session's working directory; a worktree moves
that directory, and `root_write_guard` compares a brief's `write_paths` against
it. Adopting this without proving the guards still deny correctly would trade a
tested boundary for an untested one.

**Before adopting:** run the guard probe table inside a worktree-isolated agent
and confirm a root edit to a delegated path still exits 2.

### `maxTurns`, `memory`, `skills`, `background` — available, unused (finding 5)

- **`memory`** is the dangerous one. `memory: project` would give a validator
  persistent recall across dispatches, which quietly destroys the independence
  the two review gates rest on — the protocol requires a *fresh* agent, and
  §6 of the contract confirms non-fork subagents start with no inherited
  context. It must stay unset, and that is a decision rather than an oversight.
- **`maxTurns`** would bound a worker that never returns. Today nothing does.
- **`skills`** could replace the `Read ${CLAUDE_PLUGIN_ROOT}/references/agents/…`
  indirection with role prose preloaded at startup. Attractive, but it changes
  how every generated agent opens, so it wants its own change rather than
  riding along with something else.
- **`background`** strips most built-ins and is irrelevant to these roles.

## Hazard: plugin scope is the lowest precedence (finding 6)

Not a capability at all, and not expressible as one. A property of the channel
we distribute through.

Resolution order, highest to lowest:

```
managed settings → --agents flag → project .claude/agents/ → user ~/.claude/agents/ → plugin agents/
```

So a project-local `.claude/agents/impl-executor.md` **silently overrides** the
generated agent while still reporting `agent_type: impl-executor`.
`worker_git_guard` keys on that name, so the guard keeps firing — but the grant
it believes it is protecting belongs to somebody else's file, with whatever
tools and model that file declares.

`validate_roles.py --check` compares `agents/` against `roles/`. It has no
visibility into a higher-precedence override, and cannot be given any: the
override lives in the consuming project, not here.

Per-agent hooks would not have helped either — a shadowing agent would carry the
shadowing file's hooks. See
[[0002-plugin-shipped-agents-cannot-carry-hooks]].

What *does* mitigate it, partially: the session-wide hooks are keyed on
`agent_type` rather than attached to our files, so they still fire for a
shadowing agent. The boundary holds; the *grant* is what is no longer ours.

**If you are debugging an agent behaving unlike its manifest, check for a
project-local file of the same name before anything else.**
