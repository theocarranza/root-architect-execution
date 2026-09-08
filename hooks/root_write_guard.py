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

Exit 2 blocks the call and shows the reason to the model. Dispatch state that
exists but cannot be trusted (unparseable, schema-invalid, or unreadable
because dispatch_state itself could not be imported) is also treated as a
block: this guard fails closed, never open, whenever it cannot prove no
delegation is open.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
PATH_KEYS = ("file_path", "notebook_path", "path")


def _usable_path(value):
    """A value is usable as a path only if it is a non-empty, null-free str.

    Every other shape raises out of Path() or a "/" join — TypeError for a
    non-string, ValueError for an embedded null byte. Callers treat a None
    return as malformed hook input and allow the call through.
    """
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    return value


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

    if not isinstance(payload, dict):
        # Not a JSON object: cannot read tool_name from it. Not real work.
        _allow()

    if not isinstance(payload.get("tool_name"), str):
        # A list or dict tool_name is unhashable and cannot even be tested
        # for membership. Malformed hook input, not real work.
        _allow()
    if payload["tool_name"] not in WRITE_TOOLS:
        _allow()
    if payload.get("agent_type"):
        # Inside a worker. Its own grant governs; this guard is about root.
        _allow()

    cwd = payload.get("cwd")
    if cwd is None or cwd == "":
        workspace = "."
    else:
        workspace = _usable_path(cwd)
        if workspace is None:
            # cwd is not a path we can build on. Malformed hook input.
            _allow()

    try:
        from dispatch_state import active_dispatch, DispatchStateError
    except ImportError:
        # Cannot verify dispatch state without the module. Do not trust that
        # no dispatch is open just because we cannot check: look for state
        # files directly, with no import needed.
        found = sorted(Path(workspace).glob(".root-architect/state/dispatch-*.json"))
        if found:
            _deny(
                "Root write guard: dispatch_state could not be imported, so "
                "this guard cannot verify whether a dispatch is open. Found "
                "state file(s) that may represent an open dispatch: %s.\n"
                "Restore scripts/dispatch_state.py, or remove the stale "
                "state file(s) if the run is over."
                % ", ".join(str(f) for f in found))
        _allow()

    try:
        _, dispatch = active_dispatch(workspace)
    except DispatchStateError as e:
        _deny(
            "Root write guard: dispatch state at %s cannot be trusted:\n  %s\n"
            "This guard fails closed when it cannot verify whether a "
            "dispatch is open. Inspect and recover:\n"
            "  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py verify\n"
            "  cat %s\n"
            "  rm %s   # once the run is over"
            % (e.path, "\n  ".join(e.errors), e.path, e.path))
    if not dispatch:
        _allow()

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        # Malformed hook input, not malformed state. Do not block real work.
        _allow()
    raw = next((tool_input[k] for k in PATH_KEYS if tool_input.get(k)), None)
    if raw is None:
        _allow()
    raw = _usable_path(raw)
    if raw is None:
        # An integer, a list or a null-byte path is not a write we can locate.
        _allow()

    try:
        root = Path(workspace).resolve()
        target = (root / raw).resolve() if not Path(raw).is_absolute() \
            else Path(raw).resolve()
    except (OSError, ValueError):
        _allow()

    brief = dispatch["brief"]
    for owned in brief.get("write_paths", []):
        try:
            owned_path = (root / owned).resolve()
        except (OSError, ValueError):
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
