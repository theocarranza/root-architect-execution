#!/usr/bin/env python3
"""PreToolUse guard for Gemini / Antigravity: root must not write product code.

Root owns the plan, Git, and the ledger. Workers write product code.
When a dispatch is open under <workspace>/.root-architect/state/, this guard
intercepts write_to_file, replace_file_content, and mutating run_command calls,
blocking any attempt to modify files that resolve inside that dispatch's write_paths.

Fails closed on corrupted or unreadable dispatch state.

Layered guards (in evaluation order):

  Guard 1 — State self-close & direct edit block
    Root must never self-close a dispatch or edit state files under
    .root-architect/state/ directly. Only the orchestrator drives
    ``scripts/dispatch_state.py close`` after validating worker returns.

  Guard 2 — Global product-code write block (lib/, functions/)
    Root must never write product code directly. Files under lib/** or
    functions/** are protected: writes from root are denied unconditionally,
    regardless of whether a dispatch is open. Product implementation must be
    delegated to a worker subagent.

  Guard 3 — Caller identity differentiation
    Identity is established via AGENT_ROLE environment variable or payload
    attributes (agent_role/agent_type/caller). Unspecified identity defaults
    to 'root' (fail closed). Only worker roles (impl-executor, implementer,
    worker) are permitted to write product code within their brief's write_paths.

  Legacy guard — dispatch write-path check
    When a dispatch is open, root writes to any owned path in that dispatch's
    write_paths are denied.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# Support loading dispatch_state from both development tree and installed plugin
for _candidate in (HERE.parent / "scripts", HERE.parent.parent.parent / "scripts"):
    if (_candidate / "dispatch_state.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

WRITE_TOOLS = {"write_to_file", "replace_file_content"}

# Product-code directories root must never write directly
_PROTECTED_FIRST_SEGMENTS = frozenset({"lib", "functions"})

WORKER_ROLES = frozenset({"impl-executor", "worker", "implementer"})

# Patterns indicating run_command is mutating dispatch state files
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


def get_caller_role(payload: dict[str, Any]) -> str:
    """Extract caller role from payload or environment. Defaults to 'root'."""
    caller = payload.get("agent_role") or payload.get("agent_type") or payload.get("caller")
    if caller and isinstance(caller, str):
        if ":" in caller:
            caller = caller.split(":")[-1]
        return caller.strip().lower()
    env_role = os.environ.get("AGENT_ROLE", "").strip().lower()
    return env_role if env_role else "root"


def _is_protected_product_path(target: Path, root: Path) -> bool:
    """Return True when target is inside a protected product directory."""
    try:
        rel = target.relative_to(root)
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in _PROTECTED_FIRST_SEGMENTS


def _is_state_path(target: Path, root: Path) -> bool:
    """Return True when target resolves inside .root-architect/state/."""
    try:
        rel = target.relative_to(root)
    except ValueError:
        return False
    return len(rel.parts) >= 2 and rel.parts[0] == ".root-architect" and rel.parts[1] == "state"


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
        pattern = (
            rf"(?:>|>>|\btee\b\s+)(?:[^\w\s/.-]*\s*)?(?:{re.escape(rel)}|{re.escape(str(owned))})"
        )
        if re.search(pattern, cmd):
            return rel
    return None


_POSIX_MUTATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:sed\s+.*(?:-i|--in-place))\b.*(?:\b|/)(?:lib|functions)/"),
    re.compile(r"\b(?:cp|mv|rm|touch|truncate|patch|install|dd)\b.*(?:\b|/)(?:lib|functions)/"),
]

_INTERPRETER_MUTATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:python3?|node|ruby|perl|bash|sh|zsh)\s+.*-c\s+.*(?:\b|/)(?:lib|functions)/"),
    re.compile(r"(?:python3?|node|ruby|perl|bash|sh|zsh)\s+.*-e\s+.*(?:\b|/)(?:lib|functions)/"),
    re.compile(r"(?:python3?|bash|sh|zsh)\s+\S+\.(?:py|sh)\b.*(?:\b|/)(?:lib|functions)/"),
    re.compile(r"open\s*\(\s*['\"][^'\"]*(?:lib|functions)/"),
    re.compile(r"open\s*\([^)]*['\"][wa+]"),
    re.compile(r"(?:writeFileSync|createWriteStream)\s*\(\s*['\"][^'\"]*(?:lib|functions)/"),
    re.compile(r"Path\s*\(\s*['\"][^'\"]*(?:lib|functions)/[^'\"]*['\"]\s*\)\.write_"),
]

HARD_STOP_PRODUCT_DENIAL = (
    "Root write guard [Guard 2 — product-code write block]:\n"
    "DENIED: Root attempted to modify protected product code in a protected product directory.\n\n"
    "Root Architect mode is active.\n\n"
    "Do not retry this operation using:\n"
    "- run_command\n"
    "- Python\n"
    "- shell scripts\n"
    "- sed\n"
    "- interpreters\n"
    "- alternate file tools\n"
    "- indirect subprocesses\n\n"
    "Required action:\n"
    "1. Dispatch `orchestrator` through the approved subagent mechanism.\n"
    "2. If `orchestrator` is unavailable, mark the session BLOCKED and stop implementation.\n\n"
    "This denial represents an architectural boundary, not a tool limitation."
)


def _check_shell_product_write(cmd: str) -> str | None:
    """Detect shell redirection, file utility mutation, or interpreter execution targeting protected product code."""
    for seg in _PROTECTED_FIRST_SEGMENTS:
        pattern = rf"(?:>|>>|\btee\b\s+(?:-a\s+)?)(?:[^\w\s/.-]*\s*)?(?:{seg}/|[^\w\s/.-]*\b{seg}/)"
        if re.search(pattern, cmd):
            return seg

    for pattern in _POSIX_MUTATION_PATTERNS:
        if pattern.search(cmd):
            for seg in _PROTECTED_FIRST_SEGMENTS:
                if f"{seg}/" in cmd:
                    return seg
            return "lib"

    for pattern in _INTERPRETER_MUTATION_PATTERNS:
        if pattern.search(cmd):
            for seg in _PROTECTED_FIRST_SEGMENTS:
                if f"{seg}/" in cmd:
                    return seg
            return "lib"

    return None


def _deny(reason: str) -> int:
    json.dump({"decision": "deny", "reason": reason}, sys.stdout)
    sys.stdout.write("\n")
    return 0


def _allow() -> int:
    json.dump({"decision": "allow"}, sys.stdout)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            return _allow()
        payload = json.loads(raw_input)
    except Exception as e:
        return _deny(f"Root write guard: failed to parse input JSON: {e}")

    tool_call = payload.get("toolCall") or {}
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args") or {}

    if tool_name not in WRITE_TOOLS and tool_name != "run_command":
        return _allow()

    # Determine workspace directory
    workspace_paths = payload.get("workspacePaths") or []
    workspace = workspace_paths[0] if workspace_paths else "."
    root = Path(workspace).resolve()

    caller_role = get_caller_role(payload)

    # ------------------------------------------------------------------
    # GUARD 1: Block run_command that mutates dispatch state or product code.
    # ------------------------------------------------------------------
    if tool_name == "run_command":
        cmd_line = args.get("CommandLine", "")
        if isinstance(cmd_line, str) and cmd_line:
            if caller_role in ("root", "orchestrator"):
                for pattern in _STATE_MUTATION_PATTERNS:
                    if pattern.search(cmd_line):
                        return _deny(
                            "Root write guard [Guard 1 — state self-close]: the command line appears "
                            "to mutate a dispatch state file (.root-architect/state/dispatch-*.json). "
                            "Dispatch lifecycle is managed exclusively by the orchestrator after "
                            "validating the worker's return via `scripts/dispatch_state.py close`. "
                            "Root must not self-close a dispatch."
                        )
            if caller_role in ("root", "orchestrator"):
                hit_seg = _check_shell_product_write(cmd_line)
                if hit_seg:
                    return _deny(HARD_STOP_PRODUCT_DENIAL)

    # ------------------------------------------------------------------
    # GUARD 2: Direct file writes to state files or protected product dirs
    # ------------------------------------------------------------------
    if tool_name in WRITE_TOOLS:
        target_file = args.get("TargetFile")
        if target_file and isinstance(target_file, str):
            try:
                target = (
                    (root / target_file).resolve()
                    if not Path(target_file).is_absolute()
                    else Path(target_file).resolve()
                )
            except (OSError, ValueError, RuntimeError):
                target = None

            if target:
                # State directory protection: root must not edit dispatch files directly
                if _is_state_path(target, root) and caller_role == "root":
                    return _deny(
                        "Root write guard [Guard 1 — state edit block]: root must not directly edit "
                        "or overwrite dispatch state files under .root-architect/state/."
                    )

                # Product code protection: root and orchestrator must never edit product code
                if _is_protected_product_path(target, root) and caller_role not in WORKER_ROLES:
                    return _deny(HARD_STOP_PRODUCT_DENIAL)

    # ------------------------------------------------------------------
    # DISPATCH STATE VERIFICATION & WRITE-PATH CHECK
    # ------------------------------------------------------------------
    try:
        from dispatch_state import DispatchStateError, active_dispatch
    except ImportError:
        state_dir = Path(workspace) / ".root-architect" / "state"
        if state_dir.is_dir():
            try:
                names = os.listdir(state_dir)
            except OSError as e:
                return _deny(
                    f"Root write guard: dispatch_state could not be imported and state dir cannot be read: {e}"
                )
            found = [n for n in names if n.startswith("dispatch-") and n.endswith(".json")]
            if found:
                return _deny(
                    f"Root write guard: dispatch_state could not be imported and found state files: {found}"
                )
        return _allow()

    try:
        _, dispatch = active_dispatch(workspace)
    except DispatchStateError as e:
        return _deny(f"Root write guard: dispatch state at {e.path} cannot be trusted: {e.errors}")

    if not dispatch:
        return _allow()

    brief = dispatch.get("brief") or {}
    write_paths = brief.get("write_paths") or []
    owned_paths = _resolve_owned(root, write_paths)

    if tool_name in WRITE_TOOLS:
        target_file = args.get("TargetFile")
        if not target_file or not isinstance(target_file, str):
            return _allow()

        try:
            target = (
                (root / target_file).resolve()
                if not Path(target_file).is_absolute()
                else Path(target_file).resolve()
            )
        except (OSError, ValueError, RuntimeError):
            return _allow()

        if any(target == owned or owned in target.parents for owned in owned_paths):
            # If caller is a worker, the write is permitted within write_paths
            if caller_role in WORKER_ROLES:
                return _allow()

            run_id = dispatch.get("run_id", "unknown")
            task = brief.get("task", "unknown")
            attempt = brief.get("attempt", 1)
            max_attempts = brief.get("max_attempts", 3)
            role = brief.get("role", "worker")
            return _deny(
                f"Root write guard: '{target_file}' is a write path of open dispatch {run_id} "
                f"(task '{task}', attempt {attempt} of {max_attempts}, worker {role}). "
                f"Root does not write product code around a delegation. Either re-brief the worker "
                f"with the correction, or close the dispatch first."
            )

    elif tool_name == "run_command":
        cmd_line = args.get("CommandLine", "")
        if isinstance(cmd_line, str) and cmd_line:
            hit = _check_command_line(cmd_line, root, owned_paths)
            if hit:
                if caller_role in WORKER_ROLES:
                    return _allow()
                run_id = dispatch.get("run_id", "unknown")
                return _deny(
                    f"Root write guard: command line modifies '{hit}', which is a write path of "
                    f"open dispatch {run_id}. Root does not write product code via shell around a delegation."
                )

    return _allow()


if __name__ == "__main__":
    sys.exit(main())
