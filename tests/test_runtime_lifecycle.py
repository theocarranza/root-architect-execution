"""Lifecycle invariants spanning workspace reservations and runtime evidence."""

import hashlib
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime_store import RuntimeStore, StorageError  # noqa: E402
import runtime_contract  # noqa: E402
import render_agents  # noqa: E402


def selected_identity(template_id="impl-executor-cheap"):
    catalog = render_agents.select_catalog("codex")
    selected = render_agents.select_template(catalog, template_id)
    return {
        "family": selected["family"],
        "selected_template": selected["template_id"],
        "template_catalog_sha256": catalog["catalog_sha256"],
        "requested_model_tier": selected["requested"]["model_tier"],
        "requested_effort": selected["requested"]["effort"],
        "resolved_model": selected["resolved"]["model"],
        "resolved_effort": selected["resolved"]["effort"],
        "effective_model": None,
        "effective_effort": None,
    }


def reserve_in_process(root, run_id, attempt_id, result):
    store = RuntimeStore(Path(root))
    try:
        record = attempt(run_id, "task-" + attempt_id, attempt_id)
        store.reserve_attempt(
            record,
            "workspace",
            "launch-" + attempt_id,
            "parent-" + attempt_id,
            *dispatch(record, "dispatch-" + attempt_id),
        )
        result.put("reserved")
    except StorageError:
        result.put("rejected")


def run_record(run_id):
    return {
        "schema_version": 2,
        "run_id": run_id,
        "host_id": "codex",
        "workspace_fingerprint": "workspace",
        "configuration_fingerprint": "config",
        "principal_id": "controller:local-1",
        "created_at": "2026-09-20T00:00:00Z",
        "state": "created",
    }


def create_run(store, record):
    return store.create_run(record, render_agents.select_catalog("codex"))


def attempt(run_id, task_id, attempt_id, state="reserved"):
    return {
        "schema_version": 2,
        "run_id": run_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "provider_thread_id": None,
        "provider_turn_id": None,
        "provider_event_id": None,
        **selected_identity(),
        "started_at": "2026-09-20T00:00:00Z",
        "last_activity_at": "2026-09-20T00:00:00Z",
        "deadline_at": "2026-09-20T01:00:00Z",
        "last_envelope_id": None,
        "observed_activity_state": "unknown",
        "provider_observed_at": None,
        "local_bookkeeping_at": "2026-09-20T00:00:00Z",
        "controller_lease_expires_at": "2026-09-20T01:00:00Z",
        "state": state,
    }


def dispatch(record, envelope_id):
    body = ("dispatch:" + record["attempt_id"]).encode()
    return (
        {
            "schema_version": 2,
            "envelope_id": envelope_id,
            "run_id": record["run_id"],
            "task_id": record["task_id"],
            "attempt_id": record["attempt_id"],
            "kind": "task",
            "from": "orchestrator",
            "to": "worker:" + record["selected_template"],
            "captured_by": "controller:local-1",
            "capture_source": "controller",
            "reply_to": None,
            **{field: record[field] for field in selected_identity()},
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "created_at": "2026-09-20T00:00:00Z",
            "provider_thread_id": None,
            "provider_turn_id": None,
            "provider_event_id": None,
        },
        body,
    )


class RuntimeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RuntimeStore(Path(self.temp.name) / ".root-architect" / "state")

    def tearDown(self):
        self.temp.cleanup()

    def test_simultaneous_reservations_allow_one_workspace_writer(self):
        create_run(self.store, run_record("r1"))
        create_run(self.store, run_record("r2"))
        result = multiprocessing.Queue()
        processes = [
            multiprocessing.Process(
                target=reserve_in_process,
                args=(str(self.store.root), run_id, attempt_id, result),
            )
            for run_id, attempt_id in (("r1", "a1"), ("r2", "a2"))
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(0, process.exitcode)
        self.assertCountEqual(["reserved", "rejected"], [result.get(timeout=2) for _ in processes])

    def test_direct_active_attempt_creation_cannot_bypass_launch_reservation(self):
        create_run(self.store, run_record("r1"))
        for state in ("reserved", "active", "cancel_requested", "validated"):
            with self.subTest(state=state), self.assertRaises(StorageError):
                self.store.create_attempt(attempt("r1", "t1", "a-" + state, state))

    def test_report_replay_keeps_one_envelope_and_one_terminal_transition(self):
        create_run(self.store, run_record("r1"))
        record = attempt("r1", "t1", "a1")
        self.store.reserve_attempt(
            record, "workspace", "launch-1", "parent-1", *dispatch(record, "task-env")
        )
        self.store.begin_launch("a1")
        self.store.record_launch_started("a1", "provider-child-1")
        body = b"report"
        envelope = {
            "schema_version": 2,
            "envelope_id": "e1",
            "run_id": "r1",
            "task_id": "t1",
            "attempt_id": "a1",
            "kind": "report",
            "from": "worker:impl-executor-cheap",
            "to": "orchestrator",
            "captured_by": "controller:local-1",
            "capture_source": "controller",
            "reply_to": "task-env",
            **selected_identity(),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "created_at": "2026-09-20T00:10:00Z",
            "provider_thread_id": None,
            "provider_turn_id": None,
            "provider_event_id": None,
        }
        envelope["provider_thread_id"] = "provider-child-1"
        envelope.update(selected_identity())
        first = self.store.capture_result(envelope, body, "launch-1:report", "captured")
        replay = self.store.capture_result(envelope, body, "launch-1:report", "captured")
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(2, self.store.count("envelopes"))
        self.assertEqual("captured", self.store.attempt_state("a1"))

    def test_terminal_attempt_cannot_be_reversed(self):
        self.assertTrue(runtime_contract.validate_attempt_transition("validated", "active"))

    def test_crash_after_host_start_reconciles_by_key_without_relaunch(self):
        create_run(self.store, run_record("r1"))
        record = attempt("r1", "t1", "a1")
        self.store.reserve_attempt(
            record, "workspace", "launch-key", "parent-1", *dispatch(record, "task-env")
        )
        self.store.begin_launch("a1")
        # The host accepted the key and made the child, but the process crashed
        # before persisting that acknowledgement.
        host_launches = {"launch-key": "provider-child-1"}
        restarted = RuntimeStore(self.store.root)
        lookups = []
        self.assertEqual(
            "provider-child-1",
            restarted.reconcile_launch(
                "launch-key", lambda key: (lookups.append(key), host_launches.get(key))[1]
            ),
        )
        self.assertEqual("provider-child-1", restarted.reconcile_launch("launch-key"))
        self.assertEqual(["launch-key"], lookups)
        with self.assertRaises(StorageError):
            restarted.begin_launch("a1")
        self.assertEqual(1, len(host_launches))
        self.assertEqual(1, restarted.count("attempts"))

    def test_capture_rejects_report_with_wrong_template_or_reply(self):
        create_run(self.store, run_record("r1"))
        record = attempt("r1", "t1", "a1")
        self.store.reserve_attempt(
            record, "workspace", "launch", "parent", *dispatch(record, "task-env")
        )
        self.store.begin_launch("a1")
        self.store.record_launch_started("a1", "child")
        body = b"report"
        envelope = self._report_envelope(body, "r1", "t1", "a1", "child")
        envelope.update(selected_identity("spec-validator-cheap"))
        with self.assertRaises(StorageError):
            self.store.capture_result(envelope, body, "event-template", "captured")
        envelope.update(selected_identity())
        envelope["reply_to"] = "other-task"
        with self.assertRaises(StorageError):
            self.store.capture_result(envelope, body, "event-reply", "captured")

    def test_worker_question_cannot_be_captured_as_a_terminal_return(self):
        create_run(self.store, run_record("r1"))
        record = attempt("r1", "t1", "a1")
        self.store.reserve_attempt(
            record, "workspace", "launch", "parent", *dispatch(record, "task-env")
        )
        self.store.begin_launch("a1")
        self.store.record_launch_started("a1", "child")
        body = b"clarification needed"
        envelope = self._report_envelope(body, "r1", "t1", "a1", "child")
        envelope["kind"] = "question"
        with self.assertRaises(StorageError):
            self.store.capture_result(envelope, body, "event-question", "captured")

    def test_report_captured_by_another_controller_is_rejected(self):
        create_run(self.store, run_record("r1"))
        record = attempt("r1", "t1", "a1")
        self.store.reserve_attempt(
            record, "workspace", "launch", "parent", *dispatch(record, "task-env")
        )
        self.store.begin_launch("a1")
        self.store.record_launch_started("a1", "child")
        body = b"report"
        envelope = self._report_envelope(body, "r1", "t1", "a1", "child")
        envelope["captured_by"] = "controller:other"
        with self.assertRaises(StorageError):
            self.store.capture_result(envelope, body, "event-wrong-controller", "captured")

    def test_repair_attempt_has_immutable_parent_and_one_format_correction(self):
        create_run(self.store, run_record("r1"))
        original = attempt("r1", "t1", "a1")
        self.store.reserve_attempt(
            original, "workspace", "launch-1", "parent", *dispatch(original, "task-env")
        )
        self.store.begin_launch("a1")
        self.store.record_launch_started("a1", "child-1")
        body = b"malformed report"
        envelope = self._report_envelope(body, "r1", "t1", "a1", "child-1")
        self.store.capture_result(envelope, body, "event-1", "captured")
        self.store.record_machine_validation("a1", False, "invalid-json")
        repair = attempt("r1", "t2", "a2")
        with self.assertRaises(StorageError):
            self.store.reserve_followup_attempt(
                repair,
                "workspace",
                "launch-2",
                "parent",
                *dispatch(repair, "task-env-2"),
                "format_correction",
                "a1",
            )
        self.store.record_decision(
            "r1", "d-format", "implementation", "format_correction", "a1", "controller:local-1"
        )
        with self.assertRaises(StorageError):
            self.store.record_decision(
                "r1", "d-rewrite", "implementation", "reject", "a1", "controller:local-1"
            )
        with self.assertRaises(StorageError):
            self.store.reserve_followup_attempt(
                repair,
                "workspace",
                "launch-2",
                "parent",
                *dispatch(repair, "task-env-2"),
                "format_correction",
                "a1",
            )
        self.store.confirm_attempt_stopped("a1", "child-1")
        self.store.reserve_followup_attempt(
            repair,
            "workspace",
            "launch-2",
            "parent",
            *dispatch(repair, "task-env-2"),
            "format_correction",
            "a1",
        )
        with self.assertRaises(StorageError):
            self.store.record_format_correction(envelope["envelope_id"], "a2")
        self.assertEqual(3, self.store.count("envelopes"))
        self.assertEqual(1, self.store.count("attempt_lineage"))
        with self.store._connect() as connection:
            original = connection.execute(
                "SELECT body FROM envelopes WHERE envelope_id=?", (envelope["envelope_id"],)
            ).fetchone()[0]
            lineage = connection.execute(
                "SELECT parent_attempt_id, purpose FROM attempt_lineage WHERE attempt_id='a2'"
            ).fetchone()
        self.assertEqual(body, original)
        self.assertEqual(("a1", "format_correction"), tuple(lineage))
        self.assertEqual("invalid", self.store.attempt_state("a1"))

    def test_accepted_outcome_requires_linked_decisions_for_validated_attempts(self):
        create_run(self.store, run_record("r1"))
        attempt_refs, decision_refs, envelope_refs, evidence, selections = [], [], [], [], []
        parent_attempt_id = None
        for index, (family, template) in enumerate(
            (
                ("implementation", "impl-executor-cheap"),
                ("specification", "spec-validator-cheap"),
                ("quality", "quality-validator-cheap"),
            ),
            start=1,
        ):
            attempt_id, task_id = "a%d" % index, "t%d" % index
            record = attempt("r1", task_id, attempt_id)
            record.update(selected_identity(template))
            dispatch_record, dispatch_body = dispatch(record, "task-%d-env" % index)
            if parent_attempt_id is None:
                self.store.reserve_attempt(
                    record,
                    "workspace",
                    "launch-%d" % index,
                    "parent",
                    dispatch_record,
                    dispatch_body,
                )
            else:
                self.store.reserve_followup_attempt(
                    record,
                    "workspace",
                    "launch-%d" % index,
                    "parent",
                    dispatch_record,
                    dispatch_body,
                    family,
                    parent_attempt_id,
                )
            self.store.begin_launch(attempt_id)
            self.store.record_launch_started(attempt_id, "child-%d" % index)
            body = ("%s report" % family).encode()
            envelope = self._report_envelope(
                body, "r1", task_id, attempt_id, "child-%d" % index, template
            )
            envelope["from"] = "worker:" + template
            envelope["reply_to"] = "task-%d-env" % index
            envelope["selected_template"] = template
            envelope.update(selected_identity(template))
            envelope["envelope_id"] = "env-%d" % index
            self.store.capture_result(envelope, body, "event-%d" % index, "captured")
            self.store.record_machine_validation(attempt_id, True, "valid-%d" % index)
            decision_id = "decision-%d" % index
            self.store.record_decision(
                "r1", decision_id, family, "accept", attempt_id, "controller:local-1"
            )
            attempt_refs.append(attempt_id)
            selections.append({"attempt_id": attempt_id, **selected_identity(template)})
            decision_refs.append(decision_id)
            envelope_refs.append(envelope["envelope_id"])
            parent_attempt_id = attempt_id
            evidence.append(
                {
                    "evidence_ref": envelope["envelope_id"],
                    "captured_by": "controller:local-1",
                    "capture_source": "controller",
                    "command": "offline-check",
                    "output": "passed",
                    "exit_status": 0,
                    "tested_tree_fingerprint": "a" * 64,
                }
            )
            if index < 3:
                self.store.confirm_attempt_stopped(attempt_id, "child-%d" % index)
        outcome = {
            "schema_version": 2,
            "run_id": "r1",
            "outcome": "accepted",
            "rationale": "all linked stages accepted",
            "template_selections": selections,
            "validated_attempt_refs": attempt_refs,
            "orchestrator_decision_refs": decision_refs,
            "execution_evidence": evidence,
        }
        self.assertEqual(
            [],
            self.store.validate_accepted_outcome(outcome, "controller:local-1", set(envelope_refs)),
        )
        tampered = dict(outcome)
        tampered["template_selections"] = [dict(selection) for selection in selections]
        tampered["template_selections"][0]["resolved_model"] = "invented-model"
        self.assertTrue(
            self.store.validate_accepted_outcome(tampered, "controller:local-1", set(envelope_refs))
        )

    @staticmethod
    def _report_envelope(
        body, run_id, task_id, attempt_id, provider_thread_id, template_id="impl-executor-cheap"
    ):
        return {
            "schema_version": 2,
            "envelope_id": "env-" + hashlib.sha256(body).hexdigest()[:8],
            "run_id": run_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "kind": "report",
            "from": "worker:impl-executor-cheap",
            "to": "orchestrator",
            "captured_by": "controller:local-1",
            "capture_source": "controller",
            "reply_to": "task-env",
            **selected_identity(template_id),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "created_at": "2026-09-20T00:10:00Z",
            "provider_thread_id": provider_thread_id,
            "provider_turn_id": None,
            "provider_event_id": "event-1",
        }

    def test_accepted_outcome_requires_implementation_specification_and_quality_decisions(self):
        create_run(self.store, run_record("r1"))
        outcome = {
            "schema_version": 2,
            "run_id": "r1",
            "outcome": "accepted",
            "rationale": "done",
            "template_selections": [
                {"attempt_id": "impl", **selected_identity()},
                {"attempt_id": "spec", **selected_identity("spec-validator-cheap")},
            ],
            "validated_attempt_refs": ["impl", "spec"],
            "orchestrator_decision_refs": ["d1"],
            "execution_evidence": [
                {
                    "evidence_ref": "e",
                    "captured_by": "controller:local-1",
                    "capture_source": "controller",
                    "command": "check",
                    "output": "ok",
                    "exit_status": 0,
                    "tested_tree_fingerprint": "a" * 64,
                }
            ],
        }
        errors = self.store.validate_accepted_outcome(outcome, "controller:local-1", {"e"})
        self.assertEqual(
            ["accepted outcome requires implementation, specification, and quality decisions"],
            errors,
        )


if __name__ == "__main__":
    unittest.main()
