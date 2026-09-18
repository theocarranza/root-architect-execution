#!/usr/bin/env python3
"""Unit tests for Claude Code session bootstrap hook (SessionStart)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPT_PATH = REPO_ROOT / "adapters" / "claude-code" / "hooks" / "claude_session_bootstrap.py"


class TestClaudeSessionBootstrapHook(unittest.TestCase):
    def run_hook(self, payload: dict | str) -> tuple[int, str]:
        input_data = json.dumps(payload) if isinstance(payload, dict) else payload
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"Hook failed with stderr: {proc.stderr}")
        return proc.returncode, proc.stdout

    def test_session_start_with_root_architect_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / ".root-architect"
            root_dir.mkdir()

            payload = {
                "hook_event_name": "SessionStart",
                "session_id": "test-session-1",
                "cwd": tmpdir,
                "transcript_path": "",
            }
            code, output = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertIn("Root Architect Mode", output)
            self.assertIn("root_preflight.py", output)
            self.assertIn("SKILL.md", output)

    def test_session_start_with_handoff_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handoff = Path(tmpdir) / "HANDOFF.md"
            handoff.write_text(
                "# Handoff\nGoverned by root-architect-execution.\n", encoding="utf-8"
            )

            payload = {
                "hook_event_name": "SessionStart",
                "session_id": "test-session-2",
                "cwd": tmpdir,
            }
            code, output = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertIn("Root Architect Mode", output)

    def test_session_start_with_transcript_keyword(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript = Path(tmpdir) / "transcript.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "step_index": 1,
                        "type": "USER_INPUT",
                        "content": "Please start /root-architect-execution for this task",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            payload = {
                "hook_event_name": "SessionStart",
                "session_id": "test-session-3",
                "cwd": tmpdir,
                "transcript_path": str(transcript),
            }
            code, output = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertIn("root_preflight.py", output)

    def test_session_start_unrelated_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "hook_event_name": "SessionStart",
                "session_id": "test-session-4",
                "cwd": tmpdir,
            }
            code, output = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertEqual(output.strip(), "")

    def test_malformed_input_fails_safe(self):
        code, output = self.run_hook("NOT JSON AT ALL")
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "")

    def test_empty_input_fails_safe(self):
        code, output = self.run_hook("")
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "")

    def test_missing_cwd_with_no_markers(self):
        """No cwd, no transcript_path — should produce no output."""
        payload = {
            "hook_event_name": "SessionStart",
            "session_id": "test-session-5",
        }
        code, output = self.run_hook(payload)
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "")


if __name__ == "__main__":
    unittest.main()
