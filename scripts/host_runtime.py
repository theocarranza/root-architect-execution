"""Small, offline contract for host-specific runtime bridges.

Adapters implement handlers; this module neither probes nor invokes a host.
It makes the absence of a host operation observable and prevents an adapter
from returning an unvalidated empty object as if work had succeeded.
"""

OPERATIONS = ("probe", "start", "status", "follow_up", "cancel", "events")

# A success must identify what the controller can act on next.  These are
# intentionally small portable records: host-specific observations remain in
# adapter-defined payloads, but no operation can acknowledge success with an
# empty object.
SUCCESS_FIELDS = {
    "probe": {"observations": dict},
    "start": {"provider_thread_id": str},
    "status": {"provider_thread_id": str, "activity": str},
    "follow_up": {"provider_thread_id": str, "accepted": bool},
    "cancel": {"provider_thread_id": str, "cancelled": bool},
}


def unsupported(capability):
    return {"status": "unsupported_host_capability", "capability": capability}


def validate_result(operation, result):
    """Return contract errors, rather than raising on an adapter's raw JSON."""
    if not isinstance(result, dict):
        return ["%s result must be an object" % operation]
    if result.get("status") == "unsupported_host_capability":
        return (
            []
            if result.get("capability") == operation
            else ["unsupported result must name capability %s" % operation]
        )
    if operation == "events":
        allowed = {"status", "events", "next_cursor"}
        unexpected = set(result) - allowed
        if unexpected:
            return ["events result has unknown fields: %s" % sorted(unexpected)]
        events = result.get("events")
        if not isinstance(events, list):
            return ["events result must contain an ordered events list"]
        if "next_cursor" not in result or not isinstance(result["next_cursor"], (str, type(None))):
            return ["events result must contain string-or-null next_cursor"]
        errors = []
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                errors.append("events[%d] must be an object" % index)
                continue
            if event.get("source") not in {"host", "adapter", "unknown"}:
                errors.append("events[%d].source must be explicit" % index)
            if event.get("child") not in {"host", "adapter", "unknown"}:
                errors.append("events[%d].child must be explicit" % index)
            if (
                not isinstance(event.get("adapter_dedup_key"), str)
                or not event["adapter_dedup_key"]
            ):
                errors.append("events[%d].adapter_dedup_key is required" % index)
            if "provider_event_id" in event and not isinstance(
                event["provider_event_id"], (str, type(None))
            ):
                errors.append("events[%d].provider_event_id must be string-or-null" % index)
        return errors
    if result.get("status") != "ok":
        return ["%s result must explicitly have status 'ok'" % operation]
    errors = []
    for field, expected_type in SUCCESS_FIELDS[operation].items():
        value = result.get(field)
        if not isinstance(value, expected_type) or (expected_type is str and not value):
            errors.append("%s result requires %s" % (operation, field))
    return errors


class HostRuntimeBridge:
    """Validate calls to supplied adapter handlers without making live calls itself."""

    def __init__(self, handlers):
        self.handlers = dict(handlers)

    def _call(self, operation, *args):
        handler = self.handlers.get(operation)
        if handler is None:
            return unsupported(operation)
        try:
            result = handler(*args)
        except Exception as exc:  # adapter errors are data for the controller
            return {
                "status": "invalid_host_result",
                "capability": operation,
                "error": "%s: %s" % (type(exc).__name__, exc),
            }
        if validate_result(operation, result):
            return {"status": "invalid_host_result", "capability": operation}
        return result

    def probe(self, launch_context):
        return self._call("probe", launch_context)

    def start(self, parent_thread_id, template_id, task_envelope_id, idempotency_key):
        return self._call("start", parent_thread_id, template_id, task_envelope_id, idempotency_key)

    def status(self, provider_thread_id):
        return self._call("status", provider_thread_id)

    def follow_up(self, provider_thread_id, answer_envelope_id):
        return self._call("follow_up", provider_thread_id, answer_envelope_id)

    def cancel(self, provider_thread_id):
        return self._call("cancel", provider_thread_id)

    def events(self, cursor=None):
        return self._call("events", cursor)
