---
title: Environments
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Environments

## Source/development checkout

Authoritative editable environment. Source declarations live here. Generated `agents`/adapter-agent files and `dist` are outputs.

## Built distribution

`dist/claude-code` and `dist/codex` are installation artifacts checked against source by byte-for-byte rebuild comparison. They should be treated as immutable outputs.

## Installed host cache

Claude Code installation uses a version-keyed plugin cache. Editing the source checkout does not change an already installed cached plugin. A new build/version/reinstall or update plus restart is required.

## Target project workspace

The repository in which the protocol performs work. Runtime dispatch state is stored below:

```text
<workspace>/.root-architect/state/
```

The workspace also contains project Git state and the run's ledger/checkpoint artifacts.

## Throwaway validation environment

Smoke/e2e tests should use isolated temporary `HOME` and disposable Git repositories so host/plugin configuration and test mutations do not affect a developer's normal environment.

## Claude runtime prerequisite

Set `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2` before launching the process when the root must dispatch an orchestrator that itself dispatches workers.
