---
title: Deployment and Installation
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Deployment and Installation

This project deploys as local host plugin/agent bundles, not as a server.

## Build

```sh
python3 scripts/build_adapter.py --host claude-code
python3 scripts/build_adapter.py --host codex
python3 scripts/build_adapter.py --host gemini
```

## Claude Code installation

Register the built bundle as a marketplace source, install the plugin, restart Claude Code, then run the capability checks. Hooks are loaded at session start; installation without restart means guards may exist on disk but not be active in the current process.

For local development, use `dist/claude-code` as the marketplace source after rebuilding.

## Codex installation

Build `dist/codex`, add/install the plugin as appropriate for Codex, then run the bundled installer:

```sh
python3 /path/to/dist/codex/install.py \
  --target .codex/agents \
  --plugin-root /path/to/dist/codex
```

The installer is designed to be idempotent and to remove only files tracked by its own marker.

## Gemini installation

Build `dist/gemini`:

```sh
python3 scripts/build_adapter.py --host gemini
```

The resulting `dist/gemini` bundle contains `.gemini-plugin/plugin.json`, Markdown agent configurations under `agents/`, roles, references, schemas, scripts, and `SKILL.md`.

## Verification

Before treating a bundle as deployable:

```sh
python3 scripts/build_adapter.py --host <host> --check
python3 scripts/validate_roles.py
python3 scripts/validate_interfaces.py
```

For Claude also validate the actual built plugin and smoke-install it.

## Rollback

Because installed plugin caches are versioned copies rather than symlinks, rollback is performed by reinstalling/selecting a previously known-good version/bundle and restarting the host. Do not "fix" an installed generated agent in place; fix source and rebuild.
