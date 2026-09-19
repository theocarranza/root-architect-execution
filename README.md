# root-architect-execution

[![Outcome Gate](https://github.com/theocarranza/root-architect-execution/actions/workflows/outcome-gate.yml/badge.svg?branch=main)](https://github.com/theocarranza/root-architect-execution/actions/workflows/outcome-gate.yml)
[![Version](https://img.shields.io/github/v/release/theocarranza/root-architect-execution?sort=semver&color=brightgreen&label=version)](https://github.com/theocarranza/root-architect-execution/releases)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude_Code-supported-blueviolet.svg)](https://docs.anthropic.com/en/docs/claude-code)
[![Codex](https://img.shields.io/badge/Codex-supported-black.svg)](https://developers.openai.com/codex/)
[![Gemini](https://img.shields.io/badge/Gemini-supported-4285F4.svg)](https://antigravity.google)
[![Documentation](https://img.shields.io/badge/docs-project_documentation-informational.svg)](./docs/README.md)

A contract-driven execution protocol for running implementation plans through a **root architect** that owns planning, Git history, durable state, and acceptance gates while delegating product-code changes to isolated workers.

The project turns agent orchestration from a prose convention into an auditable execution system: roles are schema-declared, host agents are generated, worker handoffs are validated, dispatch state is durable, and host-specific guards enforce authority boundaries where the host exposes the required capabilities.

> **Core rule:** root owns authority; workers own bounded execution.

## Why this exists

Agentic coding becomes difficult to trust when planning, implementation, review, Git mutation, and final acceptance all happen inside the same context.

`root-architect-execution` separates those responsibilities:

```text
Human Owner
    |
    v
Root Architect
(plan + Git + ledger + gates)
    |
    v
Orchestrator
    |
    +-------------------+
    |                   |
    v                   v
Implementer        Validators
(write-scoped)     (spec + quality)
    |                   |
    +---------+---------+
              |
              v
       Structured Evidence
              |
              v
      Root Acceptance Gate
```

The root session does not silently replace a failed worker by writing delegated product code itself. Implementation, specification review, and quality review are separate roles, and their results cross schema-checked interfaces before root advances the run.

## Documentation

The repository contains a structured documentation interface under [`docs/`](./docs/README.md).

| Area         | Documentation                                                                                                |
| ------------ | ------------------------------------------------------------------------------------------------------------ |
| Product      | [`docs/00-product/`](./docs/00-product/) — vision, requirements, glossary                                    |
| Architecture | [`docs/01-architecture/`](./docs/01-architecture/) — system context, architecture, data model, ADRs          |
| Design       | [`docs/02-design/`](./docs/02-design/) — command contracts, components, workflows                            |
| Engineering  | [`docs/03-engineering/`](./docs/03-engineering/) — development, testing, standards, dependencies             |
| Operations   | [`docs/04-operations/`](./docs/04-operations/) — deployment, environments, observability, runbooks, recovery |
| Security     | [`docs/05-security/`](./docs/05-security/) — authority model, threat model, privacy                          |
| Delivery     | [`docs/06-delivery/`](./docs/06-delivery/) — roadmap, releases, changelog                                    |
| Guides       | [`docs/07-guides/`](./docs/07-guides/) — onboarding, usage, troubleshooting                                  |
| Templates    | [`docs/_templates/`](./docs/_templates/) — reusable documentation contracts                                  |

Start with the **[documentation index](./docs/README.md)** for the complete project model. For implementation work, read [`SKILL.md`](./SKILL.md) as the canonical execution protocol and [`HANDOFF.md`](./HANDOFF.md) for current execution status.

## Architecture at a glance

The repository is split into declarations, generated host representations, runtime controls, and verification.

```text
roles/*.json ---------+
hosts/*.json ---------+----> render_agents.py ----> host agent files
references/agents/* --+                              |
                                                     v
adapters/<host>/* ----------------------------> build_adapter.py
                                                     |
                                                     v
                                               dist/<host>/

schemas/*.json ---> briefs / reports / verdicts / dispatch state
                         |
                         v
                   runtime gates
                         |
             +-----------+-----------+
             |                       |
     dispatch_state.py         check_return.py
             |                       |
             +-----------+-----------+
                         |
                         v
                  root acceptance
```

The important architectural boundary is documented in [`docs/01-architecture/architecture.md`](./docs/01-architecture/architecture.md).

## Supported hosts

| Host        | Status                       | Notes                                                                                                                                          |
| ----------- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude Code | Supported                    | Generated agents, plugin bundle, identity-aware PreToolUse guards, smoke installation                                                          |
| Codex       | Supported                    | Generated TOML agents and install bootstrap; root/worker write isolation cannot currently use the same documented identity-aware hook boundary |
| Gemini      | Supported                    | Generated markdown agents, Antigravity CLI plugin bundle, layout metadata, first-party documented interface provenance                          |
| Cursor      | Reference / sourcing pending | Retained as a reference path; capability claims require re-verification before equivalent support is asserted                                  |

Host capabilities are declared under [`hosts/`](./hosts/) and checked against adapter interface provenance.

## Installation

### Claude Code

The plugin ships its own marketplace manifest.

```bash
# From a local clone
claude plugin marketplace add /path/to/root-architect-execution
claude plugin install root-architect-execution@root-architect-execution

# Or from GitHub
claude plugin marketplace add theocarranza/root-architect-execution
claude plugin install root-architect-execution@root-architect-execution
```

Restart Claude Code after installation. PreToolUse hooks are loaded at session start.

Verify the installation:

```bash
claude plugin list
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_roles.py"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_agents.py" \
  --host claude-code --check
```

### Codex

Codex installation requires the bundled bootstrap to materialize this repository's custom agent TOMLs:

```bash
python3 scripts/build_adapter.py --host codex

codex plugin add /path/to/dist/codex

python3 /path/to/dist/codex/install.py \
  --target .codex/agents \
  --plugin-root /path/to/dist/codex
```

### Gemini

Build the Gemini bundle:

```bash
python3 scripts/build_adapter.py --host gemini
```

The installable bundle is written to `dist/gemini`, providing `.gemini-plugin/plugin.json`, markdown role agents under `agents/`, role definitions, contracts, and scripts.

See [`docs/04-operations/deployment.md`](./docs/04-operations/deployment.md) for the complete installation and deployment model.

## Claude Code prerequisite: nesting depth

The architecture requires two levels of agent nesting:

```text
root -> orchestrator -> worker
```

Set the nesting cap **before launching Claude Code**:

```bash
export CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2
```

Then launch root as the main-thread agent:

```bash
CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2 \
claude --agent root-architect
```

Root performs a startup capability check before initializing an execution run.

## Execution model

A normal task follows a fail-closed gate sequence:

```text
root preflight
      |
      v
capability gate
      |
      v
schema-valid brief
      |
      v
open dispatch
      |
      v
implementer
  RED -> code -> GREEN
      |
      v
return gate
      |
      v
spec validator
      |
      v
quality validator
      |
      v
close dispatch
      |
      v
ledger + narrow commit
      |
      v
full outcome gate
```

A failed gate does not implicitly authorize root to bypass the failing role.

See [`docs/02-design/workflows.md`](./docs/02-design/workflows.md) for the complete workflow and retry/escalation model.

## Repository layout

| Path                                                   | Purpose                                                                   |
| ------------------------------------------------------ | ------------------------------------------------------------------------- |
| [`SKILL.md`](./SKILL.md)                               | Canonical protocol: authority, gates, state, task loop, stop conditions   |
| [`docs/`](./docs/)                                     | Structured project documentation                                          |
| [`roles/`](./roles/)                                   | Vendor-neutral role declarations                                          |
| [`hosts/`](./hosts/)                                   | Host capability declarations and evidence                                 |
| [`references/agents/`](./references/agents/)           | Single-source role behavior                                               |
| [`references/contracts.md`](./references/contracts.md) | Runtime handoff contracts                                                 |
| [`schemas/`](./schemas/)                               | JSON Schemas for roles, hosts, briefs, reports, verdicts, and state       |
| [`adapters/`](./adapters/)                             | Host-specific mechanics, hooks, manifests, installers, interfaces         |
| [`agents/`](./agents/)                                 | Generated Claude Code agent files                                         |
| [`scripts/`](./scripts/)                               | Validation, rendering, build, state, queue, return, and preflight tooling |
| [`tests/`](./tests/)                                   | Automated verification                                                    |
| [`dist/`](./dist/)                                     | Built host bundles; generated, not hand-edited                            |
| [`HANDOFF.md`](./HANDOFF.md)                           | Current implementation/e2e status                                         |

## Runtime contracts

Root works primarily through deterministic command and JSON interfaces.

Open a schema-checked dispatch:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py" open \
  --brief /tmp/brief.json \
  --run-id 20260907-task-3
```

Validate a worker return before treating it as evidence:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_return.py" \
  --role implementer \
  --file /tmp/return.txt \
  --task "..." \
  --attempt 1
```

Verify durable dispatch state during recovery:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py" verify
```

The command/contract interface is documented in [`docs/02-design/api.md`](./docs/02-design/api.md).

## Development

Never edit generated agents or `dist/` by hand.

For example, to change a role:

```bash
$EDITOR roles/impl-executor.json

python3 scripts/render_agents.py --host claude-code
python3 scripts/render_agents.py --host codex
python3 scripts/render_agents.py --host gemini

python3 scripts/validate_roles.py

python3 scripts/build_adapter.py --host claude-code
python3 scripts/build_adapter.py --host codex
python3 scripts/build_adapter.py --host gemini

python3 tools/lint.py --fix
```

See [`docs/03-engineering/development.md`](./docs/03-engineering/development.md) before changing declarations, host interfaces, guards, schemas, or packaging.

## Verification

The repository's outcome gate is intentionally broader than its unit test suite:

```bash
python3 -m unittest discover -s tests -t .

python3 tools/lint.py --check

python3 scripts/render_agents.py --host claude-code --check
python3 scripts/render_agents.py --host codex --check
python3 scripts/render_agents.py --host gemini --check

python3 scripts/build_adapter.py --host claude-code --check
python3 scripts/build_adapter.py --host codex --check
python3 scripts/build_adapter.py --host gemini --check

python3 scripts/validate_interfaces.py
python3 scripts/validate_roles.py

python3 scripts/smoke_install.py --host claude-code
claude plugin validate dist/claude-code

python3.12 -m unittest discover -s tests -t .
```

The final Python 3.12+ run ensures TOML-backed Codex assertions execute with `tomllib`.

The same outcome gate runs in GitHub Actions on pushes to `master` and pull requests.

For the rationale behind each layer, see [`docs/03-engineering/testing.md`](./docs/03-engineering/testing.md).

## Security model

The security boundary is primarily about **authority and mutation**, not network perimeter security.

Key rules include:

- root owns Git; workers do not commit;
- implementers may write only their brief-scoped paths;
- specification validators are read-only and have no shell;
- quality validators can inspect and run approved commands but cannot edit;
- untrusted durable dispatch state fails closed;
- generated artifacts and installable bundles are checked against their sources;
- destructive Git/release operations require explicit owner authorization.

See [`docs/05-security/security.md`](./docs/05-security/security.md) and [`docs/05-security/threat-model.md`](./docs/05-security/threat-model.md).

## Current project status

The authoritative status is maintained in [`HANDOFF.md`](./HANDOFF.md) and [`docs/06-delivery/roadmap.md`](./docs/06-delivery/roadmap.md).

The current architecture includes the root execution protocol, declared roles, schema-checked runtime contracts, generated Claude Code, Codex, and Gemini adapters, durable dispatch state, runtime guards, bundle validation, smoke installation, and CI outcome gating.

Live end-to-end evidence should remain distinguished from intended protocol behavior. Consult the handoff before assuming that every execution path has been observed in a real host run.

## Contributing

Before submitting a change:

1. Modify authoritative source rather than generated output.
2. Add or update targeted regression tests.
3. Regenerate affected host agents.
4. Rebuild affected host bundles.
5. Run the complete outcome gate (or install automated hooks via `python3 tools/install_hooks.py`).
6. Update documentation when a contract, capability, workflow, or operational procedure changes.

Contributor onboarding is available at [`docs/07-guides/onboarding.md`](./docs/07-guides/onboarding.md).

## Documentation standard

This repository uses a reusable software-project documentation interface organized around:

```text
product -> architecture -> design -> engineering
        -> operations -> security -> delivery -> guides
```

Reusable document templates are available in [`docs/_templates/`](./docs/_templates/).

---

For architecture details, start with **[`docs/README.md`](./docs/README.md)**.
