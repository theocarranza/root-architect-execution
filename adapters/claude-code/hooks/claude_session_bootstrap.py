#!/usr/bin/env python3
"""Lifecycle bootstrap hook for Claude Code (SessionStart).

Fires when a session begins or resumes. Detects whether the session is
governed by or targeting Root Architect Execution, and automatically
injects the operational protocol and mandatory startup preflight directives
into working context via stdout text injection.

Claude Code SessionStart contract:
  stdin  -> {"hook_event_name": "SessionStart", "session_id": "...",
             "cwd": "...", "transcript_path": "..."}
  stdout -> plain text injected into session context
  exit 0 -> success
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_KEYWORDS = {
    "root-architect",
    "root architect",
    "root_architect",
    "orchestrator",
    "impl-executor",
    "spec-validator",
    "quality-validator",
    "/root-architect-execution",
    "root-architect-execution",
    "implementation_plan.md",
    "handoff.md",
}

BOOTSTRAP_PROMPT = """### [Root Architect Execution Protocol Bootstrapped]
You are operating in **Root Architect Mode** governed by `root-architect-execution`.

**Mandatory Operational Directives:**
1. **Startup Preflight Gate**: Before planning, reading codebase files, or answering the operator, observe your toolset and dispatchable types, and run:
   ```sh
   python3 scripts/root_preflight.py --run-id <run-id> --observed .root-architect/preflight/<run-id>.observed.json
   ```
2. **Authority & Isolation**: Root owns the implementation plan, Git history, session ledger, and acceptance gates. Product-code implementation and test validation MUST be delegated to the orchestrator. Root must NEVER write product code directly.
3. **Queue Enforcement**: All tasks must be tracked through `scripts/job_queue.py`, which mechanically fails closed if startup preflight has not passed.
4. **Governing Reference**: Consult `SKILL.md` and `references/contracts.md` for role specifications, envelope schemas, and outcome criteria."""


def is_root_session(data: dict[str, Any]) -> bool:
    """Determine whether the active session relates to Root Architect."""
    # 1. Check workspace directory for .root-architect state or root markers
    cwd = data.get("cwd", "")
    if cwd:
        ws_path = Path(cwd)
        if (ws_path / ".root-architect").is_dir():
            return True
        if (ws_path / "HANDOFF.md").is_file():
            try:
                content = (ws_path / "HANDOFF.md").read_text(encoding="utf-8", errors="ignore")
                if "root-architect" in content.lower():
                    return True
            except OSError:
                pass

    # 2. Check initial transcript prompt if available
    transcript_path = data.get("transcript_path")
    if transcript_path and Path(transcript_path).is_file():
        try:
            with open(transcript_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    step = json.loads(line)
                    if step.get("type") == "USER_INPUT":
                        content = str(step.get("content", "")).lower()
                        if any(kw in content for kw in ROOT_KEYWORDS):
                            return True
                        break  # Only inspect the initial user turn
        except (OSError, json.JSONDecodeError):
            pass

    return False


def main() -> int:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            return 0
        data = json.loads(raw_input)
    except Exception:
        return 0

    if is_root_session(data):
        sys.stdout.write(BOOTSTRAP_PROMPT)
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
