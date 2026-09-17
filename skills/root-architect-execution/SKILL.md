---
name: root-architect-execution
description: Run a governing implementation plan through isolated workers while root owns Git, the ledger, and outcome gates.
---

This is the Codex entry point. The canonical protocol — gates, dispatch state,
stop conditions — lives in the plugin's own `SKILL.md` and governs you. Codex
sets no plugin-root variable of its own, so export `PLUGIN_ROOT` to the
installed plugin root before running anything here, then read that file:

```bash
export RAE_HOST=codex
export PLUGIN_ROOT=/absolute/path/to/the/installed/plugin
cat "$PLUGIN_ROOT/SKILL.md"
```

Codex plugin installation copies the bundle but has no documented post-install
callback for custom agents, so materialize them explicitly before dispatching:

```bash
python3 "$PLUGIN_ROOT/scripts/validate_roles.py" --host codex
python3 "$PLUGIN_ROOT/scripts/render_agents.py" --host codex --check
python3 "$PLUGIN_ROOT/install.py" --target .codex/agents --plugin-root "$PLUGIN_ROOT"
```

Start a new Codex conversation afterwards so the custom agents load from the
installed state. The source repository keeps generated reference files in
`adapters/codex/agents`; the bootstrap writes the active TOMLs to the selected
Codex agent directory and never into the source tree.

Codex does not document worker identity in `PreToolUse`, so root-versus-worker
write separation is instructional and enforced by root's review of the worker
diff. Validator read-only isolation remains host-enforced through
`sandbox_mode = "read-only"`.
