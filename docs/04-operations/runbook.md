---
title: Operations Runbook
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Operations Runbook

## Root cannot dispatch nested worker

**Symptom:** orchestrator lacks the agent/delegation tool.

**Check:** verify the host nesting cap was configured before process start.

**Claude remediation:** launch a fresh process with `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2`.

## Root write is denied unexpectedly

Run:

```sh
python3 scripts/dispatch_state.py verify
python3 scripts/dispatch_state.py active
```

Inspect the named corrupt/untrusted record. Repair or remove state only after establishing the real run status. Do not bypass the guard by editing product code elsewhere.

## Generated files are stale

```sh
python3 scripts/render_agents.py --host <host>
python3 scripts/build_adapter.py --host <host>
```

Then rerun `--check`.

## Installed Claude plugin behaves like an older build

The install cache is a copy. Rebuild, bump/update/reinstall as required, and restart Claude Code. Hook changes always require restart.

## Worker return rejected

Run `check_return.py` with the exact role/task/attempt. A malformed return gets one corrective formatting retry. If it remains malformed, stop rather than interpreting prose manually.

## Claude root agent not found in e2e environment

Ensure plugin installation state was not overwritten when adding permissions. Merge permissions into the existing host settings instead of replacing the file.

## Permission mode breaks the run

The documented e2e experience found `dontAsk` can silently deny required Bash/external reads. Use a mode/allow-list that actually grants the tools declared by the root role, and verify via preflight.

## CI permission-state tests skip

Do not run the relevant suite as uid 0. The CI gate deliberately refuses this because root bypasses permission bits.
