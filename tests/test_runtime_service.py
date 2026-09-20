"""The offline service must not pretend it can authenticate shared-user callers."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from runtime_service import RuntimeService


class RuntimeServiceTests(unittest.TestCase):
    def test_privileged_calls_are_unsupported_without_a_proven_identity_boundary(self):
        result = RuntimeService(Path(tempfile.mkdtemp()) / "state").capture({"role": "controller"})
        self.assertEqual("unsupported_boundary", result["status"])
        self.assertEqual("authenticated_controller_identity", result["capability"])
        self.assertNotIn("worker_can_modify_authoritative_state", result)

    def test_role_session_and_environment_are_not_authentication(self):
        service = RuntimeService(Path(tempfile.mkdtemp()) / "state")
        for supplied in (
            {"role": "controller"},
            {"persisted_by": "orchestrator"},
            {"controller_session_id": "forged"},
            {"caller": "root"},
        ):
            with self.subTest(supplied=supplied):
                self.assertEqual("unsupported_boundary", service.privileged(supplied)["status"])

    def test_cli_has_only_narrow_offline_operations(self):
        root = Path(__file__).resolve().parents[1]
        command = [sys.executable, str(root / "scripts" / "runtime.py"), "--help"]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        self.assertIn("init", result.stdout)
        self.assertIn("export", result.stdout)
        self.assertNotIn("dispatch", result.stdout)
        self.assertNotIn("capture", result.stdout)
