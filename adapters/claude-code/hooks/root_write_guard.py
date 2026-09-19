#!/usr/bin/env python3
"""PreToolUse guard: root must not write product code or bypass the orchestrator.

Root owns the plan, Git, and the ledger. Workers write product code.
When a dispatch is open under <cwd>/.root-architect/state/, this guard
intercepts Edit, Write, MultiEdit, NotebookEdit, Bash, and Agent calls.

Fails closed on corrupted or unreadable dispatch state.

Three layered guards (in evaluation order):

  Guard 1 — State self-close & direct edit block
    Root must never self-close a dispatch or mutate dispatch state files under
    .root-architect/state/. Only the orchestrator drives
    ``scripts/dispatch_state.py close`` after validating worker returns.

  Guard 2 — Global product-code write block (lib/, functions/)
    Root must never write product code directly. Files under lib/** or
    functions/** are protected: writes from root are denied unconditionally,
    regardless of whether a dispatch is open. Product implementation must be
    delegated via the orchestrator to a worker dispatch.

  Guard 3 — Worker identity & subagent spawning
    Only the orchestrator may spawn workers (impl-executor, spec-validator,
    quality-validator). Root may only spawn 'orchestrator'. Workers cannot
    spawn subagents. Only worker roles are permitted to write product code.

Exit 2 blocks the call and shows the reason to the model.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import NoReturn

HERE = Path(__file__).resolve().parent

# Support loading dispatch_state from both development tree and installed plugin
for _candidate in (HERE.parent / "scripts", HERE.parent.parent.parent / "scripts"):
    if (_candidate / "dispatch_state.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
PATH_KEYS = ("file_path", "notebook_path", "path")

# Product-code directories root must never write directly
_PROTECTED_FIRST_SEGMENTS = frozenset({"lib", "functions"})

WORKER_ROLES = frozenset({"impl-executor", "implementer", "worker"})
VALIDATOR_ROLES = frozenset({"spec-validator", "quality-validator", "validator"})
ALL_WORKER_ROLES = WORKER_ROLES | VALIDATOR_ROLES

_STATE_MUTATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"dispatch_state\.py\b.*\bclose\b"),
    re.compile(r"dispatch_state\.py\b.*\baborted\b"),
    re.compile(r"python3?\s+-c\b.*\.root-architect[\\/]?state"),
    re.compile(r"(?:>|>>|tee\s)\s*\.root-architect[\\/]state[\\/]dispatch-"),
    re.compile(r"\brm\b.*\.root-architect[\\/]state[\\/]dispatch-"),
    re.compile(r"\bjq\b.*dispatch-.*\.json"),
    re.compile(r"\bsed\b.*-i\b.*dispatch-.*\.json"),
    re.compile(r"json\.dump\b.*dispatch-"),
    re.compile(r"open\(['\"].+\.root-architect[\\/]state[\\/]"),
]


def _usable_path(value):
    """A value is usable as a path only if it is a non-empty, null-free str."""
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    return value


def _allow() -> NoReturn:
    sys.exit(0)


def _report(stream, text):
    try:
        stream.write(text)
        stream.flush()
    except Exception:
        pass


def _deny(reason: str) -> NoReturn:
    _report(
        sys.stdout,
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
        + "\n",
    )
    _report(sys.stderr, reason + "\n")
    os._exit(2)


def get_caller_role(payload: dict) -> str:
    """Extract caller identity from agent_type payload field or environment. Defaults to 'root'."""
    agent_type = payload.get("agent_type")
    if agent_type and isinstance(agent_type, str):
        if ":" in agent_type:
            agent_type = agent_type.split(":")[-1]
        return agent_type.strip().lower()
    env_role = os.environ.get("AGENT_ROLE", "").strip().lower()
    return env_role if env_role else "root"


def _is_protected_product_path(target: Path, root: Path) -> bool:
    try:
        rel = target.relative_to(root)
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in _PROTECTED_FIRST_SEGMENTS


def _is_state_path(target: Path, root: Path) -> bool:
    try:
        rel = target.relative_to(root)
    except ValueError:
        return False
    return len(rel.parts) >= 2 and rel.parts[0] == ".root-architect" and rel.parts[1] == "state"


def _resolve_owned(root, write_paths):
    owned_paths = []
    for owned in write_paths:
        try:
            owned_paths.append((root / owned).resolve())
        except (OSError, ValueError, RuntimeError):
            continue
    return owned_paths


def _check_shell_product_write(cmd: str) -> str | None:
    for seg in _PROTECTED_FIRST_SEGMENTS:
        pattern = rf"(?:>|>>|\btee\b\s+)(?:[^\w\s/.-]*\s*)?(?:{seg}/|[^\w\s/.-]*\b{seg}/)"
        if re.search(pattern, cmd):
            return seg
    return None


def main():
    try:
        _main()
    except SystemExit:
        raise
    except Exception as e:
        _deny(
            "Root write guard: an internal error occurred while checking "
            "this call, so it cannot be verified safe:\n  %r\n"
            "This guard fails closed on internal errors, never open." % (e,)
        )


def _main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        _allow()

    if not isinstance(payload, dict):
        _allow()

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        _allow()

    if tool_name not in WRITE_TOOLS and tool_name not in ("Bash", "Agent"):
        _allow()

    cwd = payload.get("cwd")
    if cwd is None or cwd == "":
        workspace = "."
    else:
        usable = _usable_path(cwd)
        if usable is None:
            _allow()
        workspace = usable

    root = Path(workspace).resolve()
    caller_role = get_caller_role(payload)
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        _allow()

    # ------------------------------------------------------------------
    # GUARD 3: Subagent spawning restrictions (Agent tool)
    # ------------------------------------------------------------------
    if tool_name == "Agent":
        target_type = (
            tool_input.get("agent_type")
            or tool_input.get("subagent_type")
            or tool_input.get("type")
            or tool_input.get("name", "")
        )
        if isinstance(target_type, str) and ":" in target_type:
            target_type = target_type.split(":")[-1]
        target_type = target_type.strip().lower() if isinstance(target_type, str) else ""

        if caller_role in ALL_WORKER_ROLES:
            _deny("Worker write guard: workers are not permitted to dispatch subagents.")

        if caller_role == "orchestrator":
            if target_type == "orchestrator":
                _deny(
                    "Orchestrator write guard: orchestrator cannot dispatch another orchestrator."
                )
            if target_type not in ALL_WORKER_ROLES and target_type != "":
                _deny(
                    f"Orchestrator may only dispatch worker subagents ({sorted(ALL_WORKER_ROLES)}), "
                    f"attempted: '{target_type}'."
                )
            _allow()

        # Root: can only dispatch orchestrator
        if target_type != "orchestrator":
            _deny(
                f"Root write guard [subagent boundary]: root is strictly restricted to dispatching "
                f"'orchestrator' (roles/root-architect.json delegates_to: ['orchestrator']). "
                f"Only the orchestrator can spawn workers. Attempted to dispatch '{target_type}'. "
                f"Root must not bypass the orchestrator layer or invoke workers directly."
            )
        _allow()

    # ------------------------------------------------------------------
    # GUARD 1 & 2: Shell commands (Bash) mutating state or product code
    # ------------------------------------------------------------------
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if isinstance(cmd, str) and cmd:
            if caller_role in ("root", "orchestrator"):
                for pattern in _STATE_MUTATION_PATTERNS:
                    if pattern.search(cmd):
                        _deny(
                            "Root write guard [Guard 1 — state self-close]: command line appears to "
                            "mutate a dispatch state file (.root-architect/state/dispatch-*.json). "
                            "Dispatch lifecycle is managed exclusively by the orchestrator after "
                            "validating the worker's return via `scripts/dispatch_state.py close`. "
                            "Root must not self-close a dispatch."
                        )
                hit_seg = _check_shell_product_write(cmd)
                if hit_seg:
                    _deny(
                        f"Root write guard [Guard 2 — product-code write block]: command line writes "
                        f"to protected product directory ('{hit_seg}/'). Root must never write product "
                        f"code directly via shell."
                    )
        _allow()

    # ------------------------------------------------------------------
    # GUARD 1 & 2: Direct file writes (Edit, Write, NotebookEdit, MultiEdit)
    # ------------------------------------------------------------------
    raw_paths = [tool_input[k] for k in PATH_KEYS if tool_input.get(k)]
    if not raw_paths:
        _allow()

    for raw in raw_paths:
        raw = _usable_path(raw)
        if raw is None:
            continue
        try:
            target = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        except (OSError, ValueError, RuntimeError):
            continue

        # State directory protection: root must never edit dispatch state files directly
        if _is_state_path(target, root) and caller_role == "root":
            _deny(
                "Root write guard [Guard 1 — state edit block]: root must not directly edit "
                "or overwrite dispatch state files under .root-architect/state/."
            )

        # Product code protection: root must never edit product code directly
        if _is_protected_product_path(target, root) and caller_role not in WORKER_ROLES:
            _deny(
                f"Root write guard [Guard 2 — product-code write block]: '{raw}' is under a "
                f"protected product directory (lib/ or functions/). Root must never write product "
                f"code directly — delegate via `scripts/job_queue.py` to a worker dispatch. "
                f"(caller={caller_role!r})"
            )

    # ------------------------------------------------------------------
    # DISPATCH STATE VERIFICATION & WRITE-PATH CHECK
    # ------------------------------------------------------------------
    try:
        from dispatch_state import DispatchStateError, active_dispatch
    except ImportError:
        directory = Path(workspace) / ".root-architect" / "state"
        if directory.is_dir():
            try:
                names = os.listdir(directory)
            except OSError as e:
                _deny(
                    "Root write guard: dispatch_state could not be imported, "
                    "and the state directory %s exists but cannot be listed:\n"
                    "  %s\n"
                    "This guard cannot verify whether a dispatch is open, and "
                    "fails closed rather than open. Restore access to the "
                    "directory, or remove it if the run is over." % (directory, e)
                )
        else:
            names = []
        found = sorted(
            directory / name
            for name in names
            if name.startswith("dispatch-") and name.endswith(".json")
        )
        if found:
            _deny(
                "Root write guard: dispatch_state could not be imported, so "
                "this guard cannot verify whether a dispatch is open. Found "
                "state file(s) that may represent an open dispatch: %s.\n"
                "Restore scripts/dispatch_state.py, or remove the stale "
                "state file(s) if the run is over." % ", ".join(str(f) for f in found)
            )
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
            "  rm %s   # once the run is over" % (e.path, "\n  ".join(e.errors), e.path, e.path)
        )
    if not dispatch:
        _allow()

    brief = dispatch["brief"]
    try:
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
            if caller_role in WORKER_ROLES:
                _allow()

            _deny(
                "Root write guard: %s is a write path of open dispatch %s "
                "(task %r, attempt %d of %d, worker %s).\n"
                "Root does not write product code around a delegation. Either "
                "re-brief the worker with the correction, or close the dispatch "
                "first:\n"
                "  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py close "
                "--run-id %s --outcome blocked"
                % (
                    raw,
                    dispatch["run_id"],
                    brief["task"],
                    brief["attempt"],
                    brief["max_attempts"],
                    brief["role"],
                    dispatch["run_id"],
                )
            )
    _allow()


if __name__ == "__main__":
    main()
