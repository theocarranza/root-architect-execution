---
type: adr
area: host-adapters
tags: [adr, host-adapters, distribution, codegen]
created: 2026-09-14
---

# 0001 — Host adapters as directories, with generated agents

## Status

Proposed — 2026-09-14. Supersedes nothing. Blocks nothing; the corrections in
`.root-architect/ledger/2026-09-14-claude-subagent-contract.md` §7 land first and
independently.

## Context

This plugin declares each worker role once in `roles/*.json`, declares what each
host can enforce in `hosts/*.json`, and generates per-host agent files with
`scripts/render_agents.py`. `validate_roles.py` re-renders in memory and fails if
what is on disk differs, so a hand-edit to a generated agent cannot survive
review. That half works.

The other half does not exist. We generate agent *files*; we have no notion of a
host-native *installation*. The evidence:

- `scripts/install_codex.py` is a one-off bolt-on. It exists because Codex has no
  post-install callback for custom agents, and it handles only Codex.
- Claude Code gets nothing, because the marketplace happens to be a native
  install path. That is luck, not design.
- Cursor has `dist/cursor/` generated and no way to install it at all.
- Everything a host needs that is *not* an agent file — hook wiring, manifest
  shape, manifest location, the installer itself — is either hard-coded in a
  script, absent, or squeezed into `hosts/<host>.json` as a capability field.

That last point is what forced this ADR. Three findings in two days did not fit
the capability schema, which models exactly six booleans of the form "does this
host enforce X, and in which field":

1. `isolation: worktree` is a capability Claude Code has that we do not use. The
   schema has no vocabulary for "available, deliberately unused, here is why".
2. Plugin scope is the lowest precedence, so a project-local
   `.claude/agents/impl-executor.md` shadows ours while keeping its `agent_type`.
   That is a hazard of the distribution channel, not a property of a field.
3. Codex's `apply_patch` carries no worker identity, so we ruled root-vs-worker
   separation unenforceable there — but `orchestration-quality-control` enforces
   an equivalent boundary on the same host by hashing `(path, before, after)` and
   admitting only patches whose digest was pre-approved. Identity-free
   enforcement. That is a *mechanism*, and mechanisms are code, not booleans.

Reviewed as prior art: `orchestration-quality-control/adapters/`, which ships
four hosts (Claude, Codex, Cursor, AGY). Its shape is right and its content is
not. Right: a per-host directory holding that host's specifics, a `build_plugin.py`
per host emitting `dist/<host>-marketplace/` in the host's own layout, a
per-host installer only where the host lacks a native install path, and a
`BUILD-MANIFEST.json` of path→sha256 with deterministic zip timestamps. Wrong:
the six worker agents are hand-authored in every adapter — 24 files restating six
roles — and they have drifted. The same validator role is `sonnet` at
`effort: high` on Claude, `model: inherit` on Cursor and AGY, and carries no model
at all on Codex. `inherit` is the value our own brief schema forbids by name,
because every host defaults to inheriting the parent and a cheap worker silently
becomes as expensive as root.

So: they have the distribution layer we lack, and we have the
single-source-of-truth layer they lack.

## Decision

Adopt the adapter-directory-and-build shape, and keep generation.

1. **`roles/` and `hosts/` remain the single source of truth for role content.**
   No host-specific copy of a role is ever hand-authored. This is the property
   that makes the OQC drift table impossible here, and it is not negotiable in
   exchange for the build layer.

2. **Add `adapters/<host>/` holding host *mechanics* only** — the things that
   genuinely differ per host and cannot be derived from a role:
   hooks and their wiring, the plugin manifest template and its location, the
   installer, and any host-specific enforcement module. No agent files are
   authored here.

3. **The renderer emits generated agents into the adapter tree**, and a build
   step assembles `dist/<host>/` from the portable core plus the adapter's
   mechanics plus those generated agents.

4. **`hosts/<host>.json` stays a capability declaration.** Mechanics move to the
   adapter directory as files. A manifest location is a path, an installer is a
   program, digest-authorization is a module — none of those are facts about
   enforcement, and forcing them into schema fields is what made the schema feel
   wrong in the first place.

5. **`--check` extends to the built bundle**, not just the agent files.

## Target layout

