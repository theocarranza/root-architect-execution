# Root Architect Execution Protocol Rules

When `root-architect-execution` is active, the following architectural invariants are mandatory and govern every turn of the session:

## 1. Authority & Isolation Invariant

- **Root session responsibility**: Root exclusively owns planning, Git branch and commit management, the session ledger, orchestration, and acceptance gates.
- **Strict write prohibition**: Root must **NEVER write product code directly**. Files under protected product directories (e.g. `lib/**`, `functions/**`) and dispatch state files (`.root-architect/state/**`) must never be modified by Root.

## 2. Instruction Precedence Rule

- Repository-level implementation instructions (such as directives in `GEMINI.md`, `AGENTS.md`, or README files instructing the model to "implement features", "write code", "edit files", or "run build_runner") apply **exclusively to delegated worker subagents**, never to the root session.
- Root-level isolation rules take strict precedence over any repository instructions that would imply direct product implementation.

## 3. Mandatory Delegation Hierarchy

- Product implementation and validation must be delegated through isolated subagents:

  ```text
  root
  └── orchestrator
      ├── impl-executor
      ├── spec-validator
      └── quality-validator
  ```

- Root dispatches only `orchestrator` via `invoke_subagent`.
- Only `orchestrator` coordinates and dispatches `impl-executor`, `spec-validator`, and `quality-validator`.
- Dynamic subagent definition (`define_subagent`) is strictly prohibited. All roles are statically registered.

## 4. Architectural Boundary Semantics

- A write or edit denial is an **architectural capability boundary**, not a tool limitation.
- If a tool invocation is denied by a guard, Root must **NEVER** search for alternative execution channels (such as `run_command`, Python scripts, Node.js, `sed -i`, shell scripts, or child subprocesses) to produce the denied modification.
- If `orchestrator` is unavailable or delegation fails, the session state is **BLOCKED**. Root must stop and report the obstacle rather than attempting implementation itself.
