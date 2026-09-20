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


def run_record(run_id="run-1"):
    return {"schema_version": 2, "run_id": run_id, "host_id": "offline", "workspace_fingerprint": "ws",
            "configuration_fingerprint": "config", "principal_id": "controller:local-1",
            "created_at": "2026-09-20T00:00:00Z", "state": "created"}


def attempt_record():
    return {"schema_version": 2, "run_id": "run-1", "task_id": "task-1", "attempt_id": "attempt-1",
            "provider_thread_id": "thread-1", "provider_turn_id": "turn-1", "provider_event_id": None,
            "selected_template": "impl-executor-cheap", "started_at": "2026-09-20T00:00:00Z",
            "last_activity_at": "2026-09-20T00:00:00Z", "deadline_at": "2026-09-20T01:00:00Z",
            "last_envelope_id": None, "observed_activity_state": "active", "provider_observed_at": None,
            "local_bookkeeping_at": "2026-09-20T00:00:00Z", "controller_lease_expires_at": "2026-09-20T01:00:00Z",
            "state": "active"}


def envelope_record(body, event_id="provider-event-1"):
    return {"schema_version": 2, "envelope_id": "env-" + hashlib.sha256(body).hexdigest()[:10], "run_id": "run-1",
            "task_id": "task-1", "attempt_id": "attempt-1", "kind": "report", "from": "worker:implementer",
            "to": "orchestrator", "captured_by": "controller:local-1", "capture_source": "controller",
            "reply_to": "env-task-1", "body_sha256": hashlib.sha256(body).hexdigest(),
            "created_at": "2026-09-20T00:02:00Z", "provider_thread_id": "thread-1",
            "provider_turn_id": "turn-1", "provider_event_id": event_id}


def capture_in_process(root, body, queue):
    store = RuntimeStore(root)
    try:
        queue.put(store.capture_result(envelope_record(body), body, "provider:thread-1:event-1", "captured"))
    except Exception as exc:  # pragma: no cover - assertion reads the child result
        queue.put({"error": type(exc).__name__})


def capture_then_forced_exit(root, before_commit):
    store = RuntimeStore(root)
    try:
        store.capture_result(envelope_record(b"forced-exit"), b"forced-exit", "forced-exit", "captured",
                             fail_before_commit=before_commit)
    except StorageError:
        pass
    os._exit(17 if before_commit else 18)


class RuntimeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / ".root-architect" / "state"
        self.store = RuntimeStore(self.root)
        self.store.create_run(run_record())
        self.store.create_attempt(attempt_record())

    def tearDown(self):
        self.temp.cleanup()

    def test_identical_concurrent_delivery_has_one_envelope_and_transition(self):
        queue = multiprocessing.Queue()
        workers = [multiprocessing.Process(target=capture_in_process, args=(str(self.root), b"same", queue)) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(0, worker.exitcode)
        results = [queue.get(timeout=2) for _ in workers]
        self.assertEqual(1, self.store.count("envelopes"))
        self.assertEqual({result["envelope_id"] for result in results}, {results[0]["envelope_id"]})
        self.assertEqual("captured", self.store.attempt_state("attempt-1"))

    def test_conflicting_identity_blocks_run_and_preserves_both_bodies(self):
        first = self.store.capture_result(envelope_record(b"first"), b"first", "provider:thread-1:event-1", "captured")
        conflict = self.store.capture_result(envelope_record(b"second"), b"second", "provider:thread-1:event-1", "captured")
        self.assertEqual("captured", first["status"])
        self.assertEqual("conflict", conflict["status"])
        self.assertEqual("blocked", self.store.run_state("run-1"))
        self.assertEqual(2, self.store.count("envelopes"))

    def test_failure_before_commit_leaves_no_partial_evidence_or_transition(self):
        with self.assertRaises(StorageError):
            self.store.capture_result(envelope_record(b"body"), b"body", "dedup-1", "captured", fail_before_commit=True)
        self.assertEqual(0, self.store.count("envelopes"))
        self.assertEqual("active", self.store.attempt_state("attempt-1"))

    def test_restart_after_commit_keeps_evidence_and_transition_together(self):
        self.store.capture_result(envelope_record(b"body"), b"body", "dedup-1", "captured")
        restarted = RuntimeStore(self.root)
        self.assertEqual(1, restarted.count("envelopes"))
        self.assertEqual("captured", restarted.attempt_state("attempt-1"))

    def test_forced_exit_before_and_after_commit_has_no_torn_state(self):
        before = multiprocessing.Process(target=capture_then_forced_exit, args=(str(self.root), True))
        before.start()
        before.join(10)
        self.assertEqual(17, before.exitcode)
        self.assertEqual(0, self.store.count("envelopes"))
        self.assertEqual("active", self.store.attempt_state("attempt-1"))
        after = multiprocessing.Process(target=capture_then_forced_exit, args=(str(self.root), False))
        after.start()
        after.join(10)
        self.assertEqual(18, after.exitcode)
        self.assertEqual(1, RuntimeStore(self.root).count("envelopes"))
        self.assertEqual("captured", RuntimeStore(self.root).attempt_state("attempt-1"))

    def test_write_failure_rolls_back(self):
        self.store.fail_next_write_for_test()
        with self.assertRaises(StorageError):
            self.store.capture_result(envelope_record(b"body"), b"body", "dedup-1", "captured")
        self.assertEqual(0, self.store.count("envelopes"))
        self.assertEqual("active", self.store.attempt_state("attempt-1"))

    def test_exports_are_generated_and_partial_export_is_recoverable(self):
        self.store.capture_result(envelope_record(b"body"), b"body", "dedup-1", "captured")
        destination = Path(self.temp.name) / "exports"
        with self.assertRaises(OSError):
            self.store.export(destination, fail_after="json")
        RuntimeStore(self.root).export(destination)
        self.assertEqual("run-1", json.loads((destination / "runtime.json").read_text())["runs"][0]["run_id"])
        self.assertIn("run-1", (destination / "runtime.md").read_text())

    def test_rejects_unsupported_storage_roots(self):
        with self.assertRaises(UnsupportedStorageRoot):
            RuntimeStore(Path("relative") / "state")