```
root-architect-execution/
├── roles/                        # unchanged — one declaration per role
│   ├── impl-executor.json
│   ├── spec-validator.json
│   └── quality-validator.json
├── hosts/                        # unchanged in kind — capability declarations
│   ├── claude-code.json          #   what this host ENFORCES, and in which field
│   ├── codex.json
│   └── cursor.json
├── references/agents/            # unchanged — role prose, exists once
├── schemas/                      # unchanged — the contracts
├── scripts/
│   ├── render_agents.py          # roles + hosts -> generated agents
│   ├── build_adapter.py          # NEW: core + adapter + generated -> dist/<host>/
│   └── validate_roles.py         # extended: also gates the built bundle
│
├── adapters/                     # NEW — host MECHANICS, never role content
│   ├── claude-code/
│   │   ├── manifest.template.json     # .claude-plugin/plugin.json shape
│   │   ├── marketplace.template.json  # .claude-plugin/marketplace.json shape
│   │   ├── layout.json                # where each artifact lands in the bundle
│   │   ├── hooks/
│   │   │   ├── hooks.json
│   │   │   ├── root_write_guard.py    # moved from hooks/
│   │   │   └── worker_git_guard.py    # moved from hooks/
│   │   ├── agents/                    # GENERATED — .gitignore'd or --check'd
│   │   └── README.md                  # what this host enforces, honestly
│   ├── codex/
│   │   ├── manifest.template.json     # .codex-plugin/plugin.json
│   │   ├── layout.json
│   │   ├── install.py                 # was scripts/install_codex.py
│   │   ├── hooks/                     # none today; digest guard would live here
│   │   ├── agents/                    # GENERATED (.toml)
│   │   └── README.md
│   └── cursor/
│       ├── manifest.template.json
│       ├── layout.json
│       ├── install.py                 # does not exist today; this is the gap
│       ├── agents/                    # GENERATED (.md)
│       └── README.md
│
└── dist/                         # BUILT — host-native, installable as-is
    ├── claude-code/
    │   ├── .claude-plugin/marketplace.json
    │   ├── plugins/root-architect-execution/
    │   │   ├── .claude-plugin/plugin.json
    │   │   ├── agents/*.md
    │   │   ├── hooks/{hooks.json,*.py}
    │   │   ├── skills/root-architect-execution/SKILL.md
    │   │   ├── references/  schemas/  scripts/
    │   └── BUILD-MANIFEST.json        # path -> sha256
    ├── codex/
    │   ├── .codex-plugin/plugin.json
    │   ├── agents/*.toml
    │   ├── install.py
    │   └── BUILD-MANIFEST.json
    └── cursor/
        └── ...
```

`layout.json` is what keeps `build_adapter.py` generic. Rather than a `if host ==
"codex"` chain, each adapter declares where its pieces land:

```json
{
  "bundle_root": "plugins/root-architect-execution",
  "place": {
    "manifest.template.json": "plugins/root-architect-execution/.claude-plugin/plugin.json",
    "marketplace.template.json": ".claude-plugin/marketplace.json",
    "hooks/": "plugins/root-architect-execution/hooks/",
    "agents/": "plugins/root-architect-execution/agents/"
  },
  "core": {
    "references/": "plugins/root-architect-execution/references/",
    "schemas/": "plugins/root-architect-execution/schemas/",
    "scripts/": "plugins/root-architect-execution/scripts/",
    "SKILL.md": "plugins/root-architect-execution/skills/root-architect-execution/SKILL.md"
  }
}
```

Codex's `layout.json` places the manifest at `.codex-plugin/plugin.json` and the
agents at `agents/`; Cursor's places them wherever Cursor wants them. The build
script reads the map; it does not know the hosts.

## Consequences

**What this buys.**

Cursor becomes installable, which it is not today. Codex's installer stops being
a special case and becomes one host's implementation of a shared interface. Each
host's mechanics become a directory someone can read to answer "what does this
host need from us", rather than being distributed across a renderer, a schema,
and one bolt-on script. A fifth host is a new directory and a `layout.json`, not
edits to shared code. And the three findings that did not fit the schema get a
home: `isolation: worktree` becomes an adapter decision recorded in that
adapter's README, plugin-scope shadowing becomes a hazard documented where the
manifest is built, and digest authorization becomes a module in
`adapters/codex/hooks/` if we decide to build it.

**What this costs, and the specific risk.**

A build step means the thing reviewed stops being the thing that runs. Today
`agents/*.md` are checked in and `validate_roles.py --check` proves byte equality
against a re-render, so a reviewer sees the artifact that ships. Introducing
`dist/` gives that up unless `--check` is extended to cover the bundle.

OQC's `BUILD-MANIFEST.json` is the right instinct but is not sufficient on its
own: a path→hash list proves a bundle is internally consistent, not that it
agrees with the source it claims to come from. The gate we need is a rebuild into
a temporary directory and a byte comparison against `dist/`, exactly as
`render_agents.py --check` already does for agent files. Until that exists, this
migration would trade a guarantee we currently have for convenience — which is
the trade this plugin exists to refuse. **`--check` over the bundle is therefore
a precondition of the migration, not a follow-up.**

Secondary costs: `dist/` grows to a full copy of the core per host, so the built
output is no longer reviewable as a diff (OQC's bundles are ~250 files each).
Hook paths move, so `hooks/hooks.json` command strings and the
`${CLAUDE_PLUGIN_ROOT}` references in deny messages must be re-checked. And
`.gitignore` needs a decision on whether `adapters/*/agents/` and `dist/` are
committed or built on demand — committed keeps review honest, built-on-demand
keeps the tree small; the `--check` gate makes committed the cheaper choice.

**What is explicitly not decided here.** Whether to build digest authorization
for Codex, whether to adopt `isolation: worktree`, and whether
`host-capability.schema.json` still needs an `unused_capabilities` block once
mechanics move out of it. Those are separate decisions this layout makes
possible, not consequences of it.

## Sequencing

1. Land the §7 corrections from
   `.root-architect/ledger/2026-09-14-claude-subagent-contract.md` in the current
   shape. They are false statements shipping today and must not wait for a
   migration.
2. Write `--check` over a built bundle, against today's single-host output.
3. Introduce `adapters/claude-code/` and `build_adapter.py`, with `dist/` byte-gated.
4. Move Codex, then Cursor.

Step 2 before step 3 is the load-bearing order. Building the migration first and
the gate afterwards is how the guarantee gets lost.
