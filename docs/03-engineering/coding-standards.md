---
title: Coding Standards
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Coding Standards

## Contract first

Behavior crossing an agent/process boundary should be represented by an explicit schema or deterministic command contract. Do not rely on free-form prose where a malformed result can affect authority or mutation.

## Fail closed for trusted state

If durable dispatch state exists but cannot be read, parsed, or validated, protected writes must be denied. Do not reinterpret corrupt state as "no dispatch."

Malformed hook input is intentionally different: if the hook cannot establish that a protected delegation exists, it allows rather than globally breaking every write in an installed project.

## Generated files

Never hand-edit generated agent definitions or `dist/`. Modify declarations/templates and regenerate/rebuild.

## Host claims

Do not infer a host capability and encode it as guaranteed. Record provenance and use `unsourced` where evidence is missing. Unsupported behavior must remain visible.

## Python

Keep scripts directly executable where intended, deterministic, filesystem-conscious, and explicit about non-zero failure exits. Compatibility must account for TOML parsing: Python 3.11+ has `tomllib`; degraded environments must not silently imply equivalent verification.

## Formatting & Linting

Code formatting, linting, and type checking standards are enforced via Ruff and Basedpyright/Mypy (`pyproject.toml`):
- Run `python3 tools/lint.py --check` (or `ruff check`, `ruff format --check`, and type checking) to verify compliance.
- Run `python3 tools/lint.py --fix` (or `ruff check --fix` and `ruff format`) to format code and auto-fix linter issues.
- `tools/lint.py --fix` automatically rebuilds host distribution bundles (`dist/`) so generated bundles remain byte-for-byte in sync with sources.

## Git

Workers never commit. Root creates narrow commits after successful task gates, stages only brief-owned paths plus ledger/checkpoint artifacts, and runs `git diff --cached --check`.
