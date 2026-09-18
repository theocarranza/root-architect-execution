---
title: Threat Model
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
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
