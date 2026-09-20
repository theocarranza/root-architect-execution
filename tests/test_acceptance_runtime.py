"""The Codex feasibility runner must fail closed before any live launch."""

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "acceptance_runtime.py"
FIXTURE = ROOT / "tests" / "fixtures" / "runtime" / "codex-probe.json"


class AcceptanceRuntimeTests(unittest.TestCase):
    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, str(RUNNER), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_live_probe_refuses_unenforceable_limits_without_launching(self):
        result = self.invoke(
            "--host", "codex", "--scenario", "capability-probe", "--require-live",
            "--max-seconds", "300", "--max-tokens", "12000",
        )
        self.assertEqual(2, result.returncode, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual("blocked", record["status"])
        self.assertEqual("not_run", record["live_trial"])
        self.assertFalse(record["model_invoked"])
        self.assertEqual("max_tokens", record["blocker"]["capability"])
        self.assertEqual("unknown", record["limits"]["token_enforcement"])
        self.assertEqual(
            {"max_seconds", "max_tokens"},
            {blocker["capability"] for blocker in record["blockers"]},
        )

    def test_invalid_or_missing_required_controls_are_rejected(self):
        invalid_host = self.invoke(
            "--host", "claude-code", "--scenario", "capability-probe", "--require-live",
            "--max-seconds", "300", "--max-tokens", "12000",
        )
        missing_limit = self.invoke(
            "--host", "codex", "--scenario", "capability-probe", "--require-live",
            "--max-seconds", "300",
        )
        self.assertEqual(2, invalid_host.returncode)
        self.assertEqual(2, missing_limit.returncode)

    def test_offline_probe_records_not_run_status_and_safe_facts_only(self):
        result = self.invoke(
            "--host", "codex", "--scenario", "capability-probe",
            "--max-seconds", "300", "--max-tokens", "12000",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual("blocked", record["status"])
        self.assertEqual("not_run", record["live_trial"])
        self.assertFalse(record["model_invoked"])
        self.assertEqual("unknown", record["identities"]["root"])
        self.assertEqual("not_run", record["events"])
        self.assertIn("configuration", record["local_evidence"])

    def test_fixture_does_not_fabricate_live_events_or_identities(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual("blocked", fixture["status"])
        self.assertEqual("not_run", fixture["live_trial"])
        self.assertFalse(fixture["model_invoked"])
        self.assertEqual("unknown", fixture["identities"]["worker"])
        self.assertEqual("not_run", fixture["events"])
        self.assertEqual([], fixture["observed_events"])
