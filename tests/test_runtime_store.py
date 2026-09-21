"""Process-level checks for the local, transactional runtime store."""

import hashlib
import json
import multiprocessing
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from runtime_store import RuntimeStore, StorageError, UnsupportedStorageRoot
import render_agents


def selected_identity():
    catalog = render_agents.select_catalog("codex")
    selected = render_agents.select_template(catalog, "impl-executor-cheap")
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


def run_record(run_id="run-1"):
    return {
        "schema_version": 2,
        "run_id": run_id,
        "host_id": "codex",
        "workspace_fingerprint": "ws",
        "configuration_fingerprint": "config",
        "principal_id": "controller:local-1",
        "created_at": "2026-09-20T00:00:00Z",
        "state": "created",
    }


def attempt_record():
    return {
        "schema_version": 2,
        "run_id": "run-1",
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "provider_thread_id": None,
        "provider_turn_id": "turn-1",
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
        "state": "reserved",
    }


def create_run(store, record):
    return store.create_run(record, render_agents.select_catalog("codex"))


def envelope_record(body, event_id="provider-event-1"):
    return {
        "schema_version": 2,
        "envelope_id": "env-" + hashlib.sha256(body).hexdigest()[:10],
        "run_id": "run-1",
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "kind": "report",
        "from": "worker:impl-executor-cheap",
        "to": "orchestrator",
        "captured_by": "controller:local-1",
        "capture_source": "controller",
        "reply_to": "env-task-1",
        **selected_identity(),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "created_at": "2026-09-20T00:02:00Z",
        "provider_thread_id": "thread-1",
        "provider_turn_id": "turn-1",
        "provider_event_id": event_id,
    }


def capture_in_process(root, body, queue):
    store = RuntimeStore(root)
    try:
        queue.put(
            store.capture_result(
                envelope_record(body), body, "provider:thread-1:event-1", "captured"
            )
        )
    except Exception as exc:  # pragma: no cover - assertion reads the child result
        queue.put({"error": type(exc).__name__})


def capture_then_forced_exit(root, before_commit):
    store = RuntimeStore(root)
    try:
        store.capture_result(
            envelope_record(b"forced-exit"),
            b"forced-exit",
            "forced-exit",
            "captured",
            fail_before_commit=before_commit,
        )
    except StorageError:
        pass
    os._exit(17 if before_commit else 18)


class RuntimeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / ".root-architect" / "state"
        self.store = RuntimeStore(self.root)
        create_run(self.store, run_record())
        record = attempt_record()
        dispatch_body = b"task"
        dispatch_envelope = {
            "schema_version": 2,
            "envelope_id": "env-task-1",
            "run_id": "run-1",
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "kind": "task",
            "from": "orchestrator",
            "to": "worker:impl-executor-cheap",
            "captured_by": "controller:local-1",
            "capture_source": "controller",
            "reply_to": None,
            **selected_identity(),
            "body_sha256": hashlib.sha256(dispatch_body).hexdigest(),
            "created_at": "2026-09-20T00:00:00Z",
            "provider_thread_id": None,
            "provider_turn_id": None,
            "provider_event_id": None,
        }
        self.store.reserve_attempt(
            record, "ws", "launch-1", "parent-1", dispatch_envelope, dispatch_body
        )
        self.store.begin_launch("attempt-1")
        self.store.record_launch_started("attempt-1", "thread-1")

    def tearDown(self):
        self.temp.cleanup()

    def test_reservation_rejects_template_identity_not_declared_by_run_catalog(self):
        identity_fields = (
            "family",
            "selected_template",
            "template_catalog_sha256",
            "requested_model_tier",
            "requested_effort",
            "resolved_model",
            "resolved_effort",
            "effective_model",
            "effective_effort",
        )
        for field, value in (
            ("selected_template", "impl-executor-dynamic"),
            ("template_catalog_sha256", "b" * 64),
            ("requested_model_tier", "strong"),
            ("resolved_model", "invented-model"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                store = RuntimeStore(Path(directory) / ".root-architect" / "state")
                create_run(store, run_record())
                record = attempt_record()
                record[field] = value
                body = b"task"
                dispatch = {
                    "schema_version": 2,
                    "envelope_id": "env-task-1",
                    "run_id": record["run_id"],
                    "task_id": record["task_id"],
                    "attempt_id": record["attempt_id"],
                    "kind": "task",
                    "from": "orchestrator",
                    "to": "worker:" + record["selected_template"],
                    "captured_by": "controller:local-1",
                    "capture_source": "controller",
                    "reply_to": None,
                    **{key: record[key] for key in identity_fields},
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "created_at": "2026-09-20T00:00:00Z",
                    "provider_thread_id": None,
                    "provider_turn_id": None,
                    "provider_event_id": None,
                }
                with self.assertRaises(StorageError):
                    store.reserve_attempt(
                        record, "ws", "launch-" + field, "parent-1", dispatch, body
                    )

    def test_capture_requires_exact_persisted_template_provenance(self):
        changes = {
            "family": "quality-validator",
            "selected_template": "impl-executor-strong",
            "template_catalog_sha256": "b" * 64,
            "requested_model_tier": "strong",
            "requested_effort": "high",
            "resolved_model": "gpt-5.6-sol",
            "resolved_effort": "high",
            "effective_model": "gpt-5.6-luna",
            "effective_effort": "medium",
        }
        for field, value in changes.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                store = RuntimeStore(Path(directory) / ".root-architect" / "state")
                create_run(store, run_record())
                record = attempt_record()
                body = b"task"
                dispatch = {
                    "schema_version": 2,
                    "envelope_id": "env-task-1",
                    "run_id": record["run_id"],
                    "task_id": record["task_id"],
                    "attempt_id": record["attempt_id"],
                    "kind": "task",
                    "from": "orchestrator",
                    "to": "worker:" + record["selected_template"],
                    "captured_by": "controller:local-1",
                    "capture_source": "controller",
                    "reply_to": None,
                    **selected_identity(),
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "created_at": "2026-09-20T00:00:00Z",
                    "provider_thread_id": None,
                    "provider_turn_id": None,
                    "provider_event_id": None,
                }
                store.reserve_attempt(record, "ws", "launch-" + field, "parent-1", dispatch, body)
                store.begin_launch(record["attempt_id"])
                store.record_launch_started(record["attempt_id"], "thread-1")
                report = envelope_record(b"report")
                report[field] = value
                report["reply_to"] = "env-task-1"
                if field == "selected_template":
                    report["from"] = "worker:" + value
                with self.assertRaises(StorageError):
                    store.capture_result(report, b"report", "event-" + field, "captured")

    def test_identical_concurrent_delivery_has_one_envelope_and_transition(self):
        queue = multiprocessing.Queue()
        workers = [
            multiprocessing.Process(
                target=capture_in_process, args=(str(self.root), b"same", queue)
            )
            for _ in range(2)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(0, worker.exitcode)
        results = [queue.get(timeout=2) for _ in workers]
        self.assertEqual(2, self.store.count("envelopes"))
        self.assertEqual({result["envelope_id"] for result in results}, {results[0]["envelope_id"]})
        self.assertEqual("captured", self.store.attempt_state("attempt-1"))

    def test_conflicting_identity_blocks_run_and_preserves_both_bodies(self):
        first = self.store.capture_result(
            envelope_record(b"first"), b"first", "provider:thread-1:event-1", "captured"
        )
        conflict = self.store.capture_result(
            envelope_record(b"second"), b"second", "provider:thread-1:event-1", "captured"
        )
        self.assertEqual("captured", first["status"])
        self.assertEqual("conflict", conflict["status"])
        self.assertEqual("blocked", self.store.run_state("run-1"))
        self.assertEqual(3, self.store.count("envelopes"))

    def test_failure_before_commit_leaves_no_partial_evidence_or_transition(self):
        with self.assertRaises(StorageError):
            self.store.capture_result(
                envelope_record(b"body"), b"body", "dedup-1", "captured", fail_before_commit=True
            )
        self.assertEqual(1, self.store.count("envelopes"))
        self.assertEqual("active", self.store.attempt_state("attempt-1"))

    def test_restart_after_commit_keeps_evidence_and_transition_together(self):
        self.store.capture_result(envelope_record(b"body"), b"body", "dedup-1", "captured")
        restarted = RuntimeStore(self.root)
        self.assertEqual(2, restarted.count("envelopes"))
        self.assertEqual("captured", restarted.attempt_state("attempt-1"))

    def test_forced_exit_before_and_after_commit_has_no_torn_state(self):
        before = multiprocessing.Process(
            target=capture_then_forced_exit, args=(str(self.root), True)
        )
        before.start()
        before.join(10)
        self.assertEqual(17, before.exitcode)
        self.assertEqual(1, self.store.count("envelopes"))
        self.assertEqual("active", self.store.attempt_state("attempt-1"))
        after = multiprocessing.Process(
            target=capture_then_forced_exit, args=(str(self.root), False)
        )
        after.start()
        after.join(10)
        self.assertEqual(18, after.exitcode)
        self.assertEqual(2, RuntimeStore(self.root).count("envelopes"))
        self.assertEqual("captured", RuntimeStore(self.root).attempt_state("attempt-1"))

    def test_write_failure_rolls_back(self):
        self.store.fail_next_write_for_test()
        with self.assertRaises(StorageError):
            self.store.capture_result(envelope_record(b"body"), b"body", "dedup-1", "captured")
        self.assertEqual(1, self.store.count("envelopes"))
        self.assertEqual("active", self.store.attempt_state("attempt-1"))

    def test_exports_are_generated_and_partial_export_is_recoverable(self):
        self.store.capture_result(envelope_record(b"body"), b"body", "dedup-1", "captured")
        destination = Path(self.temp.name) / "exports"
        with self.assertRaises(OSError):
            self.store.export(destination, fail_after="json")
        RuntimeStore(self.root).export(destination)
        self.assertEqual(
            "run-1", json.loads((destination / "runtime.json").read_text())["runs"][0]["run_id"]
        )
        self.assertIn("run-1", (destination / "runtime.md").read_text())

    def test_rejects_unsupported_storage_roots(self):
        with self.assertRaises(UnsupportedStorageRoot):
            RuntimeStore(Path("relative") / "state")
