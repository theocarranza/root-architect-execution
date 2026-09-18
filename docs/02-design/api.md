---
title: Command and Contract Interfaces
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Command and Contract Interfaces

This project exposes command-line and file-contract interfaces rather than an HTTP API.

## Dispatch state

```sh
python3 scripts/dispatch_state.py open --brief <brief.json> --run-id <run-id>
python3 scripts/dispatch_state.py active
python3 scripts/dispatch_state.py close --run-id <run-id> --outcome accepted
python3 scripts/dispatch_state.py verify
```

`open` validates the brief and refuses a second concurrent dispatch. `verify` reports every state record and returns non-zero on corruption.

## Worker return validation

```sh
python3 scripts/check_return.py \
  --role implementer \
  --file <return.txt> \
  --task "<task>" \
  --attempt 1
```

Supported logical return roles are implementer, spec-validator, and quality-validator. Exit 0 means the return is structurally and semantically well-formed; exit 1 means it must not be treated as a valid result.

## Role and generated-agent validation

```sh
python3 scripts/validate_roles.py
python3 scripts/validate_roles.py --host codex
python3 scripts/render_agents.py --host claude-code --check
python3 scripts/render_agents.py --host codex --check
python3 scripts/validate_interfaces.py
```

## Build interface

```sh
python3 scripts/build_adapter.py --host claude-code
python3 scripts/build_adapter.py --host codex
python3 scripts/build_adapter.py --host claude-code --check
python3 scripts/build_adapter.py --host codex --check
```

`--check` rebuilds into temporary storage and byte-compares the result to `dist/<host>`.

## Installation interfaces

Claude Code consumes `dist/claude-code` as a plugin/marketplace artifact. Codex consumes `dist/codex` and additionally runs its bundled `install.py` to materialize custom agent TOMLs into a target such as `.codex/agents`.

## Contract compatibility rule

Schemas plus cross-field checks form the public internal API. A producer must not rely on prose tolerance: required fields, role identity, attempt identity, test evidence, findings semantics, and validator capabilities are mechanically checked.
