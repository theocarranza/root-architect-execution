"""Offline checks for the Task 2 capability vocabulary."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import render_agents
import validate_interfaces


class RuntimeCapabilityTests(unittest.TestCase):
    def test_legacy_false_is_unknown_not_unsupported(self):
        claim = render_agents.normalize_capability({"supported": False, "verified": "sample"})
        self.assertEqual("unknown", claim["availability"])

    def test_documentation_only_is_not_host_enforcement(self):
        problems = validate_interfaces.capability_semantic_errors(
            {
                "availability": "supported",
                "enforcement": "host",
                "execution_surface": "plugin",
                "evidence": [{"kind": "documentation", "reference": "vendor docs"}],
            },
            "readonly",
        )
        self.assertTrue(problems)

    def test_live_host_evidence_can_support_host_enforcement(self):
        problems = validate_interfaces.capability_semantic_errors(
            {
                "availability": "supported",
                "enforcement": "host",
                "execution_surface": "session",
                "evidence": [
                    {"kind": "live-observation", "reference": "probe", "surface": "session"}
                ],
            },
            "readonly",
        )
        self.assertEqual([], problems)

    def test_contradictory_evidence_is_rejected(self):
        problems = validate_interfaces.capability_semantic_errors(
            {
                "availability": "supported",
                "enforcement": "host",
                "execution_surface": "session",
                "evidence": [
                    {"kind": "live-observation", "reference": "yes", "surface": "session"},
                    {"kind": "contradiction", "reference": "no", "surface": "session"},
                ],
            },
            "readonly",
        )
        self.assertTrue(problems)

    def test_unknown_nesting_is_not_supported(self):
        self.assertFalse(
            validate_interfaces.can_depend_on_capability(
                {"availability": "unknown", "enforcement": "unknown"}
            )
        )

    def test_alias_collapse_is_disclosed(self):
        aliases = {"cheap": "same", "mid": "same", "strong": "strong"}
        self.assertTrue(validate_interfaces.model_effort_alias_collapse(aliases))

    def test_plugin_evidence_does_not_prove_session(self):
        problems = validate_interfaces.capability_semantic_errors(
            {
                "availability": "supported",
                "enforcement": "host",
                "execution_surface": "session",
                "evidence": [
                    {"kind": "live-observation", "reference": "plugin run", "surface": "plugin"}
                ],
            },
            "readonly",
        )
        self.assertTrue(problems)
