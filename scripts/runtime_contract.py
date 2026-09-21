"""Offline validation for version 2 runtime records.

The schemas reject malformed individual records.  This module owns the rules
that require comparing fields: routes, controller capture, scope, template
catalogues, and binding a return to the precise attempt it answers.
"""

from pathlib import Path

from jsonschema_mini import Validator
import render_agents


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
    filename = (
        "orchestrator-outcome.schema.json" if name == "outcome" else "runtime-%s.schema.json" % name
    )
    return Validator(SCHEMAS / filename)


def validate_record(name, record):
    """Return schema errors for exactly one v2 runtime record."""
    return _schema(name).validate(record)


_TEMPLATE_IDENTITY_FIELDS = (
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


def _validate_template_identity(record, catalog):
    if not isinstance(catalog, dict):
        return ["controller-owned template catalog is required"]
    catalog_errors = render_agents.validate_catalog(catalog)
    if catalog_errors:
        return ["template catalog is invalid: " + "; ".join(catalog_errors)]
    entries = [
        entry
        for entry in catalog["templates"]
        if entry["template_id"] == record.get("selected_template")
    ]
    if len(entries) != 1:
        return ["selected_template is undeclared in the controller-owned catalog"]
    entry = entries[0]
    expected = {
        "family": entry["family"],
        "selected_template": entry["template_id"],
        "template_catalog_sha256": catalog["catalog_sha256"],
        "requested_model_tier": entry["requested"]["model_tier"],
        "requested_effort": entry["requested"]["effort"],
        "resolved_model": entry["resolved"]["model"],
        "resolved_effort": entry["resolved"]["effort"],
    }
    for field, value in expected.items():
        if record.get(field) != value:
            return ["template identity %s does not match the catalog" % field]
    # Effective settings are independent observations. Null means not observed.
    if not all(field in record for field in ("effective_model", "effective_effort")):
        return ["effective model and effort must be explicit, using null when unknown"]
    return []


def validate_brief(record, catalog=None):
    """Validate a brief, requiring complete catalog identity for version 2."""
    errors = Validator(SCHEMAS / "brief.schema.json").validate(record)
    if errors:
        return errors
    if record.get("schema_version", 1) == 2:
        errors = _validate_template_identity(record, catalog)
        if errors:
            return errors
        if record.get("role") != record.get("family"):
            return ["brief role does not match its template family"]
    return []


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
    if not isinstance(controller_principal, str) or not controller_principal.startswith(
        "controller:"
    ):
        return ["controller principal is not a controller identity"]
    if record["captured_by"] != controller_principal:
        return ["envelope captured_by does not match the trusted controller"]

    worker_route = record["from"].startswith("worker:") or record["to"].startswith("worker:")
    if worker_route:
        if not all(field in record for field in _TEMPLATE_IDENTITY_FIELDS):
            return [
                "worker envelope requires complete template identity and explicit effective settings"
            ]
        if any(
            record.get(field) is None
            for field in (
                "family",
                "selected_template",
                "template_catalog_sha256",
                "requested_model_tier",
                "requested_effort",
                "resolved_model",
            )
        ):
            return ["worker envelope requires non-null requested and resolved identity"]
        if (
            record["from"].startswith("worker:")
            and record["from"] != "worker:" + record["selected_template"]
        ):
            return ["worker envelope sender does not match selected_template"]
        if (
            record["to"].startswith("worker:")
            and record["to"] != "worker:" + record["selected_template"]
        ):
            return ["worker envelope recipient does not match selected_template"]
    elif any(record.get(field) is not None for field in _TEMPLATE_IDENTITY_FIELDS):
        return ["run-level or orchestrator envelope must use explicit null template identity"]

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
        return [
            "invalid envelope route %s -> %s for %s"
            % (record["from"], record["to"], record["kind"])
        ]
    return []


def validate_attempt(record, template_catalog):
    """Validate one attempt against the controller's declared template catalog."""
    errors = validate_record("attempt", record)
    if errors:
        return errors
    return _validate_template_identity(record, template_catalog)


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
    """Bind a captured return to controller-owned dispatch and attempt state."""
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
    dispatch_id = expected_attempt.get("dispatched_envelope_id")
    if not isinstance(dispatch_id, str) or not dispatch_id:
        return ["expected attempt lacks a controller-owned dispatched envelope id"]
    if record["reply_to"] != dispatch_id:
        return ["envelope reply_to does not identify the dispatched task"]
    selected_template = expected_attempt.get("selected_template")
    if not isinstance(selected_template, str) or not selected_template:
        return ["expected attempt lacks a controller-owned selected template"]
    if record.get("selected_template") != selected_template:
        return ["envelope selected_template does not match the dispatched attempt"]
    for field in _TEMPLATE_IDENTITY_FIELDS:
        if record.get(field) != expected_attempt.get(field):
            return ["envelope template identity %s does not match the dispatched attempt" % field]
    return []


def validate_outcome(
    record, controller_principal=None, captured_evidence_refs=None, template_catalogs=None
):
    """Validate v2 outcome evidence against controller-owned capture context.

    The caller must supply trusted controller context for accepted outcomes;
    this offline validator does not authenticate that context itself.
    """
    errors = validate_record("outcome", record)
    if errors:
        return errors
    outcome = record["outcome"]
    selection_by_attempt = {item["attempt_id"]: item for item in record["template_selections"]}
    if len(selection_by_attempt) != len(record["template_selections"]):
        return ["outcome template selections must have unique attempt ids"]
    if outcome == "accepted" and not set(record.get("validated_attempt_refs", ())) <= set(
        selection_by_attempt
    ):
        return ["accepted outcome requires catalog identity for every validated attempt"]
    if template_catalogs is not None:
        for selection in record["template_selections"]:
            catalog = template_catalogs.get(selection["template_catalog_sha256"])
            errors = _validate_template_identity(selection, catalog)
            if errors:
                return ["outcome template selection is invalid: " + "; ".join(errors)]
    if outcome == "accepted":
        if not record.get("validated_attempt_refs"):
            return ["accepted outcome requires validated attempt references"]
        if not record.get("orchestrator_decision_refs"):
            return ["accepted outcome requires orchestrator decision references"]
        if not record.get("execution_evidence"):
            return ["accepted outcome requires concrete execution evidence"]
        if not isinstance(controller_principal, str) or not controller_principal.startswith(
            "controller:"
        ):
            return ["accepted outcome requires trusted controller capture context"]
        if not isinstance(captured_evidence_refs, (set, frozenset, list, tuple)):
            return ["accepted outcome requires controller-owned captured evidence references"]
        for evidence in record["execution_evidence"]:
            if evidence["captured_by"] != controller_principal:
                return ["execution evidence captured_by does not match the trusted controller"]
            if evidence["evidence_ref"] not in captured_evidence_refs:
                return ["execution evidence reference is not in controller-owned captured evidence"]
            if not evidence["command"].strip() or not evidence["output"].strip():
                return ["execution evidence requires a concrete command and output"]
    if outcome == "blocked":
        if not record.get("blocked_reason"):
            return ["blocked outcome requires a reason"]
        if not record.get("question_or_failure_refs"):
            return ["blocked outcome requires question or failure evidence references"]
    return []


def valid_preflight(
    run_id, host_id, workspace_fingerprint, configuration_fingerprint, principal_id
):
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
