#!/usr/bin/env python3
"""PreToolUse guard for Gemini / Antigravity: root must not write product code.

Root owns the plan, Git, and the ledger. Workers write product code.
When a dispatch is open under <workspace>/.root-architect/state/, this guard
intercepts write_to_file, replace_file_content, and mutating run_command calls,
blocking any attempt to modify files that resolve inside that dispatch's write_paths.

Fails closed on corrupted or unreadable dispatch state.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Support loading dispatch_state from both development tree and installed plugin
for _candidate in (HERE.parent / "scripts", HERE.parent.parent.parent / "scripts"):
    if (_candidate / "dispatch_state.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

WRITE_TOOLS = {"write_to_file", "replace_file_content"}


def _resolve_owned(root: Path, write_paths: list[str]) -> list[Path]:
    owned_paths: list[Path] = []
    for owned in write_paths:
        try:
            owned_paths.append((root / owned).resolve())
        except (OSError, ValueError, RuntimeError):
            continue
    return owned_paths


def _check_command_line(cmd: str, root: Path, owned_paths: list[Path]) -> str | None:
    """Detect simple redirection or write attempts targeting owned paths in shell commands."""
    for owned in owned_paths:
        rel = str(owned.relative_to(root)) if owned.is_relative_to(root) else str(owned)
        # Check if the path or filename is redirected to: '> file', '>> file', 'tee file'
        pattern = (
            rf"(?:>|>>|\btee\b\s+)(?:[^\w\s/.-]*\s*)?(?:{re.escape(rel)}|{re.escape(str(owned))})"
        )
        if re.search(pattern, cmd):
            return rel
    return None


def main() -> int:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            json.dump({"decision": "allow"}, sys.stdout)
            return 0
        payload = json.loads(raw_input)
    except Exception as e:
        json.dump(
            {
                "decision": "deny",
                "reason": f"Root write guard: failed to parse input JSON: {e}",
            },
            sys.stdout,
        )
        return 0

    tool_call = payload.get("toolCall") or {}
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args") or {}

    if tool_name not in WRITE_TOOLS and tool_name != "run_command":
        json.dump({"decision": "allow"}, sys.stdout)
        return 0

    # Determine workspace directory
    workspace_paths = payload.get("workspacePaths") or []
    workspace = workspace_paths[0] if workspace_paths else "."

    try:
        from dispatch_state import DispatchStateError, active_dispatch
    except ImportError:
        # Cannot import dispatch_state: check for state files directly
        state_dir = Path(workspace) / ".root-architect" / "state"
        if state_dir.is_dir():
            try:
                names = os.listdir(state_dir)
            except OSError as e:
                json.dump(
                    {
                        "decision": "deny",
                        "reason": f"Root write guard: dispatch_state could not be imported and state dir cannot be read: {e}",
                    },
                    sys.stdout,
                )
                return 0
            found = [n for n in names if n.startswith("dispatch-") and n.endswith(".json")]
            if found:
                json.dump(
                    {
                        "decision": "deny",
                        "reason": f"Root write guard: dispatch_state could not be imported and found state files: {found}",
                    },
                    sys.stdout,
                )
                return 0
        json.dump({"decision": "allow"}, sys.stdout)
        return 0

    try:
        _, dispatch = active_dispatch(workspace)
    except DispatchStateError as e:
        json.dump(
            {
                "decision": "deny",
                "reason": f"Root write guard: dispatch state at {e.path} cannot be trusted: {e.errors}",
            },
            sys.stdout,
        )
        return 0

    if not dispatch:
        json.dump({"decision": "allow"}, sys.stdout)
        return 0

    brief = dispatch.get("brief") or {}
    write_paths = brief.get("write_paths") or []
    root = Path(workspace).resolve()
    owned_paths = _resolve_owned(root, write_paths)

    if tool_name in WRITE_TOOLS:
        target_file = args.get("TargetFile")
        if not target_file or not isinstance(target_file, str):
            json.dump({"decision": "allow"}, sys.stdout)
            return 0

        try:
            target = (
                (root / target_file).resolve()
                if not Path(target_file).is_absolute()
                else Path(target_file).resolve()
            )
        except (OSError, ValueError, RuntimeError):
            json.dump({"decision": "allow"}, sys.stdout)
            return 0

        if any(target == owned or owned in target.parents for owned in owned_paths):
            run_id = dispatch.get("run_id", "unknown")
            task = brief.get("task", "unknown")
            attempt = brief.get("attempt", 1)
            max_attempts = brief.get("max_attempts", 3)
            role = brief.get("role", "worker")
            reason = (
                f"Root write guard: '{target_file}' is a write path of open dispatch {run_id} "
                f"(task '{task}', attempt {attempt} of {max_attempts}, worker {role}). "
                f"Root does not write product code around a delegation. Either re-brief the worker "
                f"with the correction, or close the dispatch first."
            )
            json.dump({"decision": "deny", "reason": reason}, sys.stdout)
            sys.stdout.write("\n")
            return 0

    elif tool_name == "run_command":
        cmd_line = args.get("CommandLine", "")
        if isinstance(cmd_line, str) and cmd_line:
            hit = _check_command_line(cmd_line, root, owned_paths)
            if hit:
                run_id = dispatch.get("run_id", "unknown")
                reason = (
                    f"Root write guard: command line modifies '{hit}', which is a write path of "
                    f"open dispatch {run_id}. Root does not write product code via shell around a delegation."
                )
                json.dump({"decision": "deny", "reason": reason}, sys.stdout)
                sys.stdout.write("\n")
                return 0

    json.dump({"decision": "allow"}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
