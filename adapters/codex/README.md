# adapters/codex

How Codex's bundle is assembled, and the two ways this host differs from
Claude Code in kind rather than in detail.

## What lives here

| | |
|---|---|
| `install.py` | The bootstrap. Was `scripts/install_codex.py`; moved by ADR 0001 step 4 |
| `manifest.template.json` | Becomes `.codex-plugin/plugin.json` in the bundle |
| `agents/*.toml` | **Generated.** Never hand-edited — `render_agents.py --host codex` writes them |
| `agent-interface.json` | What this host offers, per claim, with provenance |
| `layout.json` | Where each piece lands |

## Difference 1: the bundle cannot be installed by copying it

Claude Code needs no installer because its marketplace happens to be a native
install path. ADR 0001 calls that "luck, not design", and Codex is where the
luck runs out: Codex copies a plugin bundle but does not read a plugin's agents
out of it, so the TOMLs have to be materialized into `.codex/agents` explicitly.

```bash
python3 <bundle>/install.py --target .codex/agents --plugin-root <bundle>
```

That is why this bundle ships `roles/`, `hosts/codex.json`, `schemas/`,
`scripts/` and `references/` alongside the agents: `install.py` re-renders each
TOML with the **installed** plugin root substituted in, so a worker's
`developer_instructions` point at role prose that exists on the machine it is
running on. A bundle carrying the agents but not the means to install them
would be a directory nobody can act on, and `--check` would call it perfect.

The suite runs `install.py` from a copy of the built bundle with nothing else
on the path, for exactly that reason: a byte gate proves the copy was faithful,
never that the result can act.

### The installer owns what it wrote, and nothing else

`.codex/agents` lives inside the consuming project, where a clone can carry in
a marker file. So the installer removes only filenames its own previous marker
recorded, accepts a marker entry only if it is a bare filename, and re-checks
the resolved parent before unlinking. An entry containing a separator or `..`
is skipped rather than deleted — the failure being refused is an installer
deleting a file it never wrote, anywhere the user can reach.

## Difference 2: no tool allowlist, and no worker identity in the hook payload

Codex restricts capability through a sandbox profile reached from a role's
config layer, not through a per-agent tool list. So `hosts/codex.json` declares
`tool_allowlist` unsupported, and every generated agent here carries the
disclosure that its grant is an instruction. `read-files` and `search-files`
map to no tool name at all — which is not the same as Codex being unable to
read, and the interface file is careful about that distinction.

The sharper one: Codex's `apply_patch` carries no worker identity in
`PreToolUse`, so `root_write_guard`'s root-versus-worker separation cannot be
enforced here. Canonical `apply_patch` is deliberately left outside that guard —
blocking it would block the worker too — and the generated files say so. Root
reviewing the materialized worker diff is what stands in for it.

ADR 0001 records a mechanism that would close this without identity:
`orchestration-quality-control` hashes `(path, before, after)` and admits only
patches whose digest was pre-approved. If that is ever built, it belongs in
`adapters/codex/hooks/`, which is why this directory exists in the shape it
does. It is not built, and this file does not pretend otherwise.

## Not settled here

`hosts/codex.json` was verified against codex-cli 0.147.0 on 2026-09-08. The
nesting claim in `agent-interface.json` is first-party-sourced, so the
orchestrator and root both build for this host — but nothing in this repository
has yet run a Codex agent that dispatches another one. Sourced is not the same
as exercised, and the distinction is worth keeping in view.
