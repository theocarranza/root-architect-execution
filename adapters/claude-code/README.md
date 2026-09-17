# adapters/claude-code

How this host's bundle is assembled, and what this host can do that we
deliberately do not use.

`layout.json` declares source → destination for every piece of the bundle.
`scripts/build_adapter.py` reads it and knows nothing about Claude Code
specifically; `--check` rebuilds into a temporary directory and compares byte
for byte against `dist/claude-code/`, so the bundle cannot drift from the
sources it claims to come from.

Sources resolve against this directory first and the repository root second.
That ordering is deliberate: moving `hooks/` in here later is a `git mv`, not a
layout change, because the adapter copy simply starts winning.

## Why the bundle is the plugin

`bundle_root` is `.` because `.claude-plugin/marketplace.json` declares
`"source": "./"`. Claude Code installs a marketplace directory source directly,
so this host needs no installer — a fact [[0001-host-adapters-as-directories-with-generated-agents]]
calls "luck, not design", since Codex needs `scripts/install_codex.py` and
Cursor has no install path at all. A host that nests its plugin inside the
bundle sets `bundle_root` to that subdirectory instead.

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
