---
title: Threat Model
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-20
---

# Threat Model

| Threat | Impact | Control | Residual risk |
|---|---|---|---|
| Root bypasses failed delegation and edits worker-owned product paths | Invalidates isolation/evidence | Root write guard + diff review | Stronger on Claude than Codex because of host identity support. |
| Worker commits or mutates Git | Worker controls history/escapes review | Worker Git guard; Git owned by root | Host enforcement depends on runtime identity/tool interception. |
| Validator edits code | Self-review / hidden mutation | Mutation-class tools + guard | Misconfigured host adapter must be caught by capability/interface gates. |
| Spec and quality review are combined | Loss of independent review | Separate roles; return cross-field checks | Root could still violate protocol intentionally. |
| Malformed prose treated as PASS | False acceptance | JSON schema + `check_return.py` | Schema cannot encode every semantic truth; cross-field rules reduce gap. |
| Corrupt state interpreted as no active dispatch | Root writes through delegation | Fail-closed state verification | Manual state deletion remains privileged recovery action. |
| Stale generated agent or bundle ships | Runtime differs from reviewed source | render/build `--check`, byte comparison | Byte equality does not prove host acceptance. |
| Internally consistent but invalid plugin ships | Installation/runtime failure | host manifest validation + smoke install | Smoke coverage is host-specific. |
| Unsourced host capability is assumed | False security guarantee | `validate_interfaces.py`, provenance levels | Documentation can change upstream. |
| Python <3.12 skips TOML checks | Invalid Codex TOML can ship | CI on 3.12–3.14; explicit degraded-path warning | Local contributors can still run partial checks if they ignore warning. |
| Permission tests run as root | Fail-closed tests silently skip | CI refuses uid 0 | Local root runs remain unsafe evidence. |
| Unlimited retry/model escalation | Cost blowout / non-termination | max attempts, recorded escalation evidence, stop conditions | Human can explicitly choose further work. |
| Forged or stale preflight record admits a run | An ungoverned session appears governed | Admission binds literal boolean status to run, host, controller session, catalog, configuration, and current capability evidence | Same-user access still requires a proven controller boundary; legacy files are untrusted exports. |
| Empty or fabricated tool observation passes preflight | Root can dispatch without the required restricted path | Required delegation capability is explicit; unavailable or unknown blocks admission | A host may not expose the facts needed for runtime acceptance. |
| Direct dispatch bypasses admission | An open dispatch exists without a governed run | Every dispatch entry point uses the same admission service | Compatibility commands remain unsafe until migrated. |
| Two active worker tasks share a workspace | Concurrent writes make attribution and recovery unreliable | One authoritative reservation remains held until stop is confirmed or work is isolated | A timed-out worker can remain `stop_unknown`; replacement stays blocked. |
| Fake or reused report completes a task | Incorrect or fabricated work becomes accepted evidence | Controller captures immutable raw result and binds envelope, task, attempt, route, and provider identity in one transaction | Content validation cannot prove business correctness; orchestrator and root gates remain required. |
| Worker sends a result directly to root | The orchestrator is bypassed | Route validation accepts worker reports/questions only to the orchestrator | Root may relay operator answers through the orchestrator. |
| Worker can alter controller state or evidence | A same-user worker forges admission, results, or decisions | Independently proven storage/control isolation and authenticated controller operations | File permissions alone are insufficient with shared identities or shell access. |
