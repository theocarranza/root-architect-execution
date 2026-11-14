"""Regression cases for the runtime-admission gaps recorded in ADR 0004.

These tests intentionally fail against the version-1 file records. They state
the required boundary for the versioned runtime work that follows.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import job_queue  # noqa: E402
import mailbox  # noqa: E402
import root_preflight  # noqa: E402


def valid_brief():
    return {
        "task": "Reject an unadmitted dispatch",
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
        "expected_result": "The dispatch is admitted before it opens.",
    }


class RuntimeRegressionTests(unittest.TestCase):
    RUN = "20260920-runtime-regressions"

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="runtime-regressions-"))
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

    def seed_legacy_queue(self, tasks):
        """Create old queue bytes only to preserve later mailbox regressions."""
        path = job_queue.queue_path(self.workspace, self.RUN)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": self.RUN,
                    "created_at": "2026-09-20T00:00:00Z",
                    "tasks": tasks,
                }
            ),
            encoding="utf-8",
        )

    def test_empty_codex_tools_cannot_pass_preflight(self):
        observed = self.workspace / "observed.json"
        observed.write_text(json.dumps({"tools": [], "agent_types": ["orchestrator"]}))
        with self.assertRaises(root_preflight.PreflightError):
            root_preflight.run(self.workspace, self.RUN, observed, host_name="codex")

    def test_forged_preflight_identity_and_type_cannot_admit_a_run(self):
        path = root_preflight.record_path(self.workspace, self.RUN)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"passed": "false", "run_id": "another-run", "host": "another-host"})
        )
        admitted, reason = root_preflight.passed(self.workspace, self.RUN)
        self.assertFalse(admitted, reason)

    def test_dispatch_cannot_open_without_admission(self):
        brief = self.workspace / "brief.json"
        brief.write_text(json.dumps(valid_brief()), encoding="utf-8")
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
                str(brief),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_second_active_queue_task_is_refused_at_transition(self):
        with self.assertRaises(job_queue.JobQueueError):
            job_queue.mark(self.workspace, self.RUN, "second", "dispatched")

    def test_fake_envelope_cannot_complete_a_queue_task(self):
        self.seed_legacy_queue(
            [
                {
                    "name": "first",
                    "worker": "worker:implementer",
                    "brief": "brief.json",
                    "state": "returned",
                    "envelope": "fake.md",
                }
            ]
        )
        directory = mailbox.mailbox_dir(self.workspace, self.RUN)
        directory.mkdir(parents=True)
        (directory / "fake.md").write_text("not an envelope", encoding="utf-8")
        self.assertTrue(mailbox.legacy_verify(self.workspace, self.RUN))

    def test_report_for_one_task_cannot_complete_another_task(self):
        mailbox.legacy_post(
            self.workspace,
            self.RUN,
            "task",
            "orchestrator",
            "worker:implementer",
            "orchestrator",
            b"first task",
            envelope_id="task-first",
            task_id="first",
            attempt_id="first-attempt",
            selected_template="impl-executor-cheap",
        )
        report = mailbox.legacy_post(
            self.workspace,
            self.RUN,
            "report",
            "worker:implementer",
            "orchestrator",
            "orchestrator",
            b"first result",
            envelope_id="report-first",
            task_id="first",
            attempt_id="first-attempt",
            reply_to="task-first",
            selected_template="impl-executor-cheap",
        )
        mailbox.legacy_post(
            self.workspace,
            self.RUN,
            "task",
            "orchestrator",
            "worker:implementer",
            "orchestrator",
            b"second task",
            envelope_id="task-second",
            task_id="second",
            attempt_id="second-attempt",
            selected_template="impl-executor-cheap",
        )
        self.seed_legacy_queue(
            [
                {
                    "name": task,
                    "worker": "worker:implementer",
                    "brief": "brief.json",
                    "state": "returned",
                    "envelope": report.name,
                }
                for task in ("first", "second")
            ]
        )
        self.assertTrue(mailbox.legacy_verify(self.workspace, self.RUN))

    def test_worker_cannot_route_a_report_directly_to_root(self):
        with self.assertRaises(mailbox.MailboxError):
            mailbox.post(
                self.workspace,
                self.RUN,
                "report",
                "worker:implementer",
                "root",
                "orchestrator",
                b"bypass orchestrator",
            )


if __name__ == "__main__":
    unittest.main()
