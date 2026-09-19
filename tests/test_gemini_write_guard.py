#!/usr/bin/env python3
"""Unit tests for Gemini PreToolUse root write guard."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPT_PATH = REPO_ROOT / "adapters" / "gemini" / "hooks" / "root_write_guard.py"
DISPATCH_STATE = REPO_ROOT / "scripts" / "dispatch_state.py"


def valid_brief(**overrides):
    brief = {
        "task": "Task 1",
        "attempt": 1,
        "max_attempts": 3,
        "role": "implementer",
        "model": "haiku",
        "effort": "low",
        "read_paths": ["src/feature.py"],
        "write_paths": ["src/feature.py"],
        "acceptance": [{"command": "python3 -m unittest", "expect": "pass"}],
        "constraints": ["Reachability: only feature.py changes."],
        "owner_owned_paths": ["AI_Codex/"],
        "expected_result": "Feature implemented.",
    }
    brief.update(overrides)
    return brief


class TestGeminiWriteGuard(unittest.TestCase):
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

    def open_dispatch(
        self, workspace: Path, brief: dict | None = None, run_id: str = "20260918-task-1"
    ):
        brief_path = workspace / "brief.json"
        brief_path.write_text(json.dumps(brief or valid_brief()), encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(DISPATCH_STATE),
                "open",
                "--workspace",
                str(workspace),
                "--brief",
                str(brief_path),
                "--run-id",
                run_id,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"dispatch_state open failed: {proc.stderr}")

    def test_no_dispatch_open_allows_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "workspacePaths": [tmpdir],
                "toolCall": {
                    "name": "write_to_file",
                    "args": {"TargetFile": "src/module.py", "CodeContent": "x = 1"},
                },
            }
            code, result = self.run_guard(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result.get("decision"), "allow")

    def test_dispatch_open_allows_unrelated_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.open_dispatch(ws)

            payload = {
                "workspacePaths": [tmpdir],
                "toolCall": {
                    "name": "write_to_file",
                    "args": {"TargetFile": "docs/notes.md", "CodeContent": "# Notes"},
                },
            }
            code, result = self.run_guard(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result.get("decision"), "allow")

    def test_dispatch_open_denies_owned_paths_write_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.open_dispatch(ws)

            payload = {
                "workspacePaths": [tmpdir],
                "toolCall": {
                    "name": "write_to_file",
                    "args": {"TargetFile": "src/feature.py", "CodeContent": "x = 2"},
                },
            }
            code, result = self.run_guard(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result.get("decision"), "deny")
            self.assertIn("Root write guard", result.get("reason", ""))
            self.assertIn("src/feature.py", result.get("reason", ""))

    def test_dispatch_open_denies_owned_paths_replace_file_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.open_dispatch(ws)

            payload = {
                "workspacePaths": [tmpdir],
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": "src/feature.py",
                        "TargetContent": "a",
                        "ReplacementContent": "b",
                    },
                },
            }
            code, result = self.run_guard(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result.get("decision"), "deny")
            self.assertIn("Root write guard", result.get("reason", ""))

    def test_dispatch_open_denies_mutating_shell_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.open_dispatch(ws)

            payload = {
                "workspacePaths": [tmpdir],
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": "echo 'print(1)' > src/feature.py"},
                },
            }
            code, result = self.run_guard(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result.get("decision"), "deny")
            self.assertIn("Root write guard", result.get("reason", ""))

    def test_corrupt_dispatch_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".root-architect" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "dispatch-corrupt.json").write_text("{ unparseable json")

            payload = {
                "workspacePaths": [tmpdir],
                "toolCall": {
                    "name": "write_to_file",
                    "args": {"TargetFile": "src/feature.py", "CodeContent": "1"},
                },
            }
            code, result = self.run_guard(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result.get("decision"), "deny")

    def test_root_cannot_write_to_protected_product_dirs_even_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for protected_path in ("lib/feature.dart", "functions/main.py"):
                with self.subTest(path=protected_path):
                    payload = {
                        "workspacePaths": [tmpdir],
                        "toolCall": {
                            "name": "write_to_file",
                            "args": {
                                "TargetFile": protected_path,
                                "CodeContent": "// product code",
                            },
                        },
                    }
                    code, result = self.run_guard(payload)
                    self.assertEqual(code, 0)
                    self.assertEqual(result.get("decision"), "deny")
                    self.assertIn("protected product directory", result.get("reason", ""))

    def test_worker_can_write_to_protected_product_dirs_when_in_write_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            brief = valid_brief(write_paths=["lib/feature.dart"])
            self.open_dispatch(ws, brief=brief)

            payload = {
                "workspacePaths": [tmpdir],
                "agent_role": "worker",
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": "lib/feature.dart",
                        "CodeContent": "// worker implementation",
                    },
                },
            }
            code, result = self.run_guard(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result.get("decision"), "allow")

    def test_root_cannot_mutate_dispatch_state_via_run_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for cmd in (
                "python3 scripts/dispatch_state.py close --run-id 20260918-task-1 --outcome accepted",
                "python3 -c 'import json; ...' .root-architect/state/dispatch-1.json",
                "echo 'closed' > .root-architect/state/dispatch-1.json",
            ):
                with self.subTest(cmd=cmd):
                    payload = {
                        "workspacePaths": [tmpdir],
                        "toolCall": {
                            "name": "run_command",
                            "args": {"CommandLine": cmd},
                        },
                    }
                    code, result = self.run_guard(payload)
                    self.assertEqual(code, 0)
                    self.assertEqual(result.get("decision"), "deny")
                    self.assertIn("mutate a dispatch state file", result.get("reason", ""))

    def test_root_cannot_edit_dispatch_state_file_directly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "workspacePaths": [tmpdir],
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": ".root-architect/state/dispatch-20260918-task-1.json",
                        "CodeContent": "{}",
                    },
                },
            }
            code, result = self.run_guard(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result.get("decision"), "deny")
            self.assertIn(
                "dispatch state files under .root-architect/state/", result.get("reason", "")
            )


if __name__ == "__main__":
    unittest.main()
