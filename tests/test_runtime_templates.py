"""Contracts for family-contained, fixed worker template variants."""

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_agents  # noqa: E402


def by_id_model(catalog, template_id):
    return next(entry for entry in catalog["templates"] if entry["template_id"] == template_id)[
        "resolved"
    ]["model"]


class RuntimeTemplateTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            hasattr(render_agents, "select_catalog"),
            "renderer has no shared catalog selection function",
        )

    def test_catalog_has_named_variants_and_fixed_legacy_aliases(self):
        catalog = render_agents.select_catalog("codex")
        by_id = {entry["template_id"]: entry for entry in catalog["templates"]}

        for template_id, family, model, effort in (
            ("impl-executor-cheap", "implementer", "cheap", "low"),
            ("impl-executor-mid", "implementer", "mid", "medium"),
            ("impl-executor-strong", "implementer", "strong", "high"),
            ("spec-validator-cheap", "spec-validator", "cheap", "medium"),
            ("spec-validator-mid", "spec-validator", "mid", "medium"),
            ("spec-validator-strong", "spec-validator", "strong", "high"),
            ("quality-validator-cheap", "quality-validator", "cheap", "medium"),
            ("quality-validator-mid", "quality-validator", "mid", "medium"),
            ("quality-validator-strong", "quality-validator", "strong", "high"),
        ):
            self.assertEqual(family, by_id[template_id]["family"])
            self.assertEqual(model, by_id[template_id]["requested"]["model_tier"])
            self.assertEqual(effort, by_id[template_id]["requested"]["effort"])
            self.assertEqual(
                "gpt-5.6-" + {"cheap": "luna", "mid": "terra", "strong": "sol"}[model],
                by_id[template_id]["resolved"]["model"],
            )
            self.assertEqual(effort, by_id[template_id]["resolved"]["effort"])

        for alias, target in (
            ("impl-executor", "impl-executor-cheap"),
            ("spec-validator", "spec-validator-cheap"),
            ("quality-validator", "quality-validator-cheap"),
        ):
            self.assertEqual(target, by_id[alias]["alias_of"])
            self.assertEqual(by_id[target]["resolved"], by_id[alias]["resolved"])
            self.assertEqual(by_id[target]["permissions"], by_id[alias]["permissions"])

    def test_catalog_hash_is_canonical_and_selection_rejects_undeclared_templates(self):
        catalog = render_agents.select_catalog("codex")
        serialized = render_agents.canonical_catalog_bytes(catalog)
        self.assertEqual(
            hashlib.sha256(serialized).hexdigest(), render_agents.catalog_sha256(catalog)
        )
        with self.assertRaisesRegex(ValueError, "undeclared"):
            render_agents.select_template(catalog, "impl-executor-very-strong")

    def test_escalation_requires_reason_and_real_host_tier_change(self):
        codex = render_agents.select_catalog("codex")
        with self.assertRaisesRegex(ValueError, "reason is required"):
            render_agents.select_template(codex, "impl-executor-mid", "impl-executor-cheap")
        selected = render_agents.select_template(
            codex, "impl-executor-mid", "impl-executor-cheap", " prior attempt failed "
        )
        self.assertEqual("impl-executor-mid", selected["template_id"])
        self.assertEqual("impl-executor-cheap", selected["escalated_from"])
        self.assertEqual("prior attempt failed", selected["escalation_reason"])

        gemini = render_agents.select_catalog("gemini")
        with self.assertRaisesRegex(ValueError, "collapsed model tiers"):
            render_agents.select_template(
                gemini, "impl-executor-mid", "impl-executor-cheap", "prior attempt failed"
            )
        with self.assertRaisesRegex(ValueError, "initial worker selection"):
            render_agents.select_template(gemini, "impl-executor-strong")
        strong = render_agents.select_template(
            gemini, "impl-executor-strong", "impl-executor-cheap", "prior attempt failed"
        )
        self.assertEqual("flash", by_id_model(gemini, "impl-executor-cheap"))
        self.assertEqual("pro", strong["resolved"]["model"])
        self.assertIsNone(strong["resolved"]["effort"])
        with self.assertRaisesRegex(ValueError, "initial worker selection"):
            render_agents.select_template(gemini, "impl-executor-strong")
        strong = render_agents.select_template(
            gemini, "impl-executor-strong", "impl-executor-cheap", "prior attempt failed"
        )
        self.assertEqual("flash", by_id_model(gemini, "impl-executor-cheap"))
        self.assertEqual("pro", strong["resolved"]["model"])
        self.assertIsNone(strong["resolved"]["effort"])

    def test_catalog_integrity_rejects_permission_changes_and_invalid_hash(self):
        catalog = render_agents.select_catalog("codex")
        catalog["templates"][0]["permissions"]["mutation"] = "read-only"
        self.assertTrue(render_agents.validate_catalog(catalog))
        catalog = render_agents.select_catalog("codex")
        catalog["catalog_sha256"] = "not-a-digest"
        self.assertTrue(render_agents.validate_catalog(catalog))

    def test_named_codex_agent_files_and_catalog_share_the_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(
                hasattr(render_agents, "render_host"),
                "renderer has no shared host and catalog materializer",
            )
            render_agents.render_host("codex", directory)
            target = Path(directory)
            catalog = json.loads((target / "template-catalog.json").read_text())
            by_id = {entry["template_id"]: entry for entry in catalog["templates"]}
            for template_id in (
                "impl-executor-cheap",
                "impl-executor-mid",
                "impl-executor-strong",
                "spec-validator-cheap",
                "spec-validator-mid",
                "spec-validator-strong",
                "quality-validator-cheap",
                "quality-validator-mid",
                "quality-validator-strong",
            ):
                text = (target / (template_id + ".toml")).read_text()
                self.assertIn('name = "' + template_id + '"', text)
                self.assertIn('model = "' + by_id[template_id]["resolved"]["model"] + '"', text)
                self.assertIn(
                    'model_reasoning_effort = "' + by_id[template_id]["resolved"]["effort"] + '"',
                    text,
                )

    def test_codex_installer_records_catalog_and_materialized_file_hashes(self):
        spec = importlib.util.spec_from_file_location(
            "codex_install", ROOT / "adapters/codex/install.py"
        )
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as directory:
            target, names = installer.materialize(
                Path(directory) / "agents", Path(directory) / "plugin root"
            )
            marker = json.loads((target / ".root-architect-execution-codex.json").read_text())
            self.assertEqual(2, marker["version"])
            self.assertEqual(set(names), set(marker["file_sha256"]))
            self.assertIn("template-catalog.json", names)
            catalog = json.loads((target / "template-catalog.json").read_text())
            self.assertEqual(catalog["catalog_sha256"], marker["catalog_sha256"])
            for filename, digest in marker["file_sha256"].items():
                self.assertEqual(
                    digest, hashlib.sha256((target / filename).read_bytes()).hexdigest()
                )

    def test_non_escalating_collapsed_host_tiers_are_disclosed(self):
        catalog = render_agents.select_catalog("gemini")
        entries = {entry["template_id"]: entry for entry in catalog["templates"]}
        self.assertTrue(entries["impl-executor-mid"]["collapsed_model_tier"])
        self.assertTrue(entries["impl-executor-mid"]["collapsed_from_previous"])
        self.assertIsNone(entries["impl-executor-cheap"]["resolved"]["effort"])

    def test_every_declared_host_gets_schema_valid_catalog(self):
        for host_path in sorted((ROOT / "hosts").glob("*.json")):
            catalog = render_agents.select_catalog(host_path.stem)
            self.assertEqual([], render_agents.validate_catalog(catalog), host_path.stem)

    def test_brief_can_record_unknown_effective_settings_without_invention(self):
        from jsonschema_mini import Validator

        brief = {
            "schema_version": 2,
            "run_id": "run-1",
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "selected_template": "impl-executor-cheap",
            "template_catalog_sha256": "a" * 64,
            "family": "implementer",
            "requested_model_tier": "cheap",
            "requested_effort": "low",
            "resolved_model": "gpt-5.6-luna",
            "resolved_effort": "low",
            "effective_model": None,
            "effective_effort": None,
            "task": "Implement the change",
            "attempt": 1,
            "max_attempts": 3,
            "role": "implementer",
            "model": "gpt-5.6-luna",
            "effort": "low",
            "read_paths": [],
            "write_paths": [],
            "acceptance": [{"command": "true", "expect": "success"}],
            "constraints": ["Stay within the assigned files"],
            "owner_owned_paths": [],
            "expected_result": "A focused implementation",
        }
        self.assertEqual([], Validator(ROOT / "schemas/brief.schema.json").validate(brief))

        catalog = render_agents.select_catalog("codex")
        catalog["templates"][0]["template_id"] = "dynamic-worker"
        catalog["catalog_sha256"] = render_agents.catalog_sha256(catalog)
        with self.assertRaisesRegex(ValueError, "fixed role declarations"):
            render_agents.select_template(catalog, "dynamic-worker")


if __name__ == "__main__":
    unittest.main()
