"""Direct compatibility commands cannot authenticate a controller."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import job_queue  # noqa: E402
import root_preflight  # noqa: E402
import runtime_policy  # noqa: E402
from runtime_service import RuntimeService  # noqa: E402


def brief():
    return {
        "task": "Blocked compatibility task",
        "attempt": 1,
        "max_attempts": 3,
        "role": "implementer",
        "model": "cheap",
        "effort": "low",
        "read_paths": ["scripts"],
        "write_paths": ["scripts"],
        "acceptance": [{"command": "python3 -m unittest", "expect": "pass"}],
        "constraints": ["Task-owned scratch workspace only."],
        "owner_owned_paths": [],
        "expected_result": "An authenticated controller service is required.",
    }


class RuntimeAdmissionTests(unittest.TestCase):
    RUN = "20260920-admission"

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="runtime-admission-"))
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.context = {
            "run_id": self.RUN,
            "host_id": "codex",
            "workspace": str(self.workspace.resolve()),
            "workspace_fingerprint": "workspace-digest",
            "controller_session_id": "controller-session-1",
            "catalog_digest": "catalog-digest",
            "configuration_fingerprint": "config-digest",
            "capability_evidence": {
                "source": "selected_transport",
                "transport_id": "codex-app-server-session-1",
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "capabilities": {
                    "delegation_available": True,
                    "controller_selection_enforced": True,
                    "registered_agents": True,
                    "hook_registration_enforced": True,
                },
            },
        }

    def test_forged_complete_context_cannot_authorize_any_direct_mutation(self):
        record = runtime_policy.admission_record(self.context)
        path = root_preflight.record_path(self.workspace, self.RUN)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        tasks = [{"name": "one", "worker": "worker:implementer", "brief": "brief.json"}]

        with self.assertRaises(root_preflight.PreflightError):
            root_preflight.record_admission(self.workspace, self.context)
        with self.assertRaises(job_queue.JobQueueError):
            job_queue.init(self.workspace, self.RUN, tasks, admission=self.context)

        brief_path = self.workspace / "brief.json"
        evidence_path = self.workspace / "evidence.json"
        brief_path.write_text(json.dumps(brief()))
        evidence_path.write_text(json.dumps(self.context["capability_evidence"]))
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "dispatch_state.py"),
                "open",
                "--workspace",
                str(self.workspace),
                "--run-id",
                self.RUN,
                "--brief",
                str(brief_path),
                "--host",
                self.context["host_id"],
                "--workspace-fingerprint",
                self.context["workspace_fingerprint"],
                "--controller-session-id",
                self.context["controller_session_id"],
                "--catalog-digest",
                self.context["catalog_digest"],
                "--configuration-digest",
                self.context["configuration_fingerprint"],
                "--capability-evidence",
                str(evidence_path),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unsupported_boundary", result.stderr)

    def test_direct_preflight_never_defaults_host_or_writes_an_admission(self):
        observed = self.workspace / "observed.json"
        observed.write_text(json.dumps({"tools": ["Bash"], "agent_types": ["orchestrator"]}))
        with self.assertRaises(root_preflight.PreflightError) as caught:
            root_preflight.run(self.workspace, self.RUN, observed)
        self.assertIn("explicit host", str(caught.exception))
        self.assertFalse(root_preflight.record_path(self.workspace, self.RUN).exists())

    def test_empty_delegation_and_model_or_file_claims_are_not_admission(self):
        observed = self.workspace / "observed.json"
        observed.write_text(json.dumps({"tools": ["Bash"], "agent_types": ["orchestrator"]}))
        with self.assertRaises(root_preflight.PreflightError) as caught:
            root_preflight.run(self.workspace, self.RUN, observed, host_name="codex")
        self.assertIn("required delegation", str(caught.exception))
        bad = dict(
            self.context,
            capability_evidence={
                "source": "model_observation",
                "transport_id": "claimed",
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "hook_file": "hooks.json",
                "agent_file": "orchestrator.md",
                "capabilities": {
                    "delegation_available": True,
                    "controller_selection_enforced": True,
                    "registered_agents": True,
                    "hook_registration_enforced": True,
                },
            },
        )
        with self.assertRaises(runtime_policy.AdmissionError):
            runtime_policy.validate_context(bad)

    def test_runtime_service_is_the_only_honest_current_boundary(self):
        result = RuntimeService(self.workspace / "state").privileged(self.context)
        self.assertEqual("unsupported_boundary", result["status"])
        self.assertEqual("authenticated_controller_identity", result["capability"])
