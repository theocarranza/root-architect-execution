---
title: Contributor Onboarding
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Contributor Onboarding

## Understand the authority model first

Read, in order:

1. Repository `README.md`.
2. `SKILL.md`.
3. `references/contracts.md`.
4. `references/agents/README.md`.
5. `HANDOFF.md`.
6. These architecture/testing/security docs.

## Verify your checkout

```sh
git status
python3 scripts/validate_roles.py
python3 scripts/validate_interfaces.py
python3 -m unittest discover -s tests -t .
python3 tools/install_hooks.py
```

Use Python 3.12+ at least once so Codex TOML is parsed by the standard library. Running `python3 tools/install_hooks.py` activates automated pre-commit and pre-push quality gates.

## Golden rule for edits

Do not start by editing `dist/` or generated host agent files. Find the authoritative declaration/reference/adapter source, change it, regenerate, rebuild, then run drift checks.

## First useful contribution

A low-risk first change is a test or documentation improvement that does not alter host authority. Changes to guards, dispatch state, schemas, role capabilities, host interfaces, or packaging are high-leverage and should include targeted regression tests plus the complete outcome gate.
