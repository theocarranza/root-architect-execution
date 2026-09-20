"""Strict return parsing and evidence-schema regressions."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_return  # noqa: E402
import runtime_contract  # noqa: E402
from jsonschema_mini import Validator  # noqa: E402


def report(**changes):
    value = {
        "task": "T7",
        "attempt": 1,
        "model": "observed-model",
        "effort": "observed-effort",
        "status": "DONE",
        "files_written": [],
        "files_modified": [],
        "tests": {
            "red": {"command": "test red", "counts": "1 failing"},
            "green": {"command": "test green", "counts": "1 passing"},
        },
        "diff_summary": "changed only task files",
        "notes": "",
    }
    value.update(changes)
    return value


class RuntimeReturnTests(unittest.TestCase):
    def test_strict_contract_rejects_extra_prose_multiple_fences_and_non_object_json(self):
        block = json.dumps(report())
        for raw in (
            "extra prose\n```json\n%s\n```" % block,
            "```json\n%s\n```\nextra prose" % block,
            "```json\n%s\n```\n```json\n%s\n```" % (block, block),
            "```json\n[]\n```",
        ):
            with self.subTest(raw=raw[:20]):
                payload, problem = check_return.extract_strict(raw.encode("utf-8"), "utf-8")
                self.assertIsNone(payload)
                self.assertIsNotNone(problem)

    def test_verbatim_capture_does_not_normalize_newlines_or_trim_and_keeps_metadata_separate(self):
        raw = b"```json\r\n{}\r\n```\r\n"
        captured = check_return.capture_provider_return(
            raw, "utf-8", {"provider_event": "e1", "token_count": 4}
        )
        self.assertEqual(raw, captured["body"])
        self.assertEqual("utf-8", captured["encoding"])
        self.assertEqual({"provider_event": "e1", "token_count": 4}, captured["provider_metadata"])

    def test_observed_effective_configuration_rejects_worker_claims(self):
        errors = check_return.cross_field_errors(
            report(model="worker-claim", effort="high"),
            "implementer",
            "T7",
            1,
            observed_config={"model": "observed-model", "effort": "observed-effort"},
        )
        self.assertTrue(any("model" in error for error in errors), errors)
        self.assertTrue(any("effort" in error for error in errors), errors)

    def test_governed_cli_requires_captured_identity_and_retains_malformed_raw_bytes(self):
        temp = Path(tempfile.mkdtemp(prefix="runtime-returns-"))
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        source = temp / "return.bin"
        raw = b"bad\xff return"
        source.write_bytes(raw)
        retained = temp / "retained"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "check_return.py"),
                "--role",
                "implementer",
                "--file",
                str(source),
                "--governed-envelope-id",
                "captured-env-1",
                "--raw-retain-dir",
                str(retained),
            ],
            capture_output=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(raw, (retained / "captured-env-1.raw").read_bytes())
        self.assertIn(b"unsupported", result.stderr.lower())

    def test_file_validation_is_rejected_by_default_and_legacy_mode_is_explicit(self):
        temp = Path(tempfile.mkdtemp(prefix="runtime-return-legacy-"))
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        source = temp / "return.txt"
        source.write_text("```json\n%s\n```\n" % json.dumps(report()), encoding="utf-8")
        command = [
            sys.executable,
            str(ROOT / "scripts" / "check_return.py"),
            "--role",
            "implementer",
            "--file",
            str(source),
        ]
        default = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(0, default.returncode)
        self.assertIn("governed", default.stderr)
        legacy = subprocess.run(command + ["--legacy-file"], capture_output=True, text=True)
        self.assertEqual(0, legacy.returncode, legacy.stderr)

    def test_schema_versions_reject_boolean_values(self):
        envelope = {
            "schema_version": True,
            "run_id": "run-1",
            "seq": 1,
            "kind": "task",
            "from": "orchestrator",
            "to": "worker:implementer",
            "persisted_by": "orchestrator",
            "created_at": "now",
            "body_sha256": "a" * 64,
        }
        outcome = {
            "schema_version": True,
            "run_id": "run-1",
            "outcome": "blocked",
            "rationale": "x",
        }
        envelope_errors = Validator(ROOT / "schemas" / "envelope.schema.json").validate(envelope)
        outcome_errors = Validator(ROOT / "schemas" / "orchestrator-outcome.schema.json").validate(
            outcome
        )
        self.assertTrue(
            any("expected type integer" in error for error in envelope_errors), envelope_errors
        )
        self.assertTrue(
            any("expected type integer" in error for error in outcome_errors), outcome_errors
        )

    def test_outcome_requires_command_output_exit_and_tested_tree_evidence(self):
        outcome = {
            "schema_version": 2,
            "run_id": "run-1",
            "outcome": "accepted",
            "rationale": "validated",
            "validated_attempt_refs": ["attempt-1"],
            "orchestrator_decision_refs": ["decision-1"],
            "execution_evidence": [
                {
                    "evidence_ref": "env-command-1",
                    "captured_by": "controller:local-1",
                    "capture_source": "controller",
                    "command": "python3 -m unittest tests.test_runtime_returns",
                    "output": "ok",
                    "exit_status": 0,
                    "tested_tree_fingerprint": "a" * 64,
                }
            ],
        }
        self.assertEqual(
            [],
            runtime_contract.validate_outcome(outcome, "controller:local-1", {"env-command-1"}),
        )
        outcome["execution_evidence"][0].pop("output")
        self.assertTrue(runtime_contract.validate_outcome(outcome))


if __name__ == "__main__":
    unittest.main()
