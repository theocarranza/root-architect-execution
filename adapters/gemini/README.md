# adapters/gemini

How the Gemini host bundle is assembled and mapped from canonical framework roles.

`layout.json` declares source → destination for every piece of the bundle.
`scripts/build_adapter.py` reads it and compiles `dist/gemini/`; `--check`
rebuilds into a temporary directory and compares byte for byte against
`dist/gemini/` to prevent configuration drift.

## What lives here

| Path | Purpose |
|---|---|
| `manifest.template.json` | Becomes `.gemini-plugin/plugin.json` in the bundle |
| `agent-interface.json` | What this host offers, per claim, with first-party provenance |
| `layout.json` | Directory projection rules into `dist/gemini/` |
| `agents/*.md` | **Generated.** Never hand-edited — `render_agents.py --host gemini` compiles them |

## Host Mechanics & Execution Model

### 1. Function Calling Tool Mapping
Portable tool intents from canonical `roles/*.json` are mapped to native Gemini / Antigravity function calling targets:
- `read-files`: `view_file`
- `search-files`: `grep_search`, `find_by_name`
- `edit-files`: `replace_file_content`
- `create-files`: `write_to_file`
- `run-commands`: `run_command`
- `delegate`: `invoke_subagent`

### 2. Model Tier Allocation
- `cheap` & `mid` → `flash`
- `strong` → `pro`
- `inherit` → parent session model tier

### 3. Read-Only Enforcement
Gemini enforces read-only boundaries by omitting mutating tools (`write_to_file`, `replace_file_content`) from the agent's `tools` allowlist.

### 4. Subagent Delegation & Mailbox
- **Delegation**: Performed via `invoke_subagent` with target agent definitions declared with `subagent: true`.
- **Isolation**: Per-invocation workspace isolation is selectable via `Workspace: branch` (isolated Git worktree) or `Workspace: inherit`.
- **Nested Delegation**: Supported recursively across agent hierarchies.
- **Mailbox**: Asynchronous inter-agent messaging is performed via `send_message(Recipient=<conversationId>, Message=<text>)`.
