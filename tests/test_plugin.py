"""Tests for the root-architect-execution plugin.

Scope: enough to prove each part works and that the guards actually refuse the
things the skill says they refuse. Not an exhaustive JSON Schema conformance
suite — the mini validator is checked through the contracts that use it.

    python3 -m unittest discover -s tests -t .
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(SCRIPTS))

from jsonschema_mini import Validator  # noqa: E402
from dispatch_state import DispatchStateError  # noqa: E402
import render_agents  # noqa: E402


def run(script, args, stdin=None):
    return subprocess.run(
        [sys.executable, str(script)] + args,
        input=stdin, capture_output=True, text=True)


def valid_brief(**overrides):
    brief = {
        "task": "Task 3 — reject a tampered middle result",
        "attempt": 1,
        "max_attempts": 3,
        "role": "implementer",
        "model": "haiku",
        "effort": "low",
        "read_paths": ["scripts/envelope.py"],
        "write_paths": ["scripts/envelope.py"],
        "acceptance": [{"command": "python3 -m unittest x", "expect": "19 passed"}],
        "constraints": ["Reachability: only envelope.py changes."],
        "owner_owned_paths": ["AI_Codex/"],
        "expected_result": "A tampered payload is rejected.",
    }
    brief.update(overrides)
    return brief


def valid_report(**overrides):
    report = {
        "task": "T", "attempt": 1, "model": "haiku", "effort": "low",
        "status": "DONE", "files_written": [], "files_modified": ["a.py"],
        "tests": {
            "red": {"command": "c", "counts": "1 failed"},
            "green": {"command": "c", "counts": "19 passed"},
        },
        "diff_summary": "d", "notes": "",
    }
    report.update(overrides)
    return report


def valid_verdict(**overrides):
    verdict = {"task": "T", "attempt": 1, "role": "spec-validator",
               "status": "PASS", "findings": [], "commands_rerun": []}
    verdict.update(overrides)
    return verdict


class MiniValidatorTests(unittest.TestCase):
    """The validator has to actually reject things, or the schemas are decor."""

    def setUp(self):
        self.brief = Validator(ROOT / "schemas" / "brief.schema.json")

    def test_accepts_a_valid_brief(self):
        self.assertEqual(self.brief.validate(valid_brief()), [])

    def test_rejects_missing_required_property(self):
        brief = valid_brief()
        del brief["constraints"]
        self.assertTrue(any("constraints" in e
                            for e in self.brief.validate(brief)))

    def test_rejects_unknown_property(self):
        errors = self.brief.validate(valid_brief(surprise=1))
        self.assertTrue(any("surprise" in e for e in errors))

    def test_rejects_attempt_above_the_cap(self):
        self.assertTrue(any("maximum" in e
                            for e in self.brief.validate(valid_brief(attempt=4))))

    def test_rejects_absolute_and_escaping_write_paths(self):
        for bad in ("/etc/passwd", "../outside.py"):
            with self.subTest(path=bad):
                errors = self.brief.validate(valid_brief(write_paths=[bad]))
                self.assertTrue(any("pattern" in e for e in errors), bad)

    def test_anyof_accepts_both_effort_forms(self):
        for effort in ("high", "not settable on this host"):
            with self.subTest(effort=effort):
                self.assertEqual(
                    self.brief.validate(valid_brief(effort=effort)), [])

    def test_anyof_rejects_an_invented_effort_level(self):
        self.assertNotEqual(self.brief.validate(valid_brief(effort="turbo")), [])

    def test_boolean_is_not_an_integer(self):
        self.assertNotEqual(self.brief.validate(valid_brief(attempt=True)), [])


class RoleAndHostManifestTests(unittest.TestCase):

    def test_shipped_manifests_pass_the_capability_gate(self):
        result = run(SCRIPTS / "validate_roles.py", [])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gate_reports_inherited_host_manifests(self):
        result = run(SCRIPTS / "validate_roles.py", [])
        self.assertIn("inherited and unverified", result.stdout)

    def test_every_role_declares_all_four_axes(self):
        for _, role in render_agents.load_roles():
            with self.subTest(role=role["id"]):
                self.assertIn(role["model"]["default"], ("cheap", "mid", "strong"))
                self.assertIn(role["reasoning"]["default"],
                              ("low", "medium", "high", "xhigh", "max"))
                self.assertTrue(role["tools"]["allow"])
                self.assertIn(role["mutation"],
                              ("read-only", "read-and-run", "write-scoped"))

    def test_no_role_may_delegate(self):
        for _, role in render_agents.load_roles():
            self.assertNotIn("delegate", role["tools"]["allow"], role["id"])

    def test_read_only_role_granting_a_shell_fails_the_gate(self):
        """The contradiction the JSON Schema cannot see: both halves are valid."""
        path = ROOT / "roles" / "spec-validator.json"
        original = path.read_text(encoding="utf-8")
        broken = json.loads(original)
        broken["tools"]["allow"].append("run-commands")
        broken["tools"]["shell_purpose"] = "smuggled in"
        broken["tools"]["deny"].remove("run-commands")
        try:
            path.write_text(json.dumps(broken, indent=2) + "\n", encoding="utf-8")
            result = run(SCRIPTS / "validate_roles.py", [])
            self.assertEqual(result.returncode, 1)
            self.assertIn("read-only but grants run-commands", result.stderr)
        finally:
            path.write_text(original, encoding="utf-8")


class RenderTests(unittest.TestCase):

    def test_generated_claude_agents_declare_all_four_axes(self):
        for name in ("impl-executor", "spec-validator", "quality-validator"):
            with self.subTest(agent=name):
                text = (ROOT / "agents" / (name + ".md")).read_text(encoding="utf-8")
                head = text.split("---")[1]
                self.assertIn("model:", head)
                self.assertIn("effort:", head)
                self.assertIn("tools:", head)
                self.assertNotIn("inherit", head)

    def test_read_only_role_gets_no_write_or_shell_tool(self):
        head = (ROOT / "agents" / "spec-validator.md").read_text(
            encoding="utf-8").split("---")[1]
        tools = [line for line in head.splitlines() if line.startswith("tools:")][0]
        for forbidden in ("Edit", "Write", "Bash"):
            self.assertNotIn(forbidden, tools)

    def test_unenforceable_capability_becomes_a_disclosure(self):
        """Cursor cannot express a tool allowlist; the file must say so."""
        with tempfile.TemporaryDirectory() as tmp:
            run(SCRIPTS / "render_agents.py",
                ["--host", "cursor", "--out", tmp])
            text = (Path(tmp) / "spec-validator.md").read_text(encoding="utf-8")
        self.assertIn("not enforced", text)
        self.assertIn("## Enforcement", text)

    def test_host_that_enforces_read_only_says_so_in_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(SCRIPTS / "render_agents.py", ["--host", "codex", "--out", tmp])
            text = (Path(tmp) / "spec-validator.toml").read_text(encoding="utf-8")
        self.assertIn('sandbox_mode = "read-only"', text)
        self.assertIn("model_reasoning_effort", text)

    def test_check_detects_a_hand_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(SCRIPTS / "render_agents.py",
                ["--host", "claude-code", "--out", tmp])
            target = Path(tmp) / "impl-executor.md"
            target.write_text(target.read_text(encoding="utf-8")
                              .replace("model: haiku", "model: opus"),
                              encoding="utf-8")
            result = run(SCRIPTS / "render_agents.py",
                         ["--host", "claude-code", "--out", tmp, "--check"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("out of sync", result.stderr)


class CheckReturnTests(unittest.TestCase):

    def check(self, role, payload, extra=None, raw=None):
        body = raw if raw is not None else \
            "here you go\n\n```json\n%s\n```\n" % json.dumps(payload)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(body)
            path = fh.name
        return run(SCRIPTS / "check_return.py",
                   ["--role", role, "--file", path] + (extra or []))

    def test_accepts_a_well_formed_report(self):
        self.assertEqual(self.check("implementer", valid_report()).returncode, 0)

    def test_done_without_red_counts_is_rejected(self):
        report = valid_report()
        report["tests"]["red"] = None
        result = self.check("implementer", report)
        self.assertEqual(result.returncode, 1)
        self.assertIn("must carry observed RED counts", result.stderr)

    def test_pass_carrying_findings_is_rejected(self):
        verdict = valid_verdict(findings=[{
            "path": "a.py", "requirement": "r", "evidence": "e",
            "required_fix": "f"}])
        result = self.check("spec-validator", verdict)
        self.assertEqual(result.returncode, 1)
        self.assertIn("PASS cannot carry findings", result.stderr)

    def test_findings_carrying_none_is_rejected(self):
        result = self.check("spec-validator", valid_verdict(status="FINDINGS"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("must carry at least one finding", result.stderr)

    def test_spec_validator_that_ran_commands_is_rejected(self):
        verdict = valid_verdict(commands_rerun=[
            {"command": "pytest", "observed": "19 passed"}])
        result = self.check("spec-validator", verdict)
        self.assertEqual(result.returncode, 1)
        self.assertIn("review roles were combined", result.stderr)

    def test_quality_finding_without_a_failure_scenario_is_rejected(self):
        verdict = valid_verdict(role="quality-validator", status="FINDINGS",
                                findings=[{"path": "a.py", "requirement": "r",
                                           "evidence": "e", "required_fix": "f"}])
        result = self.check("quality-validator", verdict)
        self.assertEqual(result.returncode, 1)
        self.assertIn("failure_scenario", result.stderr)

    def test_role_mismatch_is_rejected(self):
        result = self.check("quality-validator", valid_verdict())
        self.assertEqual(result.returncode, 1)
        self.assertIn("root dispatched", result.stderr)

    def test_task_mismatch_is_rejected(self):
        result = self.check("implementer", valid_report(),
                            extra=["--task", "a different task"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("root dispatched", result.stderr)

    def test_prose_without_a_json_block_is_rejected(self):
        result = self.check("implementer", None,
                            raw="I finished the task and all tests pass.")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no fenced json block", result.stderr)

    def test_two_json_blocks_are_rejected(self):
        body = "```json\n{}\n```\nand also\n```json\n{}\n```\n"
        result = self.check("implementer", None, raw=body)
        self.assertEqual(result.returncode, 1)
        self.assertIn("return exactly one", result.stderr)


class DispatchStateTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write_brief(self, brief):
        path = self.workspace / "brief.json"
        path.write_text(json.dumps(brief), encoding="utf-8")
        return str(path)

    def open_dispatch(self, brief=None, run_id="20260907-task-3"):
        return run(SCRIPTS / "dispatch_state.py", [
            "open", "--workspace", str(self.workspace),
            "--brief", self.write_brief(brief or valid_brief()),
            "--run-id", run_id])

    def test_opens_and_reports_protected_paths(self):
        result = self.open_dispatch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scripts/envelope.py", result.stdout)

    def test_refuses_a_non_conformant_brief(self):
        brief = valid_brief()
        del brief["acceptance"]
        result = self.open_dispatch(brief)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not schema-conformant", result.stderr)

    def test_refuses_escalation_without_a_recorded_reason(self):
        result = self.open_dispatch(valid_brief(attempt=2))
        self.assertEqual(result.returncode, 1)
        self.assertIn("escalation_reason", result.stderr)

    def test_accepts_escalation_with_a_recorded_reason(self):
        result = self.open_dispatch(valid_brief(
            attempt=2, escalation_reason="attempt 1 left the tamper case unwritten"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refuses_a_second_concurrent_dispatch(self):
        self.open_dispatch()
        result = self.open_dispatch(run_id="20260907-task-4")
        self.assertEqual(result.returncode, 1)
        self.assertIn("One dependent task at a time", result.stderr)

    def test_close_frees_the_slot(self):
        self.open_dispatch()
        closed = run(SCRIPTS / "dispatch_state.py", [
            "close", "--workspace", str(self.workspace),
            "--run-id", "20260907-task-3", "--outcome", "accepted"])
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertEqual(self.open_dispatch(run_id="20260907-task-4").returncode, 0)

    def test_blocked_outcome_marks_the_dispatch_aborted(self):
        self.open_dispatch()
        run(SCRIPTS / "dispatch_state.py", [
            "close", "--workspace", str(self.workspace),
            "--run-id", "20260907-task-3", "--outcome", "blocked"])
        state = json.loads((self.workspace / ".root-architect" / "state"
                            / "dispatch-20260907-task-3.json").read_text())
        self.assertEqual(state["status"], "aborted")

    def test_active_reports_nothing_when_idle(self):
        result = run(SCRIPTS / "dispatch_state.py",
                     ["active", "--workspace", str(self.workspace)])
        self.assertIn("no open dispatch", result.stdout)

    def test_verify_exits_0_when_idle(self):
        result = run(SCRIPTS / "dispatch_state.py",
                     ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 0)

    def test_verify_exits_0_and_lists_a_healthy_dispatch(self):
        self.open_dispatch()
        result = run(SCRIPTS / "dispatch_state.py",
                     ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok open 20260907-task-3", result.stdout)

    def test_verify_exits_1_on_corrupt_json(self):
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-bad.json").write_text("not json", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py",
                     ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("CORRUPT", result.stdout)
        self.assertIn("not valid JSON", result.stdout)

    def test_verify_exits_1_on_invalid_schema(self):
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-bad.json").write_text(
            json.dumps({"schema_version": 1, "run_id": "bad"}), encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py",
                     ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("CORRUPT", result.stdout)

    def test_open_fails_cleanly_on_corrupt_file(self):
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-old.json").write_text("bad json", encoding="utf-8")
        result = self.open_dispatch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("state file corrupted", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_active_fails_cleanly_on_corrupt_file(self):
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-old.json").write_text("bad json", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py",
                     ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("state file corrupted", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_close_fails_cleanly_on_corrupt_file(self):
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-task-3.json").write_text("bad json", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py", [
            "close", "--workspace", str(self.workspace),
            "--run-id", "task-3", "--outcome", "accepted"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot read state file", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_active_skips_corrupt_closed_record_and_finds_open(self):
        """A corrupt closed/aborted record should not block finding an open dispatch."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        # Write a corrupt closed record that sorts before the open one
        (state_dir / "dispatch-20260901-old.json").write_text(
            json.dumps({"schema_version": 1, "run_id": "20260901-old",
                       "status": "closed"}), encoding="utf-8")
        # Write a healthy open record
        self.open_dispatch(run_id="20260907-task-3")
        result = run(SCRIPTS / "dispatch_state.py",
                     ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("20260907-task-3", result.stdout)

    def test_active_raises_on_unparseable_even_with_open_record(self):
        """An unparseable record must raise even if another record is open."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        # Write a healthy open record first
        self.open_dispatch(run_id="20260907-task-3")
        # Write an unparseable record that sorts after
        (state_dir / "dispatch-20260908-bad.json").write_text(
            "corrupted data", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py",
                     ["active", "--workspace", str(self.workspace)])
        # Should fail because the unparseable record could be the open dispatch
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("state file corrupted", result.stderr)

    def test_missing_schema_produces_clean_error_not_traceback(self):
        """Missing schema file should raise DispatchStateError, not FileNotFoundError."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.open_dispatch()
        # Temporarily hide the schema file
        schemas_dir = ROOT / "schemas"
        dispatch_schema = schemas_dir / "dispatch.schema.json"
        backup = dispatch_schema.read_text(encoding="utf-8")
        try:
            dispatch_schema.unlink()
            result = run(SCRIPTS / "dispatch_state.py",
                         ["active", "--workspace", str(self.workspace)])
            self.assertEqual(result.returncode, 1)
            self.assertIn("schema", result.stderr.lower())
            self.assertNotIn("FileNotFoundError", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        finally:
            dispatch_schema.write_text(backup, encoding="utf-8")

    def test_verify_reports_all_files_including_corrupt(self):
        """verify should report on every file and exit 1 if any are corrupt."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        # Write a healthy dispatch
        self.open_dispatch(run_id="20260907-task-1")
        # Write a corrupt dispatch
        (state_dir / "dispatch-20260907-bad.json").write_text(
            "not json", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py",
                     ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("ok open 20260907-task-1", result.stdout)
        self.assertIn("CORRUPT", result.stdout)

    def make_corrupted_copy(self, schema_name, contents):
        """Build a scratch copy of scripts/ + schemas/ with one schema corrupted.

        Returns the path to dispatch_state.py inside the copy so tests never
        touch the real schemas/ directory.
        """
        copy_root = Path(self.tmp.name) / "_repo_copy"
        shutil.copytree(SCRIPTS, copy_root / "scripts")
        shutil.copytree(ROOT / "schemas", copy_root / "schemas")
        (copy_root / "schemas" / schema_name).write_text(contents, encoding="utf-8")
        return copy_root / "scripts" / "dispatch_state.py"

    def test_active_fails_cleanly_when_schema_file_is_invalid_json(self):
        """A schema file that exists but is not valid JSON must not traceback."""
        script = self.make_corrupted_copy(
            "dispatch.schema.json", "not json at all")
        self.open_dispatch()
        result = run(script, ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("dispatch.schema.json", result.stderr)
        self.assertIn("not valid json", result.stderr.lower())

    def test_verify_reports_corrupt_when_schema_file_is_invalid_json(self):
        """verify must still exit 1 and report CORRUPT, not traceback."""
        script = self.make_corrupted_copy(
            "brief.schema.json", "{ this is not json")
        self.open_dispatch()
        result = run(script, ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("CORRUPT", result.stdout)

    def test_active_fails_cleanly_when_top_level_json_is_a_list(self):
        """A dispatch file whose top level is a list must not AttributeError."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-list.json").write_text(
            json.dumps([1, 2, 3]), encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py",
                     ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("state file corrupted", result.stderr)

    def test_active_fails_cleanly_when_top_level_json_is_null(self):
        """A dispatch file whose top level is null must not AttributeError."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-null.json").write_text("null", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py",
                     ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("state file corrupted", result.stderr)


class RootWriteGuardTests(unittest.TestCase):
    """Root must not write product code around an open delegation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def open_dispatch(self, brief=None):
        path = self.workspace / "brief.json"
        path.write_text(json.dumps(brief or valid_brief()), encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py", [
            "open", "--workspace", str(self.workspace), "--brief", str(path),
            "--run-id", "20260907-task-3"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def call(self, tool="Edit", path="scripts/envelope.py", agent_type=None):
        payload = {"tool_name": tool, "cwd": str(self.workspace),
                   "tool_input": {"file_path": path}}
        if agent_type:
            payload["agent_type"] = agent_type
        return run(HOOKS / "root_write_guard.py", [], stdin=json.dumps(payload))

    def test_allows_everything_when_no_dispatch_is_open(self):
        self.assertEqual(self.call().returncode, 0)

    def test_blocks_root_editing_a_delegated_path(self):
        self.open_dispatch()
        result = self.call()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Root write guard", result.stderr)
        self.assertIn("re-brief the worker", result.stderr.lower())

    def test_blocks_a_file_inside_a_delegated_directory(self):
        self.open_dispatch(valid_brief(write_paths=["scripts"]))
        self.assertEqual(self.call(path="scripts/deep/inner.py").returncode, 2)

    def test_allows_a_path_the_dispatch_does_not_own(self):
        self.open_dispatch()
        self.assertEqual(self.call(path="AI_Codex/session.md").returncode, 0)

    def test_allows_the_worker_itself(self):
        self.open_dispatch()
        for agent in ("impl-executor", "root-architect-execution:impl-executor"):
            with self.subTest(agent=agent):
                self.assertEqual(self.call(agent_type=agent).returncode, 0)

    def test_ignores_non_write_tools(self):
        self.open_dispatch()
        self.assertEqual(self.call(tool="Read").returncode, 0)

    def test_survives_malformed_input_without_blocking(self):
        result = run(HOOKS / "root_write_guard.py", [], stdin="not json")
        self.assertEqual(result.returncode, 0)


class WorkerGitGuardTests(unittest.TestCase):

    def call(self, agent_type, command=None, tool="Bash"):
        payload = {"tool_name": tool, "agent_type": agent_type,
                   "tool_input": {"command": command} if command else {}}
        return run(HOOKS / "worker_git_guard.py", [], stdin=json.dumps(payload))

    def test_ignores_the_root_session(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
        result = run(HOOKS / "worker_git_guard.py", [], stdin=json.dumps(payload))
        self.assertEqual(result.returncode, 0)

    def test_recognises_a_namespaced_agent_type(self):
        """Claude Code reports a plugin agent as "<plugin>:<agent>"."""
        result = self.call("root-architect-execution:impl-executor",
                           "git commit -m x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Root owns Git", result.stderr)

    def test_namespaced_read_only_git_still_allowed(self):
        self.assertEqual(
            self.call("root-architect-execution:impl-executor",
                      "git status").returncode, 0)

    def test_namespaced_spec_validator_has_no_shell(self):
        result = self.call("root-architect-execution:spec-validator",
                           "python3 -m unittest x")
        self.assertEqual(result.returncode, 2)

    def test_ignores_an_unrelated_subagent(self):
        self.assertEqual(
            self.call("Explore", "git commit -m x").returncode, 0)

    def test_blocks_a_worker_commit(self):
        result = self.call("impl-executor", "git commit -m 'save work'")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Root owns Git", result.stderr)

    def test_blocks_staging(self):
        self.assertEqual(
            self.call("impl-executor", "git add -A").returncode, 2)

    def test_blocks_git_hidden_behind_a_chained_command(self):
        result = self.call("impl-executor",
                           "python3 -m unittest x && git commit -am wip")
        self.assertEqual(result.returncode, 2)

    def test_blocks_an_absolute_git_path(self):
        self.assertEqual(
            self.call("impl-executor", "/usr/bin/git push origin HEAD").returncode, 2)

    def test_allows_read_only_git_inspection(self):
        for command in ("git status", "git diff --stat", "git log -1",
                        "git rev-parse HEAD"):
            with self.subTest(command=command):
                self.assertEqual(
                    self.call("impl-executor", command).returncode, 0)

    def test_allows_an_ordinary_test_command(self):
        self.assertEqual(
            self.call("impl-executor", "python3 -m unittest discover").returncode, 0)

    def test_does_not_match_a_word_merely_containing_git(self):
        self.assertEqual(
            self.call("impl-executor", "python3 digit_tool.py --legit").returncode, 0)

    def test_spec_validator_has_no_shell(self):
        result = self.call("spec-validator", "python3 -m unittest x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("read-only with no shell", result.stderr)

    def test_spec_validator_cannot_edit(self):
        result = self.call("spec-validator", tool="Edit")
        self.assertEqual(result.returncode, 2)
        self.assertIn("fixes nothing", result.stderr)

    def test_quality_validator_may_run_commands_but_not_edit(self):
        self.assertEqual(
            self.call("quality-validator", "python3 -m unittest x").returncode, 0)
        self.assertEqual(self.call("quality-validator", tool="Write").returncode, 2)


if __name__ == "__main__":
    unittest.main()
