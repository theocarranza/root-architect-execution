---
title: Troubleshooting
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Orchestrator cannot dispatch workers | Nesting depth too low | Start a new Claude process with spawn depth 2. |
| Root cannot initialize run | Preflight missing/failed | Run root preflight with observed capabilities and inspect verdict. |
| `dispatch_state open` refuses | Invalid brief or another open dispatch | Validate brief; run `active` and `verify`. |
| Root edit denied | Path belongs to open dispatch or state is untrusted | Inspect dispatch; do not bypass guard. |
| Worker return rejected | Schema/cross-field mismatch | Correct once using exact role/task/attempt. |
| `DONE` rejected | Missing RED/GREEN evidence | Provide observed TDD counts/evidence. |
| Spec verdict rejected for commands | Spec role has no shell | Remove rerun claims; use quality validator for command execution. |
| Generated check fails | Source changed without regeneration | Run `render_agents.py` for affected host(s). |
| Bundle check fails | Source/generated files changed without rebuild | Run `build_adapter.py` then re-check. |
| Claude installed behavior is stale | Cached installed copy / no restart | Rebuild/update/reinstall and restart. |
| Manifest validates at repo root unexpectedly | Wrong validation target | Validate `dist/claude-code`, not repository root. |
| TOML checks skip locally | Python <3.11 without parser fallback | Run suite on Python 3.11+. |
| Permission tests skip | Running as root | Run as non-root; do not accept partial evidence. |
| Cursor capability gate warns | Inherited/unsourced host claims | Re-source against current Cursor documentation before claiming support. |
