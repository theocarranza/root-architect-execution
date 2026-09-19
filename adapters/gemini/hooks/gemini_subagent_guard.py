#!/usr/bin/env python3
"""PreToolUse guard for Gemini / Antigravity: intercept subagent tools.

Hard-enforces the architectural boundaries of root-architect-execution:
1. Root, Orchestrator, and Workers must never call define_subagent.
2. Root is strictly restricted to dispatching 'orchestrator' via invoke_subagent.
3. Only the Orchestrator may dispatch worker subagents (impl-executor, spec-validator, quality-validator).
4. Workers are never permitted to dispatch subagents.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

WORKER_TYPES = frozenset(
    {"impl-executor", "spec-validator", "quality-validator", "worker", "implementer", "validator"}
)


def get_caller_role(payload: dict[str, Any]) -> str:
    """Extract the caller's role from the payload or environment.

    Defaults to 'root' when unspecified (fail closed).
    """
    caller = payload.get("agent_role") or payload.get("agent_type") or payload.get("caller")
    if caller and isinstance(caller, str):
        if ":" in caller:
            caller = caller.split(":")[-1]
        return caller.strip().lower()
    env_role = os.environ.get("AGENT_ROLE", "").strip().lower()
    return env_role if env_role else "root"


def check_tool_call(tool_call: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str | None]:
    name = tool_call.get("name", "")
    args = tool_call.get("args") or {}

    if name == "define_subagent":
        return (
            "deny",
            "Root is not permitted to call define_subagent. All subagents must be "
            "statically pre-registered with immutable configurations; Root cannot "
            "manufacture agent boundaries on the fly.",
        )

    if name == "invoke_subagent":
        subagents = args.get("Subagents") or []
        if not isinstance(subagents, list) or not subagents:
            return (
                "deny",
                "invoke_subagent called with empty or invalid Subagents list.",
            )

        caller_role = get_caller_role(payload)

        # Worker roles cannot dispatch subagents
        if caller_role in WORKER_TYPES:
            return (
                "deny",
                f"Worker ({caller_role}) is not permitted to call invoke_subagent. "
                "Workers cannot dispatch subagents.",
            )

        # Orchestrator can only spawn workers
        if caller_role == "orchestrator":
            for subagent in subagents:
                if not isinstance(subagent, dict):
                    return ("deny", "Invalid subagent entry in invoke_subagent.")
                type_name = subagent.get("TypeName")
                if type_name == "orchestrator":
                    return (
                        "deny",
                        "Orchestrator cannot dispatch another orchestrator (no recursive orchestration).",
                    )
                if type_name not in WORKER_TYPES:
                    return (
                        "deny",
                        f"Orchestrator may only dispatch workers ({sorted(WORKER_TYPES)}). "
                        f"Attempted to dispatch '{type_name}'.",
                    )
            return ("allow", None)

        # Root (and any unrecognized caller) can only spawn orchestrator
        for subagent in subagents:
            if not isinstance(subagent, dict):
                return ("deny", "Invalid subagent entry in invoke_subagent.")
            type_name = subagent.get("TypeName")
            if type_name != "orchestrator":
                return (
                    "deny",
                    f"Root is strictly restricted to dispatching 'orchestrator' "
                    f"(roles/root-architect.json delegates_to: ['orchestrator']). "
                    f"Only the orchestrator can spawn workers. Attempted to dispatch '{type_name}'. "
                    f"Root must not bypass the orchestrator layer or invoke workers directly.",
                )

        return ("allow", None)

    # Any other tool not managed by this guard is allowed
    return ("allow", None)


def main() -> int:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            json.dump({"decision": "allow"}, sys.stdout)
            return 0
        data = json.loads(raw_input)
    except Exception as exc:
        json.dump(
            {
                "decision": "deny",
                "reason": f"Subagent guard could not parse payload: {exc}",
            },
            sys.stdout,
        )
        return 0

    tool_call = data.get("toolCall")
    if not isinstance(tool_call, dict):
        json.dump({"decision": "allow"}, sys.stdout)
        return 0

    decision, reason = check_tool_call(tool_call, data)
    output: dict[str, Any] = {"decision": decision}
    if reason:
        output["reason"] = reason

    json.dump(output, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
