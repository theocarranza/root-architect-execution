---
title: Release Process
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Release Process

## Prepare

1. Update authoritative source declarations/scripts/adapters.
2. Regenerate host agents.
3. Rebuild affected `dist/<host>` bundles.
4. Keep host/plugin version fields synchronized where required.
5. Update handoff/changelog/documentation for behavioral changes.

## Validate

Run the full outcome gate, including unit tests, role validation, per-host render checks, per-host bundle checks, interface provenance validation, Claude plugin validation, and smoke installation.

## Release

Publishing/tagging/releasing is an owner-authorized operation under the execution protocol. Do not automatically push, tag, release, or merge to `main` without explicit approval.

## Post-release verification

Install from the release/built artifact rather than the source tree, restart hosts that cache hooks/plugins, and rerun capability validation in the installed environment.

## Rollback

Return to a previously validated bundle/version, reinstall/update the host, and restart. Preserve the failed release evidence for diagnosis.
