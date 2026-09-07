#!/usr/bin/env python3
"""PreToolUse guard: root must not write product code while a dispatch is open.

"Root writing product code" is the first red flag this skill lists, and it is
the one that reads as helpfulness in the moment — the worker stalled, the file
is small, root can just do it. That is a failed delegation with the evidence
trail deleted: no RED count, no diff for the validators, no attempt recorded.

The guard is narrow on purpose. It blocks an Edit/Write/NotebookEdit only when
all of these hold:

  * the call comes from the root session, not a subagent (the PreToolUse
    payload carries agent_type only inside a subagent);
  * a dispatch is open under <cwd>/.root-architect/state/;
  * the target path resolves inside that dispatch's write_paths.

Everything else passes through: the ledger, the plan, the state directory, any
path the open dispatch does not own, and every edit made while no dispatch is
open. Root is not locked out of its own repository — it is stopped from
overwriting the exact work it has delegated and is waiting on.

Exit 2 blocks the call and shows the reason to the model.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
PATH_KEYS = ("file_path", "notebook_path", "path")


def _allow():
    sys.exit(0)


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        # A guard that cannot read its input must not block real work.
        _allow()

    if payload.get("tool_name") not in WRITE_TOOLS:
        _allow()
    if payload.get("agent_type"):
        # Inside a worker. Its own grant governs; this guard is about root.
        _allow()

    try:
        from dispatch_state import active_dispatch
    except ImportError:
        _allow()

    workspace = payload.get("cwd") or "."
    _, dispatch = active_dispatch(workspace)
    if not dispatch:
        _allow()

    tool_input = payload.get("tool_input") or {}
    raw = next((tool_input[k] for k in PATH_KEYS if tool_input.get(k)), None)
    if not raw:
        _allow()

    root = Path(workspace).resolve()
    try:
        target = (root / raw).resolve() if not Path(raw).is_absolute() \
            else Path(raw).resolve()
    except OSError:
        _allow()

    brief = dispatch["brief"]
    for owned in brief.get("write_paths", []):
        try:
            owned_path = (root / owned).resolve()
        except OSError:
            continue
        if target == owned_path or owned_path in target.parents:
            _deny(
                "Root write guard: %s is a write path of open dispatch %s "
                "(task %r, attempt %d of %d, worker %s).\n"
                "Root does not write product code around a delegation. Either "
                "re-brief the worker with the correction, or close the dispatch "
                "first:\n"
                "  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py close "
                "--run-id %s --outcome blocked"
                % (raw, dispatch["run_id"], brief["task"], brief["attempt"],
                   brief["max_attempts"], brief["role"], dispatch["run_id"]))
    _allow()


if __name__ == "__main__":
    main()
