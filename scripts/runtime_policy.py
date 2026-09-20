"""Fail-closed admission for every legacy runtime mutation.

The old preflight JSON is a readable historical artifact.  It is not an
authorization token: only a record bound to this exact controller session,
workspace, configuration, catalog, and selected transport can admit a write.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


PREFLIGHT_SUBDIR = Path(".root-architect") / "preflight"
IDENTITY_FIELDS = (
    "run_id", "host_id", "workspace", "workspace_fingerprint",
    "controller_session_id", "catalog_digest", "configuration_fingerprint",
)
REQUIRED_CAPABILITIES = (
    "delegation_available", "controller_selection_enforced",
    "registered_agents", "hook_registration_enforced",
)
MAX_EVIDENCE_AGE = timedelta(minutes=5)


class AdmissionError(Exception):
    """A mutation lacks current, transport-backed admission."""


def unsupported_direct_mutation(context=None):
    """Direct scripts share a writable user identity with workers.

    They therefore cannot turn arguments, files, or local evidence into an
    authenticated controller identity.  This remains blocked until a protected
    controller service owns credentials and state outside worker reach.
    """
    _fail(
        context or {},
        "unsupported_boundary: direct compatibility mutation has no authenticated controller identity"
    )


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _recovery(context):
    host = context.get("host_id", "the selected host") if isinstance(context, dict) else "the selected host"
    run = context.get("run_id", "<run-id>") if isinstance(context, dict) else "<run-id>"
    workspace = context.get("workspace", "<workspace>") if isinstance(context, dict) else "<workspace>"
    return (
        "Recovery for %s run %s in %s: use a protected authenticated controller service for "
        "that selected host; direct compatibility commands cannot authorize mutation."
    ) % (host, run, workspace)


def _fail(context, detail):
    raise AdmissionError("admission blocked: %s. %s" % (detail, _recovery(context)))


def _recent_timestamp(context, value, label):
    if not _nonempty(value):
        _fail(context, "missing %s" % label)
    try:
        observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(context, "%s is not an ISO-8601 timestamp" % label)
    if observed_at.tzinfo is None:
        _fail(context, "%s has no timezone" % label)
    now = datetime.now(timezone.utc)
    if observed_at > now + timedelta(minutes=1) or now - observed_at > MAX_EVIDENCE_AGE:
        _fail(context, "%s is stale or from the future" % label)


def validate_context(context):
    """Validate caller-supplied identity and live transport observations.

    This accepts evidence only when it identifies the selected transport.  A
    model's report, an agent file, or a hook file is useful diagnosis but does
    not establish that the host loaded or enforced it.
    """
    if not isinstance(context, dict):
        _fail({}, "missing admission identity")
    for field in IDENTITY_FIELDS:
        if not _nonempty(context.get(field)):
            _fail(context, "missing explicit %s" % field.replace("_", " "))
    try:
        resolved = str(Path(context["workspace"]).resolve())
    except (OSError, RuntimeError):
        _fail(context, "workspace cannot be resolved")
    if context["workspace"] != resolved:
        _fail(context, "workspace is not its resolved explicit identity")
    evidence = context.get("capability_evidence")
    if not isinstance(evidence, dict):
        _fail(context, "missing selected transport capability evidence")
    if evidence.get("source") != "selected_transport" or not _nonempty(evidence.get("transport_id")):
        _fail(context, "capability evidence is not from the selected transport")
    _recent_timestamp(context, evidence.get("observed_at"), "selected transport observed_at")
    capabilities = evidence.get("capabilities")
    if not isinstance(capabilities, dict):
        _fail(context, "selected transport capability evidence has no capabilities object")
    for capability in REQUIRED_CAPABILITIES:
        if capabilities.get(capability) is not True:
            _fail(context, "selected transport does not prove %s" % capability.replace("_", " "))
    return True


def admission_record(context, checked_at="1970-01-01T00:00:00Z"):
    validate_context(context)
    return {
        "admission_version": 1,
        **{field: context[field] for field in IDENTITY_FIELDS},
        "capability_evidence": context["capability_evidence"],
        "passed": True,
        "checked_at": checked_at,
    }


def record_path(workspace, run_id):
    return Path(workspace) / PREFLIGHT_SUBDIR / ("%s.json" % run_id)


def write_admission(workspace, context, checked_at="1970-01-01T00:00:00Z"):
    unsupported_direct_mutation(context)


def admit(workspace, context):
    """Refuse unless the on-disk record exactly binds this mutation context."""
    validate_context(context)
    if str(Path(workspace).resolve()) != context["workspace"]:
        _fail(context, "admission workspace does not match the mutation workspace")
    path = record_path(workspace, context["run_id"])
    if not path.is_file():
        _fail(context, "no admission record exists for this run")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _fail(context, "admission record cannot be read (%s)" % exc)
    if not isinstance(record, dict):
        _fail(context, "admission record is not an object")
    if record.get("passed") is not True:
        _fail(context, "admission record passed is not the literal boolean true")
    if record.get("admission_version") != 1:
        _fail(context, "admission record has no supported admission version")
    for field in IDENTITY_FIELDS:
        if record.get(field) != context[field]:
            _fail(context, "admission record %s does not match this mutation" % field.replace("_", " "))
    if record.get("capability_evidence") != context["capability_evidence"]:
        _fail(context, "admission record capability evidence does not match this mutation")
    # Revalidate evidence stored on disk; a truthy string or forged field never
    # becomes acceptable merely because the outer record matched.
    validate_context(record)
    _recent_timestamp(context, record.get("checked_at"), "admission checked_at")
    return []
