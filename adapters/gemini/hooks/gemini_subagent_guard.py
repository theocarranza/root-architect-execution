#!/usr/bin/env python3
"""PreToolUse guard for Gemini / Antigravity: intercept subagent tools.

Hard-enforces the architectural boundaries of root-architect-execution:
1. Root must never hold or call define_subagent (denies define_subagent).
2. Root may only dispatch 'orchestrator' via invoke_subagent (denies any other TypeName).
"""

from __future__ import annotations

import json
import sys
from typing import Any


def check_tool_call(tool_call: dict[str, Any]) -> tuple[str, str | None]:
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
            # If no subagents specified or malformed, deny
            return (
                "deny",
                "invoke_subagent called with empty or invalid Subagents list.",
            )

        for subagent in subagents:
            if not isinstance(subagent, dict):
                return ("deny", "Invalid subagent entry in invoke_subagent.")
            type_name = subagent.get("TypeName")
            if type_name != "orchestrator":
                return (
                    "deny",
                    f"Root is strictly restricted to dispatching 'orchestrator' "
                    f"(roles/root-architect.json delegates_to: ['orchestrator']). "
                    f"Attempted to dispatch '{type_name}'. Root must not bypass "
                    f"the orchestrator layer or invoke workers directly.",
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
        # Fails closed on unparseable JSON when input was provided
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

    decision, reason = check_tool_call(tool_call)
    output: dict[str, Any] = {"decision": decision}
    if reason:
        output["reason"] = reason

    json.dump(output, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
