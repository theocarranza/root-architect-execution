#!/usr/bin/env python3
"""Unit tests for Gemini session bootstrap hook (PreInvocation)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPT_PATH = REPO_ROOT / "adapters" / "gemini" / "hooks" / "gemini_session_bootstrap.py"


class TestGeminiSessionBootstrapHook(unittest.TestCase):
    def run_hook(self, payload: dict | str) -> tuple[int, dict]:
        input_data = json.dumps(payload) if isinstance(payload, dict) else payload
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"Hook failed with stderr: {proc.stderr}")
        result = json.loads(proc.stdout)
        return proc.returncode, result

    def test_turn_one_with_root_architect_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / ".root-architect"
            root_dir.mkdir()

            payload = {
                "invocationNum": 1,
                "workspacePaths": [tmpdir],
                "conversationId": "test-conv-1",
            }
            code, result = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertIn("injectSteps", result)
            self.assertEqual(len(result["injectSteps"]), 1)
            msg = result["injectSteps"][0]["ephemeralMessage"]
            self.assertIn("Root Architect Mode", msg)
            self.assertIn("root_preflight.py", msg)
            self.assertIn("SKILL.md", msg)

    def test_turn_one_with_handoff_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handoff = Path(tmpdir) / "HANDOFF.md"
            handoff.write_text(
                "# Handoff\nGoverned by root-architect-execution.\n", encoding="utf-8"
            )

            payload = {
                "invocationNum": 1,
                "workspacePaths": [tmpdir],
                "conversationId": "test-conv-2",
            }
            code, result = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertEqual(len(result["injectSteps"]), 1)
            self.assertIn("Root Architect Mode", result["injectSteps"][0]["ephemeralMessage"])

    def test_turn_one_with_transcript_keyword(self):
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
                "invocationNum": 1,
                "workspacePaths": [tmpdir],
                "transcriptPath": str(transcript),
                "conversationId": "test-conv-3",
            }
            code, result = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertEqual(len(result["injectSteps"]), 1)
            self.assertIn("root_preflight.py", result["injectSteps"][0]["ephemeralMessage"])

    def test_turn_one_unconditional_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "invocationNum": 1,
                "workspacePaths": [tmpdir],
                "conversationId": "test-conv-4",
            }
            code, result = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertEqual(len(result["injectSteps"]), 1)
            self.assertIn("Root Architect Mode", result["injectSteps"][0]["ephemeralMessage"])

    def test_turn_greater_than_one_zero_overhead(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / ".root-architect"
            root_dir.mkdir()

            payload = {
                "invocationNum": 2,
                "workspacePaths": [tmpdir],
                "conversationId": "test-conv-5",
            }
            code, result = self.run_hook(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result, {"injectSteps": []})

    def test_malformed_input_fails_safe(self):
        code, result = self.run_hook("NOT JSON AT ALL")
        self.assertEqual(code, 0)
        self.assertEqual(result, {"injectSteps": []})

    def test_empty_input_fails_safe(self):
        code, result = self.run_hook("")
        self.assertEqual(code, 0)
        self.assertEqual(result, {"injectSteps": []})


if __name__ == "__main__":
    unittest.main()
