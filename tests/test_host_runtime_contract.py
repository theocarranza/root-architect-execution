"""The common bridge never turns an absent host operation into success."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from host_runtime import HostRuntimeBridge, validate_result


class HostRuntimeContractTests(unittest.TestCase):
    def test_missing_operation_is_specific_structured_error(self):
        result = HostRuntimeBridge({}).start("parent", "template", "envelope", "key")
        self.assertEqual("unsupported_host_capability", result["status"])
        self.assertEqual("start", result["capability"])

    def test_events_are_ordered_and_cursor_is_explicit(self):
        bridge = HostRuntimeBridge({"events": lambda cursor: {
            "events": [{"source": "host", "child": "unknown", "adapter_dedup_key": "d1"}],
            "next_cursor": None,
        }})
        result = bridge.events(None)
        self.assertEqual([], validate_result("events", result))
        self.assertNotIn("provider_event_id", result["events"][0])

    def test_provider_event_id_and_dedup_key_are_distinct(self):
        errors = validate_result("events", {"events": [{"source": "host", "child": "unknown",
            "provider_event_id": "p1", "adapter_dedup_key": "d1"}], "next_cursor": "2"})
        self.assertEqual([], errors)

    def test_invalid_success_is_converted_to_contract_error(self):
        bridge = HostRuntimeBridge({"status": lambda thread: {}})
        result = bridge.status("thread")
        self.assertEqual("invalid_host_result", result["status"])

    def test_each_non_event_operation_rejects_empty_ok_payload(self):
        calls = {
            "probe": ({},),
            "start": ("parent", "template", "envelope", "key"),
            "status": ("thread",),
            "follow_up": ("thread", "answer"),
            "cancel": ("thread",),
        }
        for operation, arguments in calls.items():
            with self.subTest(operation=operation):
                bridge = HostRuntimeBridge({operation: lambda *args: {"status": "ok"}})
                result = getattr(bridge, operation)(*arguments)
                self.assertEqual("invalid_host_result", result["status"])
