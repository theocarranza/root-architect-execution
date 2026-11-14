"""Regression tests for the explicitly legacy mailbox reader.

These cases intentionally exercise files as hostile input.  They do not make
the file mailbox a governed authority: governed capture remains unavailable
until an authenticated controller service exists.
"""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mailbox  # noqa: E402


class RuntimeEnvelopeTests(unittest.TestCase):
    RUN = "20260920-return-capture"

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="runtime-envelopes-"))
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

    def legacy_post(self, kind, sender, recipient, body, **fields):
        return mailbox.legacy_post(
            self.workspace,
            self.RUN,
            kind,
            sender,
            recipient,
            "orchestrator",
            body,
            **fields,
        )

    def test_governed_post_cannot_treat_a_claimed_persister_as_controller_evidence(self):
        with self.assertRaises(mailbox.MailboxError) as raised:
            mailbox.post(
                self.workspace,
                self.RUN,
                "report",
                "worker:implementer",
                "orchestrator",
                "orchestrator",
                b"claimed capture",
            )
        self.assertIn("unsupported", str(raised.exception))

    def test_legacy_verifier_rejects_fake_and_body_only_corruption(self):
        path = self.legacy_post(
            "task", "orchestrator", "worker:implementer", b"task", envelope_id="task-env"
        )
        path.write_bytes(path.read_bytes() + b"mutated")
        fake = mailbox.mailbox_dir(self.workspace, self.RUN) / "fake.md"
        fake.write_bytes(b"not an envelope")
        problems = mailbox.legacy_verify(self.workspace, self.RUN)
        self.assertTrue(any("body does not match" in item for item in problems), problems)
        self.assertTrue(any("does not begin" in item for item in problems), problems)

    def test_legacy_verifier_rejects_body_and_stored_hash_replacement(self):
        path = self.legacy_post(
            "task", "orchestrator", "worker:implementer", b"original", envelope_id="task-env"
        )
        header, _body = mailbox.parse_envelope(path.read_bytes())
        header["body_sha256"] = hashlib.sha256(b"replacement").hexdigest()
        path.write_bytes(mailbox.render_header(header).encode("utf-8") + b"replacement")
        problems = mailbox.legacy_verify(self.workspace, self.RUN)
        self.assertTrue(any("legacy" in item and "governed" in item for item in problems), problems)

    def test_legacy_verifier_rejects_mismatched_recipient_and_reused_role_report(self):
        self.legacy_post(
            "task",
            "orchestrator",
            "worker:implementer",
            b"one",
            envelope_id="task-one",
            task_id="one",
            attempt_id="one-attempt",
            selected_template="impl-executor-cheap",
        )
        self.legacy_post(
            "task",
            "orchestrator",
            "worker:implementer",
            b"two",
            envelope_id="task-two",
            task_id="two",
            attempt_id="two-attempt",
            selected_template="impl-executor-cheap",
        )
        self.legacy_post(
            "report",
            "worker:implementer",
            "root",
            b"one result",
            envelope_id="report-one",
            task_id="one",
            attempt_id="one-attempt",
            reply_to="task-one",
            selected_template="impl-executor-cheap",
        )
        self.legacy_post(
            "report",
            "worker:implementer",
            "orchestrator",
            b"reused result",
            envelope_id="report-two",
            task_id="two",
            attempt_id="two-attempt",
            reply_to="task-one",
            selected_template="impl-executor-cheap",
        )
        problems = mailbox.legacy_verify(self.workspace, self.RUN)
        self.assertTrue(any("invalid legacy route" in item for item in problems), problems)
        self.assertTrue(any("reply_to" in item for item in problems), problems)

    def test_legacy_verifier_rejects_wrong_kind_and_wrong_run_with_matching_hash(self):
        self.legacy_post(
            "task",
            "orchestrator",
            "worker:implementer",
            b"task",
            envelope_id="task-env",
            task_id="one",
            attempt_id="one-attempt",
            selected_template="impl-executor-cheap",
        )
        wrong_kind = self.legacy_post(
            "answer",
            "orchestrator",
            "worker:implementer",
            b"answer",
            envelope_id="answer-env",
            task_id="one",
            attempt_id="one-attempt",
            reply_to="task-env",
            selected_template="impl-executor-cheap",
        )
        header, body = mailbox.parse_envelope(wrong_kind.read_bytes())
        header["run_id"] = "another-run"
        wrong_kind.write_bytes(mailbox.render_header(header).encode("utf-8") + body)
        problems = mailbox.legacy_verify(self.workspace, self.RUN)
        self.assertTrue(any("wrong result kind" in item for item in problems), problems)
        self.assertTrue(any("claims run another-run" in item for item in problems), problems)

    def test_legacy_verifier_distinguishes_empty_worker_output_from_controller_missing_result(self):
        self.legacy_post(
            "task",
            "orchestrator",
            "worker:implementer",
            b"task",
            envelope_id="task-env",
            task_id="one",
            attempt_id="one-attempt",
            selected_template="impl-executor-cheap",
        )
        self.legacy_post(
            "report",
            "worker:implementer",
            "orchestrator",
            b"",
            envelope_id="empty-report",
            task_id="one",
            attempt_id="one-attempt",
            reply_to="task-env",
            selected_template="impl-executor-cheap",
        )
        problems = mailbox.legacy_verify(self.workspace, self.RUN)
        self.assertTrue(any("reported empty output" in item for item in problems), problems)
        self.assertFalse(any("missing result" in item for item in problems), problems)


if __name__ == "__main__":
    unittest.main()
