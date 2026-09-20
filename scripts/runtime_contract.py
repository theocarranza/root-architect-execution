"""Offline validation for version 2 runtime records.

The schemas reject malformed individual records.  This module owns the rules
that require comparing fields: routes, controller capture, scope, template
catalogues, and binding a return to the precise attempt it answers.
"""

from pathlib import Path

from jsonschema_mini import Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
RECORD_TYPES = ("run", "preflight", "attempt", "event", "envelope")

_ROUTES = {
    ("root", "orchestrator"): {"task", "answer"},
    ("orchestrator", "root"): {"question", "outcome"},
    ("orchestrator", "worker"): {"task", "answer"},
    ("worker", "orchestrator"): {"report", "question"},
    ("controller", "root"): {"failure", "lifecycle"},
    ("controller", "orchestrator"): {"failure", "lifecycle"},
}
_RUN_LEVEL_KINDS = {"failure", "lifecycle", "outcome"}
_ATTEMPT_TRANSITIONS = {
    "reserved": {"starting"},
    "starting": {"active", "start_failed"},
    "active": {"captured", "cancel_requested"},
    "captured": {"validated", "invalid"},
    "cancel_requested": {"stopped", "stop_unknown"},
}


def _schema(name):
    if name not in RECORD_TYPES and name != "outcome":
        raise ValueError("unknown runtime record type: %s" % name)
    filename = "orchestrator-outcome.schema.json" if name == "outcome" else "runtime-%s.schema.json" % name
    return Validator(SCHEMAS / filename)


def validate_record(name, record):
    """Return schema errors for exactly one v2 runtime record."""
    return _schema(name).validate(record)


def _party_class(value):
    if not isinstance(value, str):
        return None
    if value.startswith("worker:"):
        return "worker"
    if value.startswith("controller:"):
        return "controller"
    return value


def validate_envelope(record, controller_principal):
    """Validate a captured v2 envelope and its trusted controller identity."""
    errors = validate_record("envelope", record)
    if errors:
        return errors
    if not isinstance(controller_principal, str) or not controller_principal.startswith("controller:"):
        return ["controller principal is not a controller identity"]
    if record["captured_by"] != controller_principal:
        return ["envelope captured_by does not match the trusted controller"]

    task_id, attempt_id = record["task_id"], record["attempt_id"]
    if (task_id is None) != (attempt_id is None):
        return ["task_id and attempt_id must be present together"]
    if task_id is None and record["kind"] not in _RUN_LEVEL_KINDS:
        return ["only run-level failure, lifecycle, or outcome envelopes may omit task and attempt"]
    if task_id is not None and record["kind"] == "outcome":
        return ["outcome envelopes are run-level"]

    route = (_party_class(record["from"]), _party_class(record["to"]))
    allowed = _ROUTES.get(route)
    if allowed is None or record["kind"] not in allowed:
        return ["invalid envelope route %s -> %s for %s" % (record["from"], record["to"], record["kind"])]
    return []


def validate_attempt(record, permitted_templates):
    """Validate one attempt against the controller's declared template catalog."""
    errors = validate_record("attempt", record)
    if errors:
        return errors
    if not isinstance(permitted_templates, (set, frozenset, list, tuple)):
        return ["permitted templates must be a controller-owned collection"]
    if record["selected_template"] not in permitted_templates:
        return ["attempt selected_template is not in the declared catalog"]
    return []


def validate_attempt_transition(previous_state, current_state):
    """Reject terminal rewrites and every transition outside the v2 lifecycle.

    The current record deliberately stores one state; the append-only event
    service supplies the preceding state when it proposes a transition.
    """
    if not isinstance(previous_state, str) or not isinstance(current_state, str):
        return ["attempt transition states must be strings"]
    if current_state not in _ATTEMPT_TRANSITIONS.get(previous_state, set()):
        return ["attempt transition %s -> %s is not permitted" % (previous_state, current_state)]
    return []


def validate_answer_for_attempt(record, expected_attempt, controller_principal):
    """Ensure a captured return cannot be reused for another task or attempt."""
    errors = validate_envelope(record, controller_principal)
    if errors:
        return errors
    if record["kind"] not in {"answer", "report"}:
        return ["only answer or report envelopes may satisfy an attempt"]
    if not isinstance(expected_attempt, dict):
        return ["expected attempt is not an object"]
    for field in ("run_id", "task_id", "attempt_id"):
        if record[field] != expected_attempt.get(field):
            return ["envelope %s does not match expected %s" % (field, field)]
    return []


def validate_outcome(record):
    """Validate v2 evidence references required for an orchestrator outcome."""
    errors = validate_record("outcome", record)
    if errors:
        return errors
    outcome = record["outcome"]
    if outcome == "accepted":
        if not record.get("validated_attempt_refs"):
            return ["accepted outcome requires validated attempt references"]
        if not record.get("orchestrator_decision_refs"):
            return ["accepted outcome requires orchestrator decision references"]
    if outcome == "blocked":
        if not record.get("blocked_reason"):
            return ["blocked outcome requires a reason"]
        if not record.get("question_or_failure_refs"):
            return ["blocked outcome requires question or failure evidence references"]
    return []


def valid_preflight(run_id, host_id, workspace_fingerprint, configuration_fingerprint, principal_id):
    """Small valid fixture builder for callers testing a literal preflight result."""
    return {
        "schema_version": 2,
        "preflight_id": "preflight-" + run_id,
        "run_id": run_id,
        "host_id": host_id,
        "workspace_fingerprint": workspace_fingerprint,
        "configuration_fingerprint": configuration_fingerprint,
        "principal_id": principal_id,
        "controller_session_id": "controller-session-1",
        "passed": True,
        "checked_at": "1970-01-01T00:00:00Z",
    }


def read_v1_envelope(record):
    """Read only the historic mailbox header; do not reinterpret it as v2."""
    return Validator(SCHEMAS / "envelope.schema.json").validate(record)


def read_v1_brief(record):
    """Read a historic dispatch brief through its version 1 schema."""
    return Validator(SCHEMAS / "brief.schema.json").validate(record)


def read_v1_outcome(record):
    """Read a historic outcome through the pre-v2 reader kept below."""
    required = {"run_id", "outcome", "dispatched", "envelope_count", "rationale"}
    if not isinstance(record, dict):
        return ["$: expected type object"]
    missing = sorted(required - set(record))
    return ["$: missing required property %r" % name for name in missing]
