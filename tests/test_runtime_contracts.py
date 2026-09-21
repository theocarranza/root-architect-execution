"""Offline contracts for version 2 runtime records."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import runtime_contract
import render_agents


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


def envelope(**changes):
    record = {
        "schema_version": 2,
        "envelope_id": "env-1",
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
        "body_sha256": "a" * 64,
        "created_at": "2026-09-20T00:00:00Z",
        "provider_thread_id": "thread-1",
        "provider_turn_id": "turn-1",
        "provider_event_id": "event-1",
    }
    record.update(changes)
    if not (record["from"].startswith("worker:") or record["to"].startswith("worker:")):
        for field in runtime_contract._TEMPLATE_IDENTITY_FIELDS:
            record[field] = None
    return record


def attempt(**changes):
    record = {
        "schema_version": 2,
        "run_id": "run-1",
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "provider_thread_id": "thread-1",
        "provider_turn_id": "turn-1",
        "provider_event_id": "event-1",
        **selected_identity(),
        "started_at": "2026-09-20T00:00:00Z",
        "last_activity_at": "2026-09-20T00:01:00Z",
        "deadline_at": "2026-09-20T01:00:00Z",
        "last_envelope_id": None,
        "observed_activity_state": "active",
        "provider_observed_at": "2026-09-20T00:01:00Z",
        "local_bookkeeping_at": "2026-09-20T00:01:01Z",
        "controller_lease_expires_at": "2026-09-20T01:00:00Z",
        "state": "active",
    }
    record.update(changes)
    return record


class RuntimeContractTests(unittest.TestCase):
    def assert_invalid(self, errors):
        self.assertTrue(errors, "record unexpectedly validated")

    def test_runtime_schemas_reject_non_object_and_unknown_fields(self):
        for name in runtime_contract.RECORD_TYPES:
            for value in (None, [], "record"):
                self.assert_invalid(runtime_contract.validate_record(name, value))
        self.assert_invalid(runtime_contract.validate_record("attempt", attempt(extra=True)))

    def test_v2_attempt_requires_explicit_catalog_identity_and_unknown_effective_values(self):
        missing_identity = attempt()
        missing_identity.pop("template_catalog_sha256")
        self.assert_invalid(runtime_contract.validate_record("attempt", missing_identity))
        catalog = render_agents.select_catalog("codex")
        selected = render_agents.select_template(catalog, "impl-executor-cheap")
        record = attempt(
            family=selected["family"],
            template_catalog_sha256=catalog["catalog_sha256"],
            requested_model_tier=selected["requested"]["model_tier"],
            requested_effort=selected["requested"]["effort"],
            resolved_model=selected["resolved"]["model"],
            resolved_effort=selected["resolved"]["effort"],
            effective_model=None,
            effective_effort=None,
        )
        self.assertEqual([], runtime_contract.validate_attempt(record, catalog))
        self.assert_invalid(
            runtime_contract.validate_attempt(
                dict(record, template_catalog_sha256="b" * 64), catalog
            )
        )

    def test_v2_brief_admission_binds_selected_template_to_catalog(self):
        catalog = render_agents.select_catalog("codex")
        selected = render_agents.select_template(catalog, "impl-executor-cheap")
        brief = {
            "schema_version": 2,
            "run_id": "run-1",
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "family": selected["family"],
            "role": selected["family"],
            "selected_template": selected["template_id"],
            "template_catalog_sha256": catalog["catalog_sha256"],
            "requested_model_tier": selected["requested"]["model_tier"],
            "requested_effort": selected["requested"]["effort"],
            "resolved_model": selected["resolved"]["model"],
            "resolved_effort": selected["resolved"]["effort"],
            "effective_model": None,
            "effective_effort": None,
            "task": "Implement",
            "attempt": 1,
            "max_attempts": 3,
            "model": selected["resolved"]["model"],
            "effort": "low",
            "read_paths": [],
            "write_paths": [],
            "acceptance": [{"command": "true", "expect": "pass"}],
            "constraints": ["Stay in scope"],
            "owner_owned_paths": [],
            "expected_result": "Change",
        }
        self.assertEqual([], runtime_contract.validate_brief(brief, catalog))
        incomplete = dict(brief)
        incomplete.pop("template_catalog_sha256")
        self.assert_invalid(runtime_contract.validate_brief(incomplete, catalog))
        undeclared = dict(brief, selected_template="dynamic-worker")
        self.assert_invalid(runtime_contract.validate_brief(undeclared, catalog))

    def test_worker_capture_and_outcome_require_selection_provenance(self):
        incomplete = envelope()
        incomplete.pop("template_catalog_sha256")
        self.assert_invalid(runtime_contract.validate_envelope(incomplete, "controller:local-1"))
        self.assert_invalid(
            runtime_contract.validate_record(
                "outcome",
                {
                    "schema_version": 2,
                    "run_id": "run-1",
                    "outcome": "rejected",
                    "rationale": "failed",
                },
            )
        )

    def test_preflight_requires_literal_boolean(self):
        record = runtime_contract.valid_preflight(
            "run-1", "codex", "workspace-fingerprint", "config-fingerprint", "root:alice"
        )
        self.assertEqual([], runtime_contract.validate_record("preflight", record))
        record["passed"] = "false"
        self.assert_invalid(runtime_contract.validate_record("preflight", record))

    def test_envelope_requires_complete_correlation(self):
        record = envelope()
        self.assertEqual([], runtime_contract.validate_envelope(record, "controller:local-1"))
        record.pop("attempt_id")
        self.assert_invalid(runtime_contract.validate_envelope(record, "controller:local-1"))

    def test_envelope_cannot_satisfy_another_attempt(self):
        errors = runtime_contract.validate_answer_for_attempt(
            envelope(),
            {"run_id": "run-1", "task_id": "task-1", "attempt_id": "attempt-2"},
            "controller:local-1",
        )
        self.assert_invalid(errors)

    def test_return_binds_dispatch_envelope_and_selected_template(self):
        dispatched = {
            "run_id": "run-1",
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "dispatched_envelope_id": "env-task-1",
            **selected_identity(),
        }
        self.assertEqual(
            [],
            runtime_contract.validate_answer_for_attempt(
                envelope(selected_template="impl-executor-cheap"),
                dispatched,
                "controller:local-1",
            ),
        )
        for returned in (
            envelope(reply_to="env-task-other", selected_template="impl-executor-cheap"),
            envelope(selected_template="impl-executor-mid"),
        ):
            self.assert_invalid(
                runtime_contract.validate_answer_for_attempt(
                    returned, dispatched, "controller:local-1"
                )
            )

    def test_attempt_rejects_an_invented_template(self):
        errors = runtime_contract.validate_attempt(
            attempt(selected_template="invented-template"), {"impl-executor-cheap"}
        )
        self.assert_invalid(errors)

    def test_attempt_uses_the_plan_lifecycle_vocabulary(self):
        self.assertEqual([], runtime_contract.validate_record("attempt", attempt()))
        self.assert_invalid(runtime_contract.validate_record("attempt", attempt(state="running")))
        self.assert_invalid(runtime_contract.validate_record("attempt", attempt(state="returned")))

    def test_attempt_transitions_follow_the_immutable_lifecycle(self):
        for previous, current in (
            ("reserved", "starting"),
            ("starting", "active"),
            ("starting", "start_failed"),
            ("active", "captured"),
            ("active", "cancel_requested"),
            ("captured", "validated"),
            ("captured", "invalid"),
            ("cancel_requested", "stopped"),
            ("cancel_requested", "stop_unknown"),
        ):
            self.assertEqual([], runtime_contract.validate_attempt_transition(previous, current))
        for previous, current in (
            ("reserved", "active"),
            ("active", "validated"),
            ("validated", "active"),
            ("stop_unknown", "starting"),
            ("captured", "stopped"),
        ):
            self.assert_invalid(runtime_contract.validate_attempt_transition(previous, current))

    def test_envelope_rejects_wrong_route(self):
        self.assert_invalid(
            runtime_contract.validate_envelope(
                envelope(**{"from": "worker:implementer", "to": "root"}), "controller:local-1"
            )
        )

    def test_only_run_level_envelopes_can_have_null_task_and_attempt(self):
        self.assert_invalid(
            runtime_contract.validate_envelope(
                envelope(task_id=None, attempt_id=None), "controller:local-1"
            )
        )
        lifecycle = envelope(
            task_id=None,
            attempt_id=None,
            kind="lifecycle",
            reply_to=None,
            **{"from": "controller:local-1", "to": "orchestrator"},
        )
        self.assertEqual([], runtime_contract.validate_envelope(lifecycle, "controller:local-1"))

    def test_controller_capture_does_not_change_business_authorship(self):
        self.assertEqual([], runtime_contract.validate_envelope(envelope(), "controller:local-1"))
        self.assert_invalid(
            runtime_contract.validate_envelope(
                envelope(captured_by="orchestrator"), "controller:local-1"
            )
        )
        self.assert_invalid(
            runtime_contract.validate_envelope(
                envelope(captured_by="controller:forged"), "controller:local-1"
            )
        )

    def test_legacy_v1_readers_are_explicit_and_remain_accepted(self):
        legacy = {
            "run_id": "20260920-run",
            "seq": 1,
            "kind": "report",
            "from": "worker:implementer",
            "to": "orchestrator",
            "persisted_by": "orchestrator",
            "created_at": "now",
            "body_sha256": "a" * 64,
        }
        self.assertEqual([], runtime_contract.read_v1_envelope(legacy))
        self.assert_invalid(runtime_contract.validate_record("envelope", legacy))

    def test_v2_outcomes_use_evidence_references_not_counts_or_filenames(self):
        accepted = {
            "schema_version": 2,
            "run_id": "run-1",
            "outcome": "accepted",
            "rationale": "validated",
            "template_selections": [{"attempt_id": "attempt-1", **selected_identity()}],
            "validated_attempt_refs": ["attempt-1"],
            "orchestrator_decision_refs": ["decision-1"],
            "execution_evidence": [
                {
                    "evidence_ref": "env-command-1",
                    "captured_by": "controller:local-1",
                    "capture_source": "controller",
                    "command": "python3 -m unittest",
                    "output": "OK",
                    "exit_status": 0,
                    "tested_tree_fingerprint": "a" * 64,
                }
            ],
        }
        self.assertEqual(
            [],
            runtime_contract.validate_outcome(accepted, "controller:local-1", {"env-command-1"}),
        )
        no_execution_evidence = copy.deepcopy(accepted)
        no_execution_evidence.pop("execution_evidence")
        self.assert_invalid(runtime_contract.validate_outcome(no_execution_evidence))
        self.assert_invalid(
            runtime_contract.validate_outcome(
                {
                    "schema_version": 2,
                    "run_id": "run-1",
                    "outcome": "accepted",
                    "rationale": "counted",
                    "dispatched": [],
                    "envelope_count": 1,
                }
            )
        )
        blocked = {
            "schema_version": 2,
            "run_id": "run-1",
            "outcome": "blocked",
            "rationale": "waiting",
            "template_selections": [],
            "blocked_reason": "need operator input",
            "question_or_failure_refs": ["env-question-1"],
        }
        self.assertEqual([], runtime_contract.validate_outcome(blocked))
        missing_evidence = copy.deepcopy(blocked)
        missing_evidence.pop("question_or_failure_refs")
        self.assert_invalid(runtime_contract.validate_outcome(missing_evidence))

    def test_accepted_outcome_rejects_worker_copyable_execution_evidence(self):
        accepted = {
            "schema_version": 2,
            "run_id": "run-1",
            "outcome": "accepted",
            "rationale": "validated",
            "template_selections": [{"attempt_id": "attempt-1", **selected_identity()}],
            "validated_attempt_refs": ["attempt-1"],
            "orchestrator_decision_refs": ["decision-1"],
            "execution_evidence": [
                {
                    "evidence_ref": "worker-claimed-capture",
                    "captured_by": "controller:local-1",
                    "capture_source": "controller",
                    "command": "python3 -m unittest",
                    "output": "OK",
                    "exit_status": 0,
                    "tested_tree_fingerprint": "a" * 64,
                }
            ],
        }
        self.assert_invalid(
            runtime_contract.validate_outcome(accepted, "controller:local-1", set())
        )
        self.assertEqual(
            [],
            runtime_contract.validate_outcome(
                accepted, "controller:local-1", {"worker-claimed-capture"}
            ),
        )
