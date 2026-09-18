---
title: Testing Strategy
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Testing Strategy

## Test philosophy

Tests are layered because no single check proves the artifact that users actually install. The repository explicitly treats a green test suite as necessary but insufficient.

## Local outcome gate

```sh
python3 -m unittest discover -s tests -t .
python3 scripts/render_agents.py --host claude-code --check
python3 scripts/render_agents.py --host codex --check
python3 scripts/build_adapter.py --host claude-code --check
python3 scripts/build_adapter.py --host codex --check
python3 scripts/validate_interfaces.py
python3 scripts/validate_roles.py
python3 scripts/smoke_install.py --host claude-code
claude plugin validate dist/claude-code
python3.11 -m unittest discover -s tests -t .
```

The README describes these as the repository's ten-command contributor outcome gate.

## CI

`.github/workflows/outcome-gate.yml` runs on pushes to `master` and pull requests. The suite matrix covers Python 3.11, 3.12, and 3.13 so TOML assertions use `tomllib` rather than silently skipping.

CI refuses to run the permission-sensitive suite as root because root can bypass `chmod 000`, which would make fail-closed state tests skip while the suite still reported success.

## Important test categories

- Schema conformance.
- Cross-field worker-return invariants.
- Dispatch concurrency/state corruption behavior.
- Guard allow/deny behavior and mutation tests.
- Generated-agent drift.
- Built-bundle drift.
- Host-interface provenance.
- Plugin manifest validity.
- Smoke installation against the actual host artifact.
- Python/TOML parser compatibility.

## Runtime TDD requirement

An implementer claiming `DONE` must report observed RED and GREEN counts. Tests introduced only after implementation are recorded as such and do not satisfy the same TDD evidence claim.
