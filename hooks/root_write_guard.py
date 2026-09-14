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

Exit 2 blocks the call and shows the reason to the model. On Codex, canonical
apply_patch is intentionally outside this guard: Codex does not document
worker identity in PreToolUse, so blocking it would also block the worker.
Codex relies on the instructional boundary and root diff review. Dispatch state that
exists but cannot be trusted (unparseable, schema-invalid, or unreadable
because dispatch_state itself could not be imported) is also treated as a
block: this guard fails closed, never open, whenever it cannot prove no
delegation is open.
"""
import json
import os
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


def _report(stream, text):
    """Best-effort write. A stream that cannot take the text is not an error.

    Reporting is how a denial explains itself; it is not how a denial takes
    effect. Only the exit code blocks the call, so a broken pipe or a full
    device must never be allowed to propagate out of here.
    """
    try:
        stream.write(text)
        stream.flush()
    except Exception:
        pass


def _deny(reason):
    """Unconditionally terminal: exit 2 whatever the streams do.

    Two ways this used to fail open. (1) An OSError from the payload write
    escaped into a caller's except clause, which then allowed the call, or
    reached main()'s safety net, which called _deny() again on the same
    broken stream and let the second exception escape as exit 1. (2) Even
    with the exception contained, sys.exit(2) still runs the interpreter's
    shutdown flush, and a failing flush there makes Python report 120 no
    matter what this function decided.

    So: write and flush both streams under their own handling, then leave
    via os._exit, which cannot be re-entered and runs no shutdown flush.
    Both streams are already flushed above, so nothing reportable is lost.
    Only exit 2 blocks a call; 0, 1 and 120 are all fail-open.
    """
    _report(sys.stdout, json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }) + "\n")
    _report(sys.stderr, reason + "\n")
    os._exit(2)


def _resolve_owned(root, write_paths):
    """Resolve each write_path independently, skipping entries that raise.

    Returns a list of resolved Path objects. An entry that raises OSError or
    ValueError during resolution is skipped, and remaining entries are still
    resolved and returned. This isolation ensures one unresolvable path does
    not prevent checking the others.
    """
    owned_paths = []
    for owned in write_paths:
        try:
            owned_paths.append((root / owned).resolve())
        except (OSError, ValueError, RuntimeError):
            # RuntimeError is what pathlib.Path.resolve() raises for a
            # symlink loop on this interpreter ("Symlink loop from ...").
            # It is neither OSError nor ValueError, so it must be listed
            # explicitly or a looping entry crashes the whole hook.
            continue
    return owned_paths


def main():
    """Top-level safety net: any unexpected exception denies, never crashes.

    _allow() and _deny() communicate via SystemExit, which this must not
    swallow. Anything else escaping _main() is unproven, untrusted state by
    the guard's own contract, so it is treated the same as unreadable
    dispatch state: deny with exit 2, never let an internal error fall
    through to a bare exit 1 (which PreToolUse treats as non-blocking).
    """
    try:
        _main()
    except SystemExit:
        raise
    except Exception as e:
        _deny(
            "Root write guard: an internal error occurred while checking "
            "this call, so it cannot be verified safe:\n  %r\n"
            "This guard fails closed on internal errors, never open." % (e,))


def _main():
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
        directory = Path(workspace) / ".root-architect" / "state"
        if directory.is_dir():
            # glob() would swallow the PermissionError from an unreadable
            # directory and yield nothing, which reads exactly like "no state
            # files". List explicitly so a failure to look is never mistaken
            # for proof that nothing is there.
            try:
                names = os.listdir(directory)
            except OSError as e:
                _deny(
                    "Root write guard: dispatch_state could not be imported, "
                    "and the state directory %s exists but cannot be listed:\n"
                    "  %s\n"
                    "This guard cannot verify whether a dispatch is open, and "
                    "fails closed rather than open. Restore access to the "
                    "directory, or remove it if the run is over."
                    % (directory, e))
        else:
            names = []
        found = sorted(directory / name for name in names
                       if name.startswith("dispatch-") and name.endswith(".json"))
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
    raw_paths = [tool_input[k] for k in PATH_KEYS if tool_input.get(k)]
    if not raw_paths:
        _allow()

    brief = dispatch["brief"]
    # The try below covers resolution only. It must never span the ownership
    # comparison or the _deny() call: an OSError raised while *reporting* a
    # proven denial would otherwise be caught here and turned into _allow(),
    # exiting 0 and letting the delegated write through.
    try:
        root = Path(workspace).resolve()
        owned_paths = _resolve_owned(root, brief.get("write_paths", []))
    except (OSError, ValueError, RuntimeError):
        _allow()

    for raw in raw_paths:
        raw = _usable_path(raw)
        if raw is None:
            continue
        try:
            target = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        except (OSError, ValueError, RuntimeError):
            continue
        if any(target == owned or owned in target.parents for owned in owned_paths):
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
