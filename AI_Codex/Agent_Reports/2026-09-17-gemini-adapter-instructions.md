# Task Handoff: Gemini Adapter Implementation

## Context & Objective

Implement a fully compliant host adapter for **Gemini** inside `root-architect-execution`. This repository uses static compilation to map canonical agent definitions (`roles/*.json`) and validation schemas (`schemas/*.json`) into host-specific distributions (`dist/<host>/`) via `scripts/build_adapter.py`.

The adapter must honor the isolation model established in `ADR-0001` (host adapters as directories), `ADR-0002` (no hooks in distributed plugins), and `ADR-0003` (orchestrated worker isolation).

---

## Canonical Context & Schemas

| Artifact                     | Source Path                               | Validation Target / Authority                                    |
| ---------------------------- | ----------------------------------------- | ---------------------------------------------------------------- |
| **Host Capability Schema**   | `schemas/host-capability.schema.json`<br> | Target configuration schema for `hosts/gemini.json`<br>          |
| **Adapter Interface Schema** | `schemas/agent-interface.schema.json`<br> | Contract for `adapters/gemini/agent-interface.json`<br>          |
| **Adapter Layout Schema**    | `schemas/adapter-layout.schema.json`<br>  | Directory projection rules for `adapters/gemini/layout.json`<br> |
| **Canonical Agent Roles**    | `roles/*.json`<br>                        | Source definitions for all five framework roles                  |

|
| **Build Compiler** | `scripts/build_adapter.py`<br> | Compilation pipeline targeting `dist/gemini/`<br> |

---

## Required Deliverables

```
root-architect-execution/
├── hosts/
│   └── gemini.json
├── adapters/
│   └── gemini/
│       ├── agent-interface.json
│       ├── layout.json
│       ├── manifest.template.json
│       └── agents/
│           ├── root-architect.md
│           ├── orchestrator.md
│           ├── impl-executor.md
│           ├── spec-validator.md
│           └── quality-validator.md
└── dist/gemini/                         # Generated via compiler

```

---

## Detailed Implementation Specifications

### 1. Host Capability Declaration (`hosts/gemini.json`)

- Validate against `schemas/host-capability.schema.json`.

- Declare `host_id`: `"gemini"`.
- Set execution model parameters:
- `subagent_spawning`: `true`
- `max_nesting_depth`: `1` (strict subagent nesting cap)

- `native_hooks`: `false` (relies on Python guard scripts)

- `file_system_isolation`: `false`
- `prompt_format`: `"markdown"`
- `tool_format`: `"function_call"`

### 2. Interface Contract (`adapters/gemini/agent-interface.json`)

- Validate against `schemas/agent-interface.schema.json`.

- Expose repo-native dispatch and state tools as executable function-calling targets:
- `job_queue.py` (`enqueue`, `dequeue`, `status`)

- `mailbox.py` (`send`, `read`, `list`)

- `dispatch_state.py` (`record`, `query`)

- `check_return.py` (`validate`)

- Inject standard environment bindings (`ROOT_ARCHITECT_HOST=gemini`, `ROOT_ARCHITECT_STATE_DIR=.root-architect`).

### 3. Layout Mapping (`adapters/gemini/layout.json`)

- Validate against `schemas/adapter-layout.schema.json`.

- Map template agent paths and references into `dist/gemini/`:
- Destination for agents: `dist/gemini/agents/{role}.md`
- Destination for roles: `dist/gemini/roles/{role}.json`
- Destination for schemas: `dist/gemini/schemas/`
- Destination for scripts: `dist/gemini/scripts/`
- Destination for references: `dist/gemini/references/`

### 4. Role Prompt Templates (`adapters/gemini/agents/*.md`)

Create markdown templates modeled after `adapters/claude-code/agents/` for each of the five canonical roles:

- **`root-architect.md`**: Directs high-level architectural decomposition, brief generation, and review validation. Prohibited from executing direct workspace mutations without a task brief.

- **`orchestrator.md`**: Manages job queue progression, worker spawning, and receipt of validator reports.

- **`impl-executor.md`**: Restricted to scoped implementation boundaries designated in the input brief. Git write protection enforced.

- **`spec-validator.md`**: Evaluates implementation against requirements without modifying codebase state.

- **`quality-validator.md`**: Executes test suites and linting; emits pass/fail verdict envelopes.

### 5. Build Pipeline Registration

- Update `scripts/build_adapter.py` to add `"gemini"` to supported target host choices.

- Ensure asset copying, schema injection, and role compilation mirror the existing `claude-code` and `codex` targets.

---

## Verification Gates & Acceptance Commands

Execute the following verification sequence in order from repository root:

```bash
# 1. Interface validation
python3 scripts/validate_interfaces.py --adapter gemini

# 2. Role definition validation
python3 scripts/validate_roles.py --host gemini

# 3. Compilation check
python3 scripts/build_adapter.py --host gemini

# 4. End-to-end plugin tests
pytest tests/test_plugin.py

```

All commands must exit with code `0`. Any schema validation failure on generated JSON files must be resolved at the adapter template level rather than mutating `schemas/*.json` directly.
