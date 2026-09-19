#!/usr/bin/env python3
"""Unit tests for Gemini PreToolUse subagent guard."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPT_PATH = REPO_ROOT / "adapters" / "gemini" / "hooks" / "gemini_subagent_guard.py"


class TestGeminiSubagentGuard(unittest.TestCase):
    def run_guard(self, payload: dict | str) -> tuple[int, dict]:
        input_data = json.dumps(payload) if isinstance(payload, dict) else payload
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"Guard failed with stderr: {proc.stderr}")
        result = json.loads(proc.stdout)
        return proc.returncode, result

    def test_define_subagent_is_denied(self):
        payload = {
            "toolCall": {
                "name": "define_subagent",
                "args": {
                    "name": "custom_worker",
                    "system_prompt": "Do work directly",
                },
            }
        }
        code, result = self.run_guard(payload)
        self.assertEqual(code, 0)
        self.assertEqual(result.get("decision"), "deny")
        self.assertIn("Root is not permitted to call define_subagent", result.get("reason", ""))

    def test_invoke_subagent_orchestrator_is_allowed(self):
        payload = {
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {
                            "TypeName": "orchestrator",
                            "Prompt": "Please orchestrate task 1",
                            "Role": "Orchestrator",
                        }
                    ]
                },
            }
        }
        code, result = self.run_guard(payload)
        self.assertEqual(code, 0)
        self.assertEqual(result.get("decision"), "allow")

    def test_invoke_subagent_worker_is_denied(self):
        for worker_type in ("impl-executor", "spec-validator", "quality-validator", "rogue-worker"):
            with self.subTest(worker_type=worker_type):
                payload = {
                    "toolCall": {
                        "name": "invoke_subagent",
                        "args": {
                            "Subagents": [
                                {
                                    "TypeName": worker_type,
                                    "Prompt": "Implement this directly",
                                    "Role": "Worker",
                                }
                            ]
                        },
                    }
                }
                code, result = self.run_guard(payload)
                self.assertEqual(code, 0)
                self.assertEqual(result.get("decision"), "deny")
                self.assertIn("Root is strictly restricted to dispatching 'orchestrator'", result.get("reason", ""))

    def test_invoke_subagent_mixed_types_is_denied(self):
        payload = {
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {"TypeName": "orchestrator", "Prompt": "OK"},
                        {"TypeName": "impl-executor", "Prompt": "NOT OK"},
                    ]
                },
            }
        }
        code, result = self.run_guard(payload)
        self.assertEqual(code, 0)
        self.assertEqual(result.get("decision"), "deny")

    def test_other_tools_pass_through(self):
        payload = {
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": "/path/to/file"},
            }
        }
        code, result = self.run_guard(payload)
        self.assertEqual(code, 0)
        self.assertEqual(result.get("decision"), "allow")

    def test_empty_input(self):
        code, result = self.run_guard("")
        self.assertEqual(code, 0)
        self.assertEqual(result.get("decision"), "allow")


if __name__ == "__main__":
    unittest.main()
