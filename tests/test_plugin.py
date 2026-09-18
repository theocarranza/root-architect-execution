"""Tests for the root-architect-execution plugin.

Scope: enough to prove each part works and that the guards actually refuse the
things the skill says they refuse. Not an exhaustive JSON Schema conformance
suite — the mini validator is checked through the contracts that use it.

    python3 -m unittest discover -s tests -t .
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
# ADR 0001 step 3 moved the hooks into the adapter that ships them. The
# constant follows rather than the tests each learning the new path: at
# runtime they still land at <plugin root>/hooks/, which is what the
# guards' own messages refer to.
HOOKS = ROOT / "adapters" / "claude-code" / "hooks"
# ADR 0001 step 4: generated agents now live in the adapter that ships them,
# for every host. dist/<host>/ could not double as the renderer's output any
# more - build_adapter empties that directory before writing it.
CLAUDE_AGENTS = ROOT / "adapters" / "claude-code" / "agents"
sys.path.insert(0, str(SCRIPTS))

# The Codex installer is a host MECHANIC, not a shared script, so it is loaded
# by path rather than imported off sys.path. Putting adapters/codex/ on the
# path would also make every other host's mechanics importable by bare name,
# which is the coupling the adapter directories exist to prevent.
import importlib.util  # noqa: E402

import render_agents  # noqa: E402
from dispatch_state import DispatchStateError  # noqa: E402
from jsonschema_mini import Validator  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "codex_install", ROOT / "adapters" / "codex" / "install.py"
)
install_codex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_codex)
import mailbox  # noqa: E402

import build_adapter  # noqa: E402
import job_queue  # noqa: E402
import root_preflight  # noqa: E402
import smoke_install  # noqa: E402
import validate_interfaces  # noqa: E402


@contextlib.contextmanager
def mock_adapters(directory):
    """Point build_adapter at a scratch adapters/ tree.

    Tests never write into the real adapters/ directory; a build test
    that mutates the repository is how a suite starts passing for the
    wrong reason.
    """
    original = build_adapter.ADAPTERS
    build_adapter.ADAPTERS = Path(directory)
    try:
        yield
    finally:
        build_adapter.ADAPTERS = original


def run(script, args, stdin=None):
    return subprocess.run(
        [sys.executable, str(script)] + args, input=stdin, capture_output=True, text=True
    )


def make_corrupted_copy(tmp_dir, schema_name, contents, include_hooks=False):
    """Build a scratch copy of scripts/ + schemas/ with one schema corrupted.

    Returns the path to the copy's root directory so callers can locate
    dispatch_state.py or hooks/root_write_guard.py inside it. Tests never
    touch the real schemas/ directory this way. When contents is None, the
    schema file is removed instead of corrupted, to exercise the missing-
    sibling case.
    """
    copy_root = Path(tmp_dir) / "_repo_copy"
    shutil.copytree(SCRIPTS, copy_root / "scripts")
    shutil.copytree(ROOT / "schemas", copy_root / "schemas")
    if include_hooks:
        shutil.copytree(HOOKS, copy_root / "hooks")
    target = copy_root / "schemas" / schema_name
    if contents is None:
        target.unlink()
    else:
        target.write_text(contents, encoding="utf-8")
    return copy_root


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
        "task": "T",
        "attempt": 1,
        "model": "haiku",
        "effort": "low",
        "status": "DONE",
        "files_written": [],
        "files_modified": ["a.py"],
        "tests": {
            "red": {"command": "c", "counts": "1 failed"},
            "green": {"command": "c", "counts": "19 passed"},
        },
        "diff_summary": "d",
        "notes": "",
    }
    report.update(overrides)
    return report


def valid_verdict(**overrides):
    verdict = {
        "task": "T",
        "attempt": 1,
        "role": "spec-validator",
        "status": "PASS",
        "findings": [],
        "commands_rerun": [],
    }
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
        self.assertTrue(any("constraints" in e for e in self.brief.validate(brief)))

    def test_rejects_unknown_property(self):
        errors = self.brief.validate(valid_brief(surprise=1))
        self.assertTrue(any("surprise" in e for e in errors))

    def test_rejects_attempt_above_the_cap(self):
        self.assertTrue(any("maximum" in e for e in self.brief.validate(valid_brief(attempt=4))))

    def test_rejects_absolute_and_escaping_write_paths(self):
        for bad in ("/etc/passwd", "../outside.py"):
            with self.subTest(path=bad):
                errors = self.brief.validate(valid_brief(write_paths=[bad]))
                self.assertTrue(any("pattern" in e for e in errors), bad)

    def test_rejects_control_characters_in_write_paths(self):
        """A brief whose write_paths contain control characters (U+0000-U+001F, U+007F)
        must be rejected by the brief schema."""
        for control_char in [chr(0), chr(1), "\t", "\n", chr(31), chr(127)]:
            with self.subTest(control_char=repr(control_char)):
                errors = self.brief.validate(
                    valid_brief(write_paths=["scripts/envelope.py", "bad" + control_char + "path"])
                )
                self.assertTrue(
                    any("pattern" in e for e in errors),
                    f"Schema should reject control char {repr(control_char)}",
                )

    def test_rejects_control_characters_in_read_paths(self):
        """A brief whose read_paths contain control characters (U+0000-U+001F, U+007F)
        must be rejected by the brief schema."""
        for control_char in [chr(0), chr(1), "\t", "\n", chr(31), chr(127)]:
            with self.subTest(control_char=repr(control_char)):
                errors = self.brief.validate(
                    valid_brief(read_paths=["scripts/envelope.py", "bad" + control_char + "path"])
                )
                self.assertTrue(
                    any("pattern" in e for e in errors),
                    f"Schema should reject control char {repr(control_char)}",
                )

    def test_anyof_accepts_both_effort_forms(self):
        for effort in ("high", "not settable on this host"):
            with self.subTest(effort=effort):
                self.assertEqual(self.brief.validate(valid_brief(effort=effort)), [])

    def test_anyof_rejects_an_invented_effort_level(self):
        self.assertNotEqual(self.brief.validate(valid_brief(effort="turbo")), [])

    def test_boolean_is_not_an_integer(self):
        self.assertNotEqual(self.brief.validate(valid_brief(attempt=True)), [])


class RoleAndHostManifestTests(unittest.TestCase):
    def test_shipped_manifests_pass_the_capability_gate(self):
        result = run(SCRIPTS / "validate_roles.py", [])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gate_reports_inherited_cursor_manifest(self):
        result = run(SCRIPTS / "validate_roles.py", [])
        self.assertIn("inherited and unverified", result.stdout)

    def test_every_role_declares_all_four_axes(self):
        for _, role in render_agents.load_roles():
            with self.subTest(role=role["id"]):
                self.assertIn(role["model"]["default"], ("cheap", "mid", "strong"))
                self.assertIn(
                    role["reasoning"]["default"], ("low", "medium", "high", "xhigh", "max")
                )
                self.assertTrue(role["tools"]["allow"])
                self.assertIn(role["mutation"], ("read-only", "read-and-run", "write-scoped"))

    def test_only_the_orchestrator_may_delegate(self):
        """Was "no role may delegate", which was true until one had to.

        Kept as a positive statement of the rule rather than deleted: delegation
        being exactly one role's is the property worth guarding, and a test that
        merely disappeared would have guarded nothing.
        """
        for _, role in render_agents.load_roles():
            with self.subTest(role=role["id"]):
                self.assertEqual(
                    "delegate" in role["tools"]["allow"],
                    role["kind"] in ("orchestrator", "root"),
                    role["id"],
                )

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
    def test_codex_manifest_and_skill_are_installable(self):
        manifest = json.loads((ROOT / "adapters/codex/manifest.template.json").read_text())
        self.assertEqual(manifest["name"], "root-architect-execution")
        self.assertEqual(manifest["skills"], "./skills")
        self.assertIn("defaultPrompt", manifest["interface"])
        self.assertTrue((ROOT / "skills/root-architect-execution/SKILL.md").exists())

    def toml_parser(self):
        """A real TOML parser, or an explicit skip naming what is uncovered.

        tomllib is 3.11+, and this repo's `python3` is 3.10, so every
        parser-backed assertion here is skipped under the documented outcome
        command. That is the exact gap SKILL.md's outcome gate warns about —
        generated output can leave a suite green and still ship broken — so
        the skip says so, README names the 3.12 probe as part of the gate,
        and the parser-free assertions above carry the load on 3.10.
        """
        try:
            import tomllib

            return tomllib
        except ImportError:
            pass
        try:
            import tomli

            return tomli
        except ImportError:
            self.skipTest(
                "no TOML parser on this interpreter (tomllib needs 3.11+). "
                "Generated Codex TOMLs are UNVERIFIED here; run the outcome "
                "gate's python3.12 probe, or `pip install tomli`."
            )

    def test_codex_render_is_parseable_and_uses_no_placeholder_when_installed(self):
        tomllib = self.toml_parser()
        with tempfile.TemporaryDirectory() as tmp:
            install_codex.materialize(Path(tmp) / "agents", Path(tmp) / "plugin root")
            for path in (Path(tmp) / "agents").glob("*.toml"):
                self.assertNotIn("<skill_root>", path.read_text())
                tomllib.loads(path.read_text())

    def test_codex_install_preserves_unrelated_agents_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "agents"
            target.mkdir()
            unrelated = target / "user-agent.toml"
            unrelated.write_text('name = "user-agent"\n')
            install_codex.materialize(target, Path(tmp) / "plugin")
            first = {p.name: p.read_bytes() for p in target.iterdir()}
            install_codex.materialize(target, Path(tmp) / "plugin")
            second = {p.name: p.read_bytes() for p in target.iterdir()}
            self.assertIn("user-agent.toml", second)
            self.assertEqual(first, second)

    def test_codex_install_never_deletes_outside_its_target(self):
        """The marker is data, not a delete list.

        `.codex/agents` is the documented target and lives inside the
        consuming project, so its marker file is as trustworthy as a cloned
        repository — which is to say, not. An entry that escapes the
        directory must be skipped, never unlinked: the installer owns the
        files it wrote and nothing else.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / ".codex" / "agents"
            target.mkdir(parents=True)
            (project / "victim.txt").write_text("secret", encoding="utf-8")
            nested = project / "home"
            nested.mkdir()
            (nested / "id_rsa").write_text("key", encoding="utf-8")
            (target / ".root-architect-execution-codex.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "files": [
                            "../../victim.txt",
                            "../../home/id_rsa",
                            "../victim.txt",
                            "/etc/hostname",
                            "impl-executor.toml",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            install_codex.materialize(target, ROOT)

            self.assertTrue(
                (project / "victim.txt").exists(), "a marker entry escaped the target directory"
            )
            self.assertTrue(
                (nested / "id_rsa").exists(), "a marker entry escaped the target directory"
            )

    def test_codex_install_survives_a_malformed_marker(self):
        """A marker that is not a list of filenames must not abort the install.

        It ran mid-way through before: the TOMLs were already written and the
        marker had not been rewritten yet, so the next run inherited a stale
        ownership record.
        """
        for payload in (
            '{"version": 1, "files": [1, 2]}',
            '{"version": 1, "files": 5}',
            '{"version": 1, "files": "impl-executor.toml"}',
            '{"version": 1}',
            "[]",
            "null",
            "not json at all",
        ):
            with self.subTest(marker=payload):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / "agents"
                    target.mkdir()
                    (target / ".root-architect-execution-codex.json").write_text(
                        payload, encoding="utf-8"
                    )
                    _, names = install_codex.materialize(target, ROOT)
                    expected = sum(
                        1
                        for _, role in render_agents.load_roles()
                        if render_agents.role_targets_host(role, "codex")[0]
                    )
                    self.assertEqual(len(names), expected)

    def test_codex_install_still_removes_a_file_it_owns(self):
        """The hardening must not turn the cleanup into a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "agents"
            target.mkdir()
            stale = target / "retired-agent.toml"
            stale.write_text('name = "retired"\n', encoding="utf-8")
            unrelated = target / "user-agent.toml"
            unrelated.write_text('name = "user"\n', encoding="utf-8")
            (target / ".root-architect-execution-codex.json").write_text(
                json.dumps({"version": 1, "files": ["retired-agent.toml"]}), encoding="utf-8"
            )

            install_codex.materialize(target, ROOT)

            self.assertFalse(stale.exists(), "an owned stale file was kept")
            self.assertTrue(unrelated.exists(), "an unowned file was removed")

    def test_generated_claude_agents_declare_all_four_axes(self):
        for name in ("impl-executor", "spec-validator", "quality-validator"):
            with self.subTest(agent=name):
                text = (CLAUDE_AGENTS / (name + ".md")).read_text(encoding="utf-8")
                head = text.split("---")[1]
                self.assertIn("model:", head)
                self.assertIn("effort:", head)
                self.assertIn("tools:", head)
                self.assertNotIn("inherit", head)

    def test_read_only_role_gets_no_write_or_shell_tool(self):
        head = (CLAUDE_AGENTS / "spec-validator.md").read_text(encoding="utf-8").split("---")[1]
        tools = [line for line in head.splitlines() if line.startswith("tools:")][0]
        for forbidden in ("Edit", "Write", "Bash"):
            self.assertNotIn(forbidden, tools)

    def test_unenforceable_capability_becomes_a_disclosure(self):
        """Cursor cannot express a tool allowlist; the file must say so."""
        with tempfile.TemporaryDirectory() as tmp:
            run(SCRIPTS / "render_agents.py", ["--host", "cursor", "--out", tmp])
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
            run(SCRIPTS / "render_agents.py", ["--host", "claude-code", "--out", tmp])
            target = Path(tmp) / "impl-executor.md"
            target.write_text(
                target.read_text(encoding="utf-8").replace("model: haiku", "model: opus"),
                encoding="utf-8",
            )
            result = run(
                SCRIPTS / "render_agents.py", ["--host", "claude-code", "--out", tmp, "--check"]
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("out of sync", result.stderr)

    def test_empty_mapped_allow_list_never_produces_allowed_period(self):
        """Test requirement (a): no generated file contains the malformed 'Allowed: .' string."""
        # Check dist/ directory
        for toml_file in (ROOT / "dist" / "codex").glob("*.toml"):
            text = toml_file.read_text(encoding="utf-8")
            self.assertNotIn(
                "Allowed: .", text, f"Found malformed 'Allowed: .' in {toml_file.name}"
            )
        # Check agents/ directory
        for md_file in CLAUDE_AGENTS.glob("*.md"):
            text = md_file.read_text(encoding="utf-8")
            self.assertNotIn("Allowed: .", text, f"Found malformed 'Allowed: .' in {md_file.name}")

    def test_empty_mapped_allow_list_uses_explicit_wording(self):
        """Test requirement (b): empty mapped allow list renders 'no host-enforced tools'."""
        # spec-validator has tools.allow: ["read-files", "search-files"]
        # but codex.json only maps edit-files, create-files, and run-commands
        # so spec-validator on codex has an empty mapped allow list
        with tempfile.TemporaryDirectory() as tmp:
            run(SCRIPTS / "render_agents.py", ["--host", "codex", "--out", tmp])
            text = (Path(tmp) / "spec-validator.toml").read_text(encoding="utf-8")
        self.assertIn("Allowed: no host-enforced tools.", text)
        self.assertNotIn("Allowed: .", text)

    def unmappable_allowlist_host(self):
        """A host that enforces an allowlist and cannot map an allowed intent.

        No shipped host is in this state — claude-code maps every portable
        intent — so the case has to be constructed. It is not hypothetical:
        this branch put hosts/codex.json into exactly this shape by dropping
        read-files and search-files from tool_map, and codex is only spared
        because it declares no allowlist.
        """
        host = json.loads(json.dumps(render_agents.load_host("claude-code")))
        host["tool_map"].pop("read-files")
        host["tool_map"].pop("search-files")
        return host

    def test_unmappable_intent_on_an_allowlist_host_is_a_rendering_error(self):
        """An empty grant must never render as a full one.

        hosts/claude-code.json records the host behaviour that makes this
        load-bearing: "omitting it inherits every available tool". So an
        omitted `tools` line is not a tidy way to express an empty allow
        list, it is the opposite of one — and because read_only_enforced
        points at the same `tools` field, omitting it also drops read-only
        enforcement for the validator roles. Emitting the field empty is
        malformed instead. Neither is acceptable, so the render fails, which
        is what schemas/agent-role.schema.json already calls for: "a
        rendering error, not a silent drop".
        """
        host = self.unmappable_allowlist_host()
        role_file, role = next(
            (f, r) for f, r in render_agents.load_roles() if r["id"] == "spec-validator"
        )
        with self.assertRaises(SystemExit) as caught:
            render_agents.render_markdown_yaml(role, host, role_file)
        message = str(caught.exception)
        self.assertIn("spec-validator", message)
        self.assertIn("read-files", message)
        self.assertIn("grant every tool", message)

    def test_allowlist_host_never_renders_a_frontmatter_without_the_field(self):
        """The failure above is what stops the permissive file being written.

        Guards the outcome rather than the mechanism: on a host that enforces
        an allowlist, every generated agent carries the field. A future
        refactor that "helpfully" omits it again fails here even if it stops
        raising.
        """
        host = render_agents.load_host("claude-code")
        field = host["capabilities"]["tool_allowlist"]["field"]
        for role_file, role in render_agents.load_roles():
            with self.subTest(role=role["id"]):
                text = render_agents.render_markdown_yaml(role, host, role_file)
                head = text.split("---")[1]
                self.assertRegex(head, r"(?m)^%s: \S" % field)

    def test_generated_toml_escapes_a_hostile_plugin_root(self):
        """The plugin root is the one part of the body nobody in this repo owns.

        It comes from whoever runs install_codex.py, and it lands inside a
        TOML multi-line basic string, which processes backslash escapes and
        ends at the first triple quote. This assertion needs no TOML parser,
        so unlike the tomllib case below it actually runs on Python 3.10.
        """
        host = render_agents.load_host("codex")
        role_file, role = render_agents.load_roles()[0]
        for bad in ('/tmp/a"""root', "/tmp/a\\troot", '/tmp/pl"ain', '/tmp/end"""'):
            with self.subTest(plugin_root=bad):
                text = render_agents.render_toml(role, dict(host, root_placeholder=bad), role_file)
                body = text.split('developer_instructions = """\n', 1)[1]
                body = body.rsplit('\n"""', 1)[0]
                self.assertNotIn(
                    '"""',
                    body,
                    "an unescaped triple quote ends the string "
                    "early and turns instructions into TOML",
                )
                # Every backslash must open one of the two escapes this
                # renderer emits. Any other sequence is raw input that TOML
                # will reinterpret — \t becoming a tab is how the path stops
                # resolving. Pairs are consumed so the second character of
                # \\ is not read as opening an escape of its own.
                index = 0
                while index < len(body):
                    if body[index] != "\\":
                        index += 1
                        continue
                    self.assertIn(
                        body[index + 1 : index + 2],
                        ("\\", '"'),
                        "unescaped backslash at %d: TOML will reinterpret "
                        "%r" % (index, body[index : index + 8]),
                    )
                    index += 2

    def test_generated_toml_round_trips_a_hostile_plugin_root(self):
        """Same cases, checked against a real parser where one exists."""
        tomllib = self.toml_parser()
        host = render_agents.load_host("codex")
        role_file, role = render_agents.load_roles()[0]
        for bad in ('/tmp/a"""root', "/tmp/a\\troot", '/tmp/pl"ain'):
            with self.subTest(plugin_root=bad):
                text = render_agents.render_toml(role, dict(host, root_placeholder=bad), role_file)
                parsed = tomllib.loads(text)
                self.assertIn(
                    bad,
                    parsed["developer_instructions"],
                    "the path must survive TOML unescaping intact",
                )

    # --- host-enforced prohibitions (the ledger's section 7, findings 1-3) ---

    def test_scoped_hooks_is_false_because_we_ship_as_a_plugin(self):
        """plugins-reference: hooks are ignored for plugin-shipped agents.

        The manifest claimed `supported: true` while its own verified note
        explained that session-wide hooks are used instead. The renderer reads
        the boolean, so the generated file asserted an enforcement that does
        not exist for anything distributed the way this plugin is.
        """
        host = render_agents.load_host("claude-code")
        hooks = host["capabilities"]["scoped_hooks"]
        self.assertFalse(hooks["supported"])
        self.assertIsNone(hooks["field"])
        self.assertIn("plugin", hooks["verified"].lower())

    def test_ask_owner_is_reported_as_host_enforced(self):
        """AskUserQuestion is stripped from every subagent unconditionally.

        Not derivable: `ask-owner` maps to no portable tool intent, so nothing
        in tool_map could imply it. It is declared in the manifest instead, and
        the declaration has to carry its own provenance.
        """
        host = render_agents.load_host("claude-code")
        declared = 0
        for _role_file, role in render_agents.load_roles():
            # Scoped to roles that DECLARE it. Root is the operator channel, so
            # it declares no such prohibition and nothing should claim one is
            # enforced on it - asserting this of every role would have demanded
            # exactly that false claim.
            if "ask-owner" not in role["must_not"]:
                continue
            declared += 1
            with self.subTest(role=role["id"]):
                found = render_agents.enforced_prohibitions(role, host)
                self.assertIn("ask-owner", found)
                self.assertTrue(found["ask-owner"].strip())
        self.assertEqual(declared, 4, "every dispatched agent declares it")

    def test_spawn_agents_enforcement_is_derived_not_declared(self):
        """Derived from the grant, so it cannot drift away from the truth.

        Every role denies `delegate`, and this host enforces its allowlist, so
        Agent never reaches the written `tools` line. Grant delegate back and
        the claim must disappear on its own -- that is the whole reason this
        one is computed rather than listed in the manifest.
        """
        host = render_agents.load_host("claude-code")
        _role_file, role = render_agents.load_roles()[0]
        self.assertIn("spawn-agents", render_agents.enforced_prohibitions(role, host))

        granted = json.loads(json.dumps(role))
        granted["tools"]["allow"] = list(granted["tools"]["allow"]) + ["delegate"]
        granted["tools"]["deny"] = [d for d in granted["tools"]["deny"] if d != "delegate"]
        self.assertNotIn("spawn-agents", render_agents.enforced_prohibitions(granted, host))

    def test_a_host_without_an_enforced_allowlist_claims_nothing(self):
        """Codex and Cursor must not inherit Claude's enforcement claims."""
        for name in ("codex", "cursor"):
            host = render_agents.load_host(name)
            for _role_file, role in render_agents.load_roles():
                with self.subTest(host=name, role=role["id"]):
                    self.assertEqual(render_agents.enforced_prohibitions(role, host), {})

    def test_enforced_prohibitions_are_not_listed_as_unenforced(self):
        """The two lists must never merge.

        A positive enforcement statement rendered under the "does not enforce"
        heading is precisely the kind of false claim this file exists to catch,
        and it is what the first draft of this change actually produced.
        """
        host = render_agents.load_host("claude-code")
        for role_file, role in render_agents.load_roles():
            with self.subTest(role=role["id"]):
                notes = render_agents.disclosures(
                    role, host, render_agents.resolve_tools(role, host)[2]
                )
                joined = " ".join(notes)
                # Not a blanket search for "host-enforced": the write-scope
                # note legitimately uses the phrase negatively ("never
                # host-enforced anywhere"). What must never appear among the
                # disclosures is a prohibition this host actually enforces.
                for name in render_agents.enforced_prohibitions(role, host):
                    self.assertNotIn(name, joined)

                text = render_agents.render_markdown_yaml(role, host, role_file)
                body = text.split("## Enforcement", 1)[1]
                negative, _, positive = body.partition("What this host **does** enforce")
                # Assert over what the renderer DERIVES rather than a fixed
                # pair of names. spawn-agents is enforced only for a role that
                # holds no delegation, so hardcoding it made this test fail the
                # moment a delegating role existed - and it would have been
                # wrong to "fix" that by asserting it of the orchestrator too.
                enforced = render_agents.enforced_prohibitions(role, host)
                if "ask-owner" in role["must_not"]:
                    self.assertIn(
                        "ask-owner", enforced, "a role declaring it should have it enforced"
                    )
                for name in enforced:
                    self.assertIn(name, positive)
                    self.assertNotIn(name, negative)

    def test_generated_agents_state_the_enforcement_on_disk(self):
        """Guards the committed artifacts, not the code path above."""
        for path in sorted(CLAUDE_AGENTS.glob("*.md")):
            with self.subTest(agent=path.stem):
                text = path.read_text(encoding="utf-8")
                self.assertIn("What this host **does** enforce", text)
                # Derived per role rather than a fixed pair: spawn-agents is
                # enforced only where the role holds no delegation, so the
                # orchestrator legitimately lacks it.
                role = next(r for _, r in render_agents.load_roles() if r["id"] == path.stem)
                host = render_agents.load_host("claude-code")
                for name in render_agents.enforced_prohibitions(role, host):
                    self.assertIn("**%s**" % name, text)


class AdapterBuildTests(unittest.TestCase):
    """ADR 0001 step 2: the bundle gate, which had to exist before step 3.

    The ADR's stated risk is that "a build step means the thing reviewed stops
    being the thing that runs". These tests are the argument that it does not.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scratch = Path(self.tmp.name)

    def build(self, host="claude-code", out=None):
        return run(
            SCRIPTS / "build_adapter.py",
            ["--host", host, "--out", str(out or self.scratch / "bundle")],
        )

    def test_layout_matches_its_own_directory_and_schema(self):
        for path in sorted((ROOT / "adapters").glob("*/layout.json")):
            with self.subTest(adapter=path.parent.name):
                layout = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    layout["host"],
                    path.parent.name,
                    "a layout must not describe a host it is not filed under",
                )
                validator = Validator(ROOT / "schemas/adapter-layout.schema.json")
                self.assertEqual(validator.validate(layout), [])

    def test_build_produces_the_installable_shape(self):
        out = self.scratch / "bundle"
        result = self.build(out=out)
        self.assertEqual(result.returncode, 0, result.stderr)
        # The pieces an install actually needs.
        for required in (
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
            "SKILL.md",
            "hooks/hooks.json",
            "agents/impl-executor.md",
        ):
            self.assertTrue((out / required).exists(), "missing %s" % required)

    def test_build_carries_no_bytecode(self):
        """__pycache__ in a shipped bundle is stale code waiting to be run."""
        out = self.scratch / "bundle"
        self.build(out=out)
        strays = [p for p in out.rglob("*") if "__pycache__" in p.parts or p.suffix == ".pyc"]
        self.assertEqual(strays, [])

    def test_committed_bundle_matches_a_fresh_build(self):
        """Every built host, not just the first one.

        This checked claude-code alone until ADR 0001 step 4 added a second
        bundle, and CI gained the codex check while the suite did not - so
        `python3 -m unittest` passed over a stale Codex bundle. Derived from
        the layouts rather than listed, so a third host is covered the day its
        layout lands instead of the day somebody remembers this file.
        """
        built = sorted(p.parent.name for p in (ROOT / "adapters").glob("*/layout.json"))
        self.assertIn("codex", built, "fixture broken: no codex layout")
        self.assertIn("gemini", built, "fixture broken: no gemini layout")
        for host in built:
            with self.subTest(host=host):
                result = run(SCRIPTS / "build_adapter.py", ["--host", host, "--check"])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("in sync", result.stdout)

    def test_gemini_adapter_produces_expected_bundle_structure_and_roles(self):
        """The Gemini adapter compiles all five canonical roles into Markdown agents
        and projects them into a valid distribution bundle."""
        agents_dir = ROOT / "adapters/gemini/agents"
        for role in (
            "root-architect",
            "orchestrator",
            "impl-executor",
            "spec-validator",
            "quality-validator",
        ):
            self.assertTrue(
                (agents_dir / ("%s.md" % role)).is_file(), "missing generated agent: %s.md" % role
            )

        bundle = ROOT / "dist/gemini"
        self.assertTrue((bundle / "plugin.json").is_file())
        self.assertTrue((bundle / ".gemini-plugin/plugin.json").is_file())
        self.assertTrue((bundle / "skills/root-architect-execution/SKILL.md").is_file())
        self.assertTrue((bundle / "agents/root-architect.md").is_file())
        self.assertTrue((bundle / "agents/orchestrator.md").is_file())
        self.assertIn(
            "mainAgent: true", (bundle / "agents/root-architect.md").read_text(encoding="utf-8")
        )
        self.assertIn(
            "subagent: true", (bundle / "agents/impl-executor.md").read_text(encoding="utf-8")
        )

        res_iface = run(SCRIPTS / "validate_interfaces.py", ["--adapter", "gemini"])
        self.assertEqual(res_iface.returncode, 0, res_iface.stderr)

        res_render = run(SCRIPTS / "render_agents.py", ["--host", "gemini", "--check"])
        self.assertEqual(res_render.returncode, 0, res_render.stderr)

        res_build = run(SCRIPTS / "build_adapter.py", ["--host", "gemini", "--check"])
        self.assertEqual(res_build.returncode, 0, res_build.stderr)

    def test_check_catches_a_source_change_that_was_never_rebuilt(self):
        """The case a path -> hash manifest cannot catch.

        A bundle built from stale sources hashes perfectly against itself. Only
        a rebuild-and-compare proves the bundle agrees with the source it
        claims to come from, which is why --check does that instead of
        shipping a BUILD-MANIFEST.
        """
        out = self.scratch / "bundle"
        self.build(out=out)
        source = out / "scripts/check_return.py"
        source.write_text(source.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
        missing, extra, differing = build_adapter.compare(
            build_adapter.ROOT / "dist/claude-code", out
        )
        self.assertIn(Path("scripts/check_return.py"), differing)

    def test_check_separates_missing_from_extra_from_differing(self):
        """Three different mistakes, and a reader needs to know which."""
        left, right = self.scratch / "a", self.scratch / "b"
        self.build(out=left)
        self.build(out=right)
        (right / "scripts/check_return.py").write_text("changed", encoding="utf-8")
        (right / "extra.txt").write_text("x", encoding="utf-8")
        (right / "SKILL.md").unlink()

        missing, extra, differing = build_adapter.compare(left, right)
        self.assertEqual(missing, [Path("SKILL.md")])
        self.assertEqual(extra, [Path("extra.txt")])
        self.assertEqual(differing, [Path("scripts/check_return.py")])

    def test_a_layout_naming_a_missing_source_fails_loudly(self):
        """A bundle silently short a file is an install that breaks later."""
        adapter = self.scratch / "adapters" / "ghost"
        adapter.mkdir(parents=True)
        (adapter / "layout.json").write_text(
            json.dumps(
                {
                    "host": "ghost",
                    "bundle_root": ".",
                    "place": {"does-not-exist.md": "does-not-exist.md"},
                }
            ),
            encoding="utf-8",
        )
        with mock_adapters(adapter.parent):
            with self.assertRaises(build_adapter.BuildError) as caught:
                build_adapter.build("ghost", self.scratch / "out")
        self.assertIn("neither", str(caught.exception))

    def test_a_layout_whose_host_disagrees_is_refused(self):
        adapter = self.scratch / "adapters" / "ghost"
        adapter.mkdir(parents=True)
        (adapter / "layout.json").write_text(
            json.dumps(
                {
                    "host": "somewhere-else",
                    "bundle_root": ".",
                    "place": {"SKILL.md": "SKILL.md"},
                }
            ),
            encoding="utf-8",
        )
        with mock_adapters(adapter.parent):
            with self.assertRaises(build_adapter.BuildError) as caught:
                build_adapter.load_layout("ghost")
        self.assertIn("filed under", str(caught.exception))

    def test_adapter_sources_win_over_repository_sources(self):
        """The property that makes ADR 0001 step 3 a pure move.

        Moving hooks/ into adapters/claude-code/hooks/ must not require
        touching layout.json -- the adapter copy simply starts winning.
        """
        adapter = self.scratch / "adapters" / "claude-code"
        adapter.mkdir(parents=True)
        (adapter / "SKILL.md").write_text("adapter copy", encoding="utf-8")
        with mock_adapters(adapter.parent):
            resolved = build_adapter.resolve_source("claude-code", "SKILL.md")
        self.assertEqual(resolved, adapter / "SKILL.md")

    # --- smoke install: the host run against the artifact ---

    def test_expectations_are_derived_from_the_sources(self):
        """Add a role and the gate must demand it without being edited."""
        want = smoke_install.expectations("claude-code")
        roles = sorted(p.stem for p in (ROOT / "roles").glob("*.json"))
        self.assertEqual(want["agents"], roles)
        self.assertEqual(
            want["hooks"], ["PreToolUse"], "read from hooks.json's events, not its top-level key"
        )

    def test_hook_events_come_from_the_events_not_the_wrapper(self):
        """hooks.json nests events under a "hooks" key.

        Reading the top level yielded the literal string "hooks", which then
        matched the host report's own "Hooks (1)" heading -- an assertion that
        passed whatever shipped.
        """
        self.assertNotIn("hooks", smoke_install.expectations("claude-code")["hooks"])

    def test_missing_hook_targets_are_reported_not_raised(self):
        """Registration is not reachability.

        Deleting a guard while leaving hooks.json intact gives a bundle the
        host installs happily and reports the hook for; the guard then fails
        the first time it fires. hook_targets() returns what is unreachable
        and the caller turns that into the refusal.
        """
        bundle = Path(self.tmp.name) / "b2"
        shutil.copytree(ROOT / "dist/claude-code", bundle)
        (bundle / "hooks/worker_git_guard.py").unlink()
        self.assertEqual(smoke_install.hook_targets(bundle), ["hooks/worker_git_guard.py"])

    def test_a_bundle_with_no_hooks_manifest_fails_cleanly(self):
        """An absent hooks.json must diagnose, never traceback.

        The first version read the file unconditionally, so deleting it
        produced a stack trace in place of the message -- the same error-path
        failure this repository keeps closing in its guards.
        """
        bundle = Path(self.tmp.name) / "b3"
        shutil.copytree(ROOT / "dist/claude-code", bundle)
        (bundle / "hooks/hooks.json").unlink()
        with self.assertRaises(smoke_install.SmokeError):
            smoke_install.hook_targets(bundle)

    def test_inventory_is_read_apart_from_the_prose(self):
        """The plugin's own description names its hooks.

        Searching the whole report let "Two PreToolUse hooks enforce..." in the
        description satisfy a check for a registered PreToolUse hook, so a
        bundle shipping none passed.
        """
        report = (
            "thermos 1.0.0\n"
            "  Description: Two PreToolUse hooks enforce the boundary.\n"
            "\n"
            "Component inventory\n"
            "  Skills (1)  a-skill\n"
            "  Hooks (0)\n"
            "\n"
            "Projected token cost\n"
        )
        inventory = smoke_install.component_inventory(report)
        self.assertIn("Hooks (0)", inventory)
        self.assertNotIn("Description", inventory)

    def test_an_unreadable_report_is_refused_rather_than_passed(self):
        with self.assertRaises(smoke_install.SmokeError):
            smoke_install.component_inventory("no inventory here")


class CheckReturnTests(unittest.TestCase):
    def check(self, role, payload, extra=None, raw=None):
        body = raw if raw is not None else "here you go\n\n```json\n%s\n```\n" % json.dumps(payload)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(body)
            path = fh.name
        return run(SCRIPTS / "check_return.py", ["--role", role, "--file", path] + (extra or []))

    def test_accepts_a_well_formed_report(self):
        self.assertEqual(self.check("implementer", valid_report()).returncode, 0)

    def test_done_without_red_counts_is_rejected(self):
        report = valid_report()
        report["tests"]["red"] = None
        result = self.check("implementer", report)
        self.assertEqual(result.returncode, 1)
        self.assertIn("must carry observed RED counts", result.stderr)

    def test_pass_carrying_findings_is_rejected(self):
        verdict = valid_verdict(
            findings=[{"path": "a.py", "requirement": "r", "evidence": "e", "required_fix": "f"}]
        )
        result = self.check("spec-validator", verdict)
        self.assertEqual(result.returncode, 1)
        self.assertIn("PASS cannot carry findings", result.stderr)

    def test_findings_carrying_none_is_rejected(self):
        result = self.check("spec-validator", valid_verdict(status="FINDINGS"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("must carry at least one finding", result.stderr)

    def test_spec_validator_that_ran_commands_is_rejected(self):
        verdict = valid_verdict(commands_rerun=[{"command": "pytest", "observed": "19 passed"}])
        result = self.check("spec-validator", verdict)
        self.assertEqual(result.returncode, 1)
        self.assertIn("review roles were combined", result.stderr)

    def test_quality_finding_without_a_failure_scenario_is_rejected(self):
        verdict = valid_verdict(
            role="quality-validator",
            status="FINDINGS",
            findings=[{"path": "a.py", "requirement": "r", "evidence": "e", "required_fix": "f"}],
        )
        result = self.check("quality-validator", verdict)
        self.assertEqual(result.returncode, 1)
        self.assertIn("failure_scenario", result.stderr)

    def test_role_mismatch_is_rejected(self):
        result = self.check("quality-validator", valid_verdict())
        self.assertEqual(result.returncode, 1)
        self.assertIn("root dispatched", result.stderr)

    def test_task_mismatch_is_rejected(self):
        result = self.check("implementer", valid_report(), extra=["--task", "a different task"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("root dispatched", result.stderr)

    def test_prose_without_a_json_block_is_rejected(self):
        result = self.check("implementer", None, raw="I finished the task and all tests pass.")
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
        return run(
            SCRIPTS / "dispatch_state.py",
            [
                "open",
                "--workspace",
                str(self.workspace),
                "--brief",
                self.write_brief(brief or valid_brief()),
                "--run-id",
                run_id,
            ],
        )

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
        result = self.open_dispatch(
            valid_brief(attempt=2, escalation_reason="attempt 1 left the tamper case unwritten")
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refuses_a_second_concurrent_dispatch(self):
        self.open_dispatch()
        result = self.open_dispatch(run_id="20260907-task-4")
        self.assertEqual(result.returncode, 1)
        self.assertIn("One dependent task at a time", result.stderr)

    def test_close_frees_the_slot(self):
        self.open_dispatch()
        closed = run(
            SCRIPTS / "dispatch_state.py",
            [
                "close",
                "--workspace",
                str(self.workspace),
                "--run-id",
                "20260907-task-3",
                "--outcome",
                "accepted",
            ],
        )
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertEqual(self.open_dispatch(run_id="20260907-task-4").returncode, 0)

    def test_blocked_outcome_marks_the_dispatch_aborted(self):
        self.open_dispatch()
        run(
            SCRIPTS / "dispatch_state.py",
            [
                "close",
                "--workspace",
                str(self.workspace),
                "--run-id",
                "20260907-task-3",
                "--outcome",
                "blocked",
            ],
        )
        state = json.loads(
            (
                self.workspace / ".root-architect" / "state" / "dispatch-20260907-task-3.json"
            ).read_text()
        )
        self.assertEqual(state["status"], "aborted")

    def test_active_reports_nothing_when_idle(self):
        result = run(SCRIPTS / "dispatch_state.py", ["active", "--workspace", str(self.workspace)])
        self.assertIn("no open dispatch", result.stdout)

    def test_verify_exits_0_when_idle(self):
        result = run(SCRIPTS / "dispatch_state.py", ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 0)

    def test_verify_exits_0_and_lists_a_healthy_dispatch(self):
        self.open_dispatch()
        result = run(SCRIPTS / "dispatch_state.py", ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok open 20260907-task-3", result.stdout)

    def test_verify_exits_1_on_corrupt_json(self):
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-bad.json").write_text("not json", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py", ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("CORRUPT", result.stdout)
        self.assertIn("not valid JSON", result.stdout)

    def test_verify_exits_1_on_invalid_schema(self):
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-bad.json").write_text(
            json.dumps({"schema_version": 1, "run_id": "bad"}), encoding="utf-8"
        )
        result = run(SCRIPTS / "dispatch_state.py", ["verify", "--workspace", str(self.workspace)])
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
        result = run(SCRIPTS / "dispatch_state.py", ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("state file corrupted", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_close_fails_cleanly_on_corrupt_file(self):
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-task-3.json").write_text("bad json", encoding="utf-8")
        result = run(
            SCRIPTS / "dispatch_state.py",
            [
                "close",
                "--workspace",
                str(self.workspace),
                "--run-id",
                "task-3",
                "--outcome",
                "accepted",
            ],
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot read state file", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_active_skips_corrupt_closed_record_and_finds_open(self):
        """A corrupt closed/aborted record should not block finding an open dispatch."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        # Write a corrupt closed record that sorts before the open one
        (state_dir / "dispatch-20260901-old.json").write_text(
            json.dumps({"schema_version": 1, "run_id": "20260901-old", "status": "closed"}),
            encoding="utf-8",
        )
        # Write a healthy open record
        self.open_dispatch(run_id="20260907-task-3")
        result = run(SCRIPTS / "dispatch_state.py", ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("20260907-task-3", result.stdout)

    def test_active_raises_on_unparseable_even_with_open_record(self):
        """An unparseable record must raise even if another record is open."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        # Write a healthy open record first
        self.open_dispatch(run_id="20260907-task-3")
        # Write an unparseable record that sorts after
        (state_dir / "dispatch-20260908-bad.json").write_text("corrupted data", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py", ["active", "--workspace", str(self.workspace)])
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
            result = run(
                SCRIPTS / "dispatch_state.py", ["active", "--workspace", str(self.workspace)]
            )
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
        (state_dir / "dispatch-20260907-bad.json").write_text("not json", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py", ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("ok open 20260907-task-1", result.stdout)
        self.assertIn("CORRUPT", result.stdout)

    def test_active_fails_cleanly_when_schema_file_is_invalid_json(self):
        """A schema file that exists but is not valid JSON must not traceback."""
        copy_root = make_corrupted_copy(self.tmp.name, "dispatch.schema.json", "not json at all")
        script = copy_root / "scripts" / "dispatch_state.py"
        self.open_dispatch()
        result = run(script, ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("dispatch.schema.json", result.stderr)
        self.assertIn("not valid json", result.stderr.lower())

    def test_verify_reports_corrupt_when_schema_file_is_invalid_json(self):
        """verify must still exit 1 and report CORRUPT, not traceback."""
        copy_root = make_corrupted_copy(self.tmp.name, "brief.schema.json", "{ this is not json")
        script = copy_root / "scripts" / "dispatch_state.py"
        self.open_dispatch()
        result = run(script, ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("CORRUPT", result.stdout)

    def test_active_names_sibling_schema_not_root_schema_when_corrupt(self):
        """A corrupt SIBLING schema (brief.schema.json) must be named in the
        error, not the root schema (dispatch.schema.json) that referenced it.
        This is the regression test for the trap: the naive fix blames the
        root schema because that is what _validate_dispatch was called with.
        """
        copy_root = make_corrupted_copy(self.tmp.name, "brief.schema.json", "{ not json")
        script = copy_root / "scripts" / "dispatch_state.py"
        self.open_dispatch()
        result = run(script, ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("brief.schema.json", result.stderr)
        self.assertNotIn("dispatch.schema.json", result.stderr)

    def test_active_names_missing_sibling_schema(self):
        """A missing sibling schema file must be named in the error."""
        copy_root = make_corrupted_copy(self.tmp.name, "brief.schema.json", None)
        script = copy_root / "scripts" / "dispatch_state.py"
        self.open_dispatch()
        result = run(script, ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("brief.schema.json", result.stderr)

    def test_verify_reports_corrupt_when_sibling_schema_is_invalid_json(self):
        """verify must still report CORRUPT and exit 1 for a corrupt sibling."""
        copy_root = make_corrupted_copy(self.tmp.name, "brief.schema.json", "{ not json")
        script = copy_root / "scripts" / "dispatch_state.py"
        self.open_dispatch()
        result = run(script, ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("CORRUPT", result.stdout)

    def test_active_fails_cleanly_when_top_level_json_is_a_list(self):
        """A dispatch file whose top level is a list must not AttributeError."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-list.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py", ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("state file corrupted", result.stderr)

    def test_active_fails_cleanly_when_top_level_json_is_null(self):
        """A dispatch file whose top level is null must not AttributeError."""
        state_dir = self.workspace / ".root-architect" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "dispatch-null.json").write_text("null", encoding="utf-8")
        result = run(SCRIPTS / "dispatch_state.py", ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("state file corrupted", result.stderr)

    def _make_unlistable(self, directory):
        """chmod 000 a state directory, restoring the mode whatever happens.

        Skipped as root: uid 0 bypasses permission bits, so the directory
        would still list and the test would pass while proving nothing.
        """
        if os.geteuid() == 0:
            self.skipTest("root bypasses permission bits; chmod 000 proves nothing")
        directory.mkdir(parents=True, exist_ok=True)
        original = directory.stat().st_mode
        os.chmod(directory, 0o000)
        self.addCleanup(os.chmod, directory, original)

    def test_active_raises_when_state_directory_cannot_be_listed(self):
        """An unlistable state directory is untrusted, not 'no dispatch open'.

        Path.glob() swallows the PermissionError from scandir and yields
        nothing, which would read exactly like an empty directory.
        """
        from dispatch_state import active_dispatch

        directory = self.workspace / ".root-architect" / "state"
        self._make_unlistable(directory)
        with self.assertRaises(DispatchStateError) as caught:
            active_dispatch(self.workspace)
        self.assertIn(str(directory), str(caught.exception))

    def test_active_command_fails_cleanly_on_an_unlistable_directory(self):
        directory = self.workspace / ".root-architect" / "state"
        self._make_unlistable(directory)
        result = run(SCRIPTS / "dispatch_state.py", ["active", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("no open dispatch", result.stdout)
        self.assertIn(str(directory), result.stderr)

    def test_verify_reports_an_unlistable_directory(self):
        directory = self.workspace / ".root-architect" / "state"
        self._make_unlistable(directory)
        result = run(SCRIPTS / "dispatch_state.py", ["verify", "--workspace", str(self.workspace)])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("no dispatch files", result.stdout)
        self.assertIn(str(directory), result.stdout + result.stderr)


class RootWriteGuardTests(unittest.TestCase):
    """Root must not write product code around an open delegation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def open_dispatch(self, brief=None):
        path = self.workspace / "brief.json"
        path.write_text(json.dumps(brief or valid_brief()), encoding="utf-8")
        result = run(
            SCRIPTS / "dispatch_state.py",
            [
                "open",
                "--workspace",
                str(self.workspace),
                "--brief",
                str(path),
                "--run-id",
                "20260907-task-3",
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def call(self, tool="Edit", path="scripts/envelope.py", agent_type=None):
        payload = {"tool_name": tool, "cwd": str(self.workspace), "tool_input": {"file_path": path}}
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

    def test_codex_apply_patch_identity_unknown_is_not_blocked(self):
        self.open_dispatch()
        payload = {
            "tool_name": "apply_patch",
            "cwd": str(self.workspace),
            "tool_input": {
                "command": "*** Begin Patch\n"
                "*** Update File: scripts/envelope.py\n"
                "@@\n*** End Patch\n"
            },
        }
        result = self.raw_call(payload)
        self.assertEqual(result.returncode, 0)

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

    def test_survives_list_tool_input_without_blocking(self):
        self.open_dispatch()
        payload = {
            "tool_name": "Edit",
            "cwd": str(self.workspace),
            "tool_input": ["not", "a", "dict"],
        }
        result = run(HOOKS / "root_write_guard.py", [], stdin=json.dumps(payload))
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_survives_string_tool_input_without_blocking(self):
        self.open_dispatch()
        payload = {"tool_name": "Edit", "cwd": str(self.workspace), "tool_input": "not a dict"}
        result = run(HOOKS / "root_write_guard.py", [], stdin=json.dumps(payload))
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_survives_non_object_payload_without_blocking(self):
        result = run(HOOKS / "root_write_guard.py", [], stdin=json.dumps([1, 2, 3]))
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def raw_call(self, payload):
        return run(HOOKS / "root_write_guard.py", [], stdin=json.dumps(payload))

    def test_survives_non_string_cwd_without_blocking(self):
        self.open_dispatch()
        result = self.raw_call(
            {"tool_name": "Edit", "cwd": 42, "tool_input": {"file_path": "scripts/envelope.py"}}
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_survives_non_string_path_value_without_blocking(self):
        self.open_dispatch()
        result = self.raw_call(
            {"tool_name": "Edit", "cwd": str(self.workspace), "tool_input": {"file_path": 42}}
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_survives_a_path_with_an_embedded_null_byte(self):
        self.open_dispatch()
        result = self.raw_call(
            {
                "tool_name": "Edit",
                "cwd": str(self.workspace),
                "tool_input": {"file_path": "scripts/env\x00.py"},
            }
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_survives_an_unhashable_tool_name(self):
        self.open_dispatch()
        result = self.raw_call(
            {
                "tool_name": ["Edit"],
                "cwd": str(self.workspace),
                "tool_input": {"file_path": "scripts/envelope.py"},
            }
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_no_payload_shape_produces_a_traceback(self):
        """The invariant: every input exits 0 or 2, never with a traceback."""
        self.open_dispatch()
        shapes = [42, 4.5, True, None, [], {}, "", "a\x00b", ["x"], {"k": "v"}]
        for shape in shapes:
            for key in ("tool_name", "cwd", "agent_type", "tool_input"):
                payload = {
                    "tool_name": "Edit",
                    "cwd": str(self.workspace),
                    "tool_input": {"file_path": "scripts/envelope.py"},
                }
                payload[key] = shape
                with self.subTest(key=key, shape=shape):
                    result = self.raw_call(payload)
                    self.assertIn(result.returncode, (0, 2))
                    self.assertNotIn("Traceback", result.stderr)
            for key in ("file_path", "notebook_path", "path"):
                payload = {
                    "tool_name": "Edit",
                    "cwd": str(self.workspace),
                    "tool_input": {key: shape},
                }
                with self.subTest(key=key, shape=shape):
                    result = self.raw_call(payload)
                    self.assertIn(result.returncode, (0, 2))
                    self.assertNotIn("Traceback", result.stderr)

    def state_dir(self):
        directory = self.workspace / ".root-architect" / "state"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def test_denies_on_unparseable_state_file(self):
        directory = self.state_dir()
        (directory / "dispatch-broken.json").write_bytes(b"\xff\xfe not json")
        result = self.call()
        self.assertEqual(result.returncode, 2)
        self.assertIn("verify", result.stderr)

    def test_denies_on_open_dispatch_missing_brief(self):
        directory = self.state_dir()
        record = {
            "schema_version": 1,
            "run_id": "x",
            "status": "open",
            "opened_at": "2026-01-01T00:00:00+00:00",
        }
        (directory / "dispatch-x.json").write_text(json.dumps(record), encoding="utf-8")
        result = self.call()
        self.assertEqual(result.returncode, 2)
        self.assertIn("verify", result.stderr)

    def test_denies_on_brief_missing_task(self):
        directory = self.state_dir()
        brief = valid_brief()
        del brief["task"]
        record = {
            "schema_version": 1,
            "run_id": "x",
            "status": "open",
            "opened_at": "2026-01-01T00:00:00+00:00",
            "brief": brief,
        }
        (directory / "dispatch-x.json").write_text(json.dumps(record), encoding="utf-8")
        result = self.call()
        self.assertEqual(result.returncode, 2)
        self.assertIn("verify", result.stderr)

    def test_denies_on_brief_with_non_integer_attempt(self):
        directory = self.state_dir()
        brief = valid_brief(attempt="one")
        record = {
            "schema_version": 1,
            "run_id": "x",
            "status": "open",
            "opened_at": "2026-01-01T00:00:00+00:00",
            "brief": brief,
        }
        (directory / "dispatch-x.json").write_text(json.dumps(record), encoding="utf-8")
        result = self.call()
        self.assertEqual(result.returncode, 2)
        self.assertIn("verify", result.stderr)

    def test_deny_reason_names_the_offending_file(self):
        directory = self.state_dir()
        target = directory / "dispatch-broken.json"
        target.write_bytes(b"\xff\xfe not json")
        result = self.call()
        self.assertEqual(result.returncode, 2)
        self.assertIn(str(target), result.stderr)
        self.assertIn("verify", result.stderr)

    def call_isolated_guard(self, copy_root):
        payload = {
            "tool_name": "Edit",
            "cwd": str(self.workspace),
            "tool_input": {"file_path": "scripts/envelope.py"},
        }
        return run(copy_root / "hooks" / "root_write_guard.py", [], stdin=json.dumps(payload))

    def test_denies_on_open_dispatch_with_corrupt_sibling_schema(self):
        """A corrupt sibling schema (brief.schema.json) must still deny with
        exit 2, not escape as an unhandled exception and exit 1. This is the
        regression test for the trap: SchemaError is not a ValueError, so a
        naive fix that raises SchemaError from _resolve would escape every
        handler up to this hook and let the write through with exit 1.
        """
        self.open_dispatch()
        copy_root = make_corrupted_copy(
            self.tmp.name, "brief.schema.json", "{ not json", include_hooks=True
        )
        result = self.call_isolated_guard(copy_root)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_denies_on_open_dispatch_with_missing_sibling_schema(self):
        """A missing sibling schema must also deny with exit 2, not escape."""
        self.open_dispatch()
        copy_root = make_corrupted_copy(
            self.tmp.name, "brief.schema.json", None, include_hooks=True
        )
        result = self.call_isolated_guard(copy_root)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_denies_when_dispatch_state_cannot_be_imported(self):
        with tempfile.TemporaryDirectory() as isolated:
            isolated = Path(isolated)
            (isolated / "hooks").mkdir()
            shutil.copy(HOOKS / "root_write_guard.py", isolated / "hooks" / "root_write_guard.py")
            workspace = isolated / "workspace"
            directory = workspace / ".root-architect" / "state"
            directory.mkdir(parents=True)
            (directory / "dispatch-x.json").write_text(
                json.dumps({"status": "open"}), encoding="utf-8"
            )
            payload = {
                "tool_name": "Edit",
                "cwd": str(workspace),
                "tool_input": {"file_path": "scripts/envelope.py"},
            }
            result = run(isolated / "hooks" / "root_write_guard.py", [], stdin=json.dumps(payload))
            self.assertEqual(result.returncode, 2)

    def test_denies_when_the_state_directory_cannot_be_listed(self):
        """chmod 000 on live state must not turn a proven deny into an allow."""
        if os.geteuid() == 0:
            self.skipTest("root bypasses permission bits; chmod 000 proves nothing")
        self.open_dispatch()
        directory = self.workspace / ".root-architect" / "state"
        original = directory.stat().st_mode
        self.assertEqual(self.call().returncode, 2)
        os.chmod(directory, 0o000)
        self.addCleanup(os.chmod, directory, original)
        result = self.call()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(str(directory), result.stderr)

    def test_import_fallback_denies_when_the_directory_cannot_be_listed(self):
        """The no-import fallback globs too, and glob is just as silent there."""
        if os.geteuid() == 0:
            self.skipTest("root bypasses permission bits; chmod 000 proves nothing")
        with tempfile.TemporaryDirectory() as isolated:
            isolated = Path(isolated)
            (isolated / "hooks").mkdir()
            shutil.copy(HOOKS / "root_write_guard.py", isolated / "hooks" / "root_write_guard.py")
            workspace = isolated / "workspace"
            directory = workspace / ".root-architect" / "state"
            directory.mkdir(parents=True)
            (directory / "dispatch-x.json").write_text(
                json.dumps({"status": "open"}), encoding="utf-8"
            )
            original = directory.stat().st_mode
            os.chmod(directory, 0o000)
            try:
                payload = {
                    "tool_name": "Edit",
                    "cwd": str(workspace),
                    "tool_input": {"file_path": "scripts/envelope.py"},
                }
                result = run(
                    isolated / "hooks" / "root_write_guard.py", [], stdin=json.dumps(payload)
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(str(directory), result.stderr)
            finally:
                os.chmod(directory, original)

    def test_resolve_owned_isolation(self):
        """_resolve_owned must return resolvable paths even when one fails.

        This directly tests Defect 1's isolation fix: each owned path resolution
        is wrapped in its own try/except, so a path that raises OSError or ValueError
        does not abort the entire list. When isolation is removed (reverted to a
        single list comprehension), this assertion fails because the comprehension
        raises instead of returning a partial list.
        """
        # Import the guard module to access _resolve_owned
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "root_write_guard", HOOKS / "root_write_guard.py"
        )
        guard_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard_module)

        root = Path.cwd()
        # Mix a resolvable path with an unresolvable one (containing null byte)
        write_paths = ["scripts/envelope.py", "bad" + chr(0) + "path"]

        resolved = guard_module._resolve_owned(root, write_paths)

        # The resolvable path MUST be in the result, even though one failed
        # This assertion fails if isolation is removed and the comprehension raises
        self.assertEqual(len(resolved), 1)
        self.assertTrue(any("envelope.py" in str(p) for p in resolved))

    def test_resolve_owned_skips_a_symlink_loop_entry(self):
        """A self-referential symlink among write_paths must not crash
        resolution; the remaining, resolvable entries are still returned.

        This is the direct unit test for Defect 3. What a looping entry
        resolves to is interpreter-defined and changed in 3.13, so what is
        asserted here is the contract, not the length of the list:

        - Up to 3.12, pathlib.Path.resolve() raises a bare RuntimeError
          ("Symlink loop from ..."), which is neither OSError nor
          ValueError. _resolve_owned must name it explicitly or one bad
          entry takes down the whole hook. The entry is then dropped, and
          the path the dispatch declared it owns loses its protection.
        - From 3.13, resolve() follows os.path.realpath(strict=False) and
          returns the path unchanged instead of raising. The entry
          survives, so the declared path stays protected.

        Dropping a declared write_path is the weaker of those two, so
        asserting a count would pin this to the less safe behaviour. The
        invariant that holds on every interpreter, and the one that
        matters, is that no exception escapes and every genuinely
        resolvable owned path is still returned.
        """
        loop = self.workspace / "loop"
        try:
            loop.symlink_to(loop)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted in this environment")

        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "root_write_guard", HOOKS / "root_write_guard.py"
        )
        guard_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard_module)

        (self.workspace / "scripts").mkdir()
        (self.workspace / "scripts" / "owned.py").write_text("x", encoding="utf-8")

        resolved = guard_module._resolve_owned(self.workspace, ["scripts/owned.py", "loop/x"])

        # Resolution completed instead of raising, and the entry that can be
        # resolved is protected on every interpreter.
        self.assertTrue(any("owned.py" in str(p) for p in resolved))

        # The looping entry is either dropped (<= 3.12) or carried through
        # verbatim (3.13+). What must never happen is it resolving to some
        # third path, which would protect the wrong file.
        looping = [p for p in resolved if "owned.py" not in str(p)]
        self.assertIn(len(looping), (0, 1))
        for path in looping:
            self.assertTrue(str(path).endswith(os.path.join("loop", "x")))

    def test_blocks_a_genuinely_owned_path_when_another_write_path_loops(self):
        """A dispatch whose write_paths include a symlink loop must still
        deny an edit to the other, genuinely owned path in the same list --
        and must never crash with a traceback while doing it.
        """
        loop = self.workspace / "loop"
        try:
            loop.symlink_to(loop)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted in this environment")

        (self.workspace / "scripts").mkdir(exist_ok=True)
        (self.workspace / "scripts" / "owned.py").write_text("x", encoding="utf-8")

        self.open_dispatch(valid_brief(write_paths=["scripts/owned.py", "loop/x"]))
        result = self.call(path="scripts/owned.py")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_survives_an_edit_target_that_is_itself_a_symlink_loop(self):
        """The edit target resolving through a symlink loop must not crash
        the hook with an uncaught exception (exit 1); it must exit 0 or 2.
        """
        loop = self.workspace / "loop"
        try:
            loop.symlink_to(loop)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted in this environment")

        self.open_dispatch()
        result = self.call(path="loop/x")
        self.assertIn(result.returncode, (0, 2))
        self.assertNotIn("Traceback", result.stderr)

    def test_guard_denies_via_schema_invalid_branch(self):
        """The guard must deny when dispatch state is schema-invalid.

        This end-to-end test verifies the fail-closed invariant: when the guard
        cannot verify dispatch state (schema-invalid, unparseable, or untrusted),
        it denies the write. The deny happens via the schema-validation branch in
        active_dispatch() and DispatchStateError, BEFORE the guard's own path
        comparison logic is reached.

        This test does not exercise the per-path resolution isolation fix (Defect 1).
        That fix is tested directly in test_resolve_owned_isolation() via the
        _resolve_owned() function.
        """
        # Manually write a dispatch state with a control character in write_paths.
        # After DEFECT 2 is fixed, the schema rejects control characters, so
        # active_dispatch() raises DispatchStateError during schema validation.
        # This triggers the guard's fail-closed denial before path resolution.
        directory = self.state_dir()
        brief = valid_brief(write_paths=["scripts/envelope.py", "bad" + chr(0) + "path"])
        record = {
            "schema_version": 1,
            "run_id": "20260907-test-schema-invalid",
            "status": "open",
            "opened_at": "2026-01-01T00:00:00+00:00",
            "brief": brief,
        }
        (directory / "dispatch-20260907-test-schema-invalid.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

        result = self.call()
        # Should deny via schema-invalid branch, not allow
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be trusted", result.stderr)

    # --- A denial must terminate the process even if it cannot report ---

    def unwritable_stdout(self):
        """Open a stream that accepts no bytes, or skip if none is available.

        /dev/full raises ENOSPC on every write, which is the closest stand-in
        for the "device full" and "broken pipe" cases root observed. Where it
        does not exist, the caller skips rather than silently passing.
        """
        try:
            return open("/dev/full", "w")
        except OSError:
            self.skipTest("/dev/full is not available in this environment")

    def test_denial_exits_2_when_stdout_cannot_be_written(self):
        """The load-bearing invariant: only exit 2 blocks a call.

        The guard has already PROVEN the target is owned by an open dispatch.
        If reporting that denial fails, the denial itself must still stand.
        Exit 0 (the outer handler swallowing the OSError and allowing) and
        exit 120 (an OSError surfacing at interpreter-shutdown flush after
        sys.exit(2)) are both fail-open, and both are failures here.
        """
        self.open_dispatch()
        payload = json.dumps(
            {
                "tool_name": "Edit",
                "cwd": str(self.workspace),
                "tool_input": {"file_path": "scripts/envelope.py"},
            }
        )
        for unbuffered in (True, False):
            with self.subTest(unbuffered=unbuffered):
                env = dict(os.environ)
                if unbuffered:
                    env["PYTHONUNBUFFERED"] = "1"
                else:
                    env.pop("PYTHONUNBUFFERED", None)
                sink = self.unwritable_stdout()
                try:
                    result = subprocess.run(
                        [sys.executable, str(HOOKS / "root_write_guard.py")],
                        input=payload,
                        text=True,
                        env=env,
                        stdout=sink,
                        stderr=subprocess.PIPE,
                    )
                finally:
                    sink.close()
                self.assertEqual(result.returncode, 2)

    def test_denial_exits_2_when_stdout_is_a_closed_pipe(self):
        """Same invariant via the other real-world shape: a broken pipe."""
        self.open_dispatch()
        payload = json.dumps(
            {
                "tool_name": "Edit",
                "cwd": str(self.workspace),
                "tool_input": {"file_path": "scripts/envelope.py"},
            }
        )
        for unbuffered in (True, False):
            with self.subTest(unbuffered=unbuffered):
                env = dict(os.environ)
                if unbuffered:
                    env["PYTHONUNBUFFERED"] = "1"
                else:
                    env.pop("PYTHONUNBUFFERED", None)
                read_fd, write_fd = os.pipe()
                os.close(read_fd)
                try:
                    result = subprocess.run(
                        [sys.executable, str(HOOKS / "root_write_guard.py")],
                        input=payload,
                        text=True,
                        env=env,
                        stdout=write_fd,
                        stderr=subprocess.PIPE,
                    )
                finally:
                    os.close(write_fd)
                self.assertEqual(result.returncode, 2)

    def test_deny_itself_exits_2_when_the_stdout_write_raises(self):
        """_deny() must be unconditionally terminal, exercised directly.

        Narrowing the outer try in _main() is necessary but not sufficient:
        if _deny()'s print then raises, the exception reaches main()'s safety
        net, which calls _deny() again on the same broken stream, and the
        second exception escapes as exit 1. A reporting failure must not
        change _deny()'s exit code.
        """
        program = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location("
            "'root_write_guard', %r)\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "class Broken:\n"
            "    def write(self, *a): raise OSError(28, 'No space left on device')\n"
            "    def flush(self): raise OSError(28, 'No space left on device')\n"
            "sys.stdout = Broken()\n"
            "m._deny('boom')\n"
        ) % str(HOOKS / "root_write_guard.py")
        result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_deny_exits_2_when_both_streams_are_broken(self):
        """Neither the stdout payload nor the stderr reason may rescue a call."""
        program = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location("
            "'root_write_guard', %r)\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "class Broken:\n"
            "    def write(self, *a): raise OSError(28, 'No space left on device')\n"
            "    def flush(self): raise OSError(28, 'No space left on device')\n"
            "sys.stdout = Broken()\n"
            "sys.stderr = Broken()\n"
            "m._deny('boom')\n"
        ) % str(HOOKS / "root_write_guard.py")
        result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_allow_still_exits_0_with_an_unwritable_stdout(self):
        """The fix must not turn deliberate allows into denials."""
        self.open_dispatch()
        payload = json.dumps(
            {
                "tool_name": "Edit",
                "cwd": str(self.workspace),
                "tool_input": {"file_path": "AI_Codex/session.md"},
            }
        )
        sink = self.unwritable_stdout()
        try:
            result = subprocess.run(
                [sys.executable, str(HOOKS / "root_write_guard.py")],
                input=payload,
                text=True,
                stdout=sink,
                stderr=subprocess.PIPE,
            )
        finally:
            sink.close()
        self.assertEqual(result.returncode, 0)


class WorkerGitGuardTests(unittest.TestCase):
    def call(self, agent_type, command=None, tool="Bash"):
        payload = {
            "tool_name": tool,
            "agent_type": agent_type,
            "tool_input": {"command": command} if command else {},
        }
        return run(HOOKS / "worker_git_guard.py", [], stdin=json.dumps(payload))

    def test_ignores_the_root_session(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
        result = run(HOOKS / "worker_git_guard.py", [], stdin=json.dumps(payload))
        self.assertEqual(result.returncode, 0)

    def test_recognises_a_namespaced_agent_type(self):
        """Claude Code reports a plugin agent as "<plugin>:<agent>"."""
        result = self.call("root-architect-execution:impl-executor", "git commit -m x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Root owns Git", result.stderr)

    def test_namespaced_read_only_git_still_allowed(self):
        self.assertEqual(
            self.call("root-architect-execution:impl-executor", "git status").returncode, 0
        )

    def test_namespaced_spec_validator_has_no_shell(self):
        result = self.call("root-architect-execution:spec-validator", "python3 -m unittest x")
        self.assertEqual(result.returncode, 2)

    def test_ignores_an_unrelated_subagent(self):
        self.assertEqual(self.call("Explore", "git commit -m x").returncode, 0)

    def test_blocks_a_worker_commit(self):
        result = self.call("impl-executor", "git commit -m 'save work'")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Root owns Git", result.stderr)

    def test_blocks_staging(self):
        self.assertEqual(self.call("impl-executor", "git add -A").returncode, 2)

    def test_blocks_git_hidden_behind_a_chained_command(self):
        result = self.call("impl-executor", "python3 -m unittest x && git commit -am wip")
        self.assertEqual(result.returncode, 2)

    def test_blocks_an_absolute_git_path(self):
        self.assertEqual(self.call("impl-executor", "/usr/bin/git push origin HEAD").returncode, 2)

    def test_allows_read_only_git_inspection(self):
        for command in ("git status", "git diff --stat", "git log -1", "git rev-parse HEAD"):
            with self.subTest(command=command):
                self.assertEqual(self.call("impl-executor", command).returncode, 0)

    def test_allows_an_ordinary_test_command(self):
        self.assertEqual(self.call("impl-executor", "python3 -m unittest discover").returncode, 0)

    def test_does_not_match_a_word_merely_containing_git(self):
        self.assertEqual(self.call("impl-executor", "python3 digit_tool.py --legit").returncode, 0)

    def test_spec_validator_has_no_shell(self):
        result = self.call("spec-validator", "python3 -m unittest x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("read-only with no shell", result.stderr)

    def test_spec_validator_cannot_edit(self):
        result = self.call("spec-validator", tool="Edit")
        self.assertEqual(result.returncode, 2)
        self.assertIn("fixes nothing", result.stderr)

    def test_quality_validator_may_run_commands_but_not_edit(self):
        self.assertEqual(self.call("quality-validator", "python3 -m unittest x").returncode, 0)
        self.assertEqual(self.call("quality-validator", tool="Write").returncode, 2)

    def raw(self, payload, stdout=None):
        """Drive the hook with an arbitrary stdin body and stdout target."""
        return subprocess.run(
            [sys.executable, str(HOOKS / "worker_git_guard.py")],
            input=payload,
            capture_output=stdout is None,
            stdout=stdout,
            stderr=subprocess.DEVNULL if stdout is not None else None,
            text=True,
        )

    def unwritable_stdout(self):
        """See RootWriteGuardTests.unwritable_stdout — same stand-in, same why."""
        try:
            return open("/dev/full", "w")
        except OSError:
            self.skipTest("/dev/full is not available in this environment")

    def test_denial_exits_2_when_stdout_cannot_be_written(self):
        """The same load-bearing invariant root_write_guard already holds.

        This guard has proven the call is a worker reaching for Git. If
        reporting that denial fails, the denial still stands. Exit 1 (the
        OSError escaping an unhandled print) and exit 120 (an OSError
        surfacing at interpreter-shutdown flush after sys.exit(2)) are both
        fail-open, and both are failures here.
        """
        with self.unwritable_stdout() as devfull:
            for unbuffered in (True, False):
                for command in ("git commit -m x", "git push"):
                    with self.subTest(unbuffered=unbuffered, command=command):
                        env = dict(os.environ)
                        if unbuffered:
                            env["PYTHONUNBUFFERED"] = "1"
                        else:
                            env.pop("PYTHONUNBUFFERED", None)
                        payload = json.dumps(
                            {
                                "agent_type": "impl-executor",
                                "tool_name": "Bash",
                                "tool_input": {"command": command},
                            }
                        )
                        result = subprocess.run(
                            [sys.executable, str(HOOKS / "worker_git_guard.py")],
                            input=payload,
                            text=True,
                            env=env,
                            stdout=devfull,
                            stderr=subprocess.DEVNULL,
                        )
                        self.assertEqual(result.returncode, 2)

    def test_validator_edit_denial_also_survives_an_unwritable_stdout(self):
        with self.unwritable_stdout() as devfull:
            payload = json.dumps(
                {
                    "agent_type": "spec-validator",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "x.py"},
                }
            )
            result = subprocess.run(
                [sys.executable, str(HOOKS / "worker_git_guard.py")],
                input=payload,
                text=True,
                stdout=devfull,
                stderr=subprocess.DEVNULL,
            )
        self.assertEqual(result.returncode, 2)

    def test_no_payload_shape_produces_a_traceback(self):
        """Every input exits 0 or 2. Exit 1 is a non-blocking allow by accident.

        Malformed hook *input* allows: without a readable agent_type there is
        no evidence of a worker, and denying would block root's own shell,
        which the protocol's stop conditions rely on for recovery. Malformed
        state *inside* a proven worker denies.
        """
        cases = [
            ("not json at all", 0),
            ("[1, 2, 3]", 0),
            ('"a bare string"', 0),
            ("null", 0),
            (
                json.dumps(
                    {"agent_type": [1], "tool_name": "Bash", "tool_input": {"command": "git push"}}
                ),
                0,
            ),
            (
                json.dumps(
                    {"agent_type": 7, "tool_name": "Bash", "tool_input": {"command": "git push"}}
                ),
                0,
            ),
            (json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit"}}), 0),
            (
                json.dumps(
                    {"agent_type": "impl-executor", "tool_name": ["Bash"], "tool_input": {}}
                ),
                2,
            ),
            (
                json.dumps(
                    {"agent_type": "impl-executor", "tool_name": {"a": 1}, "tool_input": {}}
                ),
                2,
            ),
            (json.dumps({"agent_type": "spec-validator", "tool_name": None, "tool_input": {}}), 2),
            (
                json.dumps(
                    {"agent_type": "impl-executor", "tool_name": "Bash", "tool_input": [1, 2]}
                ),
                2,
            ),
            (
                json.dumps(
                    {"agent_type": "impl-executor", "tool_name": "Bash", "tool_input": "a string"}
                ),
                2,
            ),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload[:60]):
                result = self.raw(payload)
                self.assertIn(
                    result.returncode,
                    (0, 2),
                    "exit %s is neither a clean allow nor a block; "
                    "stderr:\n%s" % (result.returncode, result.stderr),
                )
                self.assertEqual(result.returncode, expected)
                self.assertNotIn("Traceback", result.stderr)


class OrchestratorRoleTests(unittest.TestCase):
    """The kind discriminator, and the invariants it exists to keep.

    Adding a fourth agent must not weaken "the loop is a fixed three-agent
    architecture". These tests check that it did not.
    """

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def sandbox(self):
        dest = self.scratch / "tree"
        shutil.copytree(
            ROOT, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "dist")
        )
        return dest

    def gate(self, root=None):
        return subprocess.run(
            [sys.executable, str((root or ROOT) / "scripts/validate_roles.py")],
            capture_output=True,
            text=True,
            cwd=str(root or ROOT),
        )

    def roles(self):
        return dict(render_agents.load_roles())

    def test_every_manifest_declares_its_kind(self):
        for role_file, role in self.roles().items():
            with self.subTest(role=role_file):
                self.assertIn(role["kind"], ("worker", "orchestrator", "root"))

    def test_exactly_three_workers_and_one_orchestrator(self):
        kinds = [r["kind"] for r in self.roles().values()]
        self.assertEqual(kinds.count("worker"), 3)
        self.assertEqual(kinds.count("orchestrator"), 1)

    def test_no_worker_delegates(self):
        """Delegation belongs to the two agents that dispatch, and to no worker.

        Was "the orchestrator's alone", which stopped being true when root
        arrived - root dispatches the orchestrator. The property that actually
        matters survives the change: a worker never dispatches anything, so
        work cannot reach a worker except through the orchestrator.
        """
        for role_file, role in self.roles().items():
            with self.subTest(role=role_file):
                delegates = "delegate" in role["tools"]["allow"]
                self.assertEqual(
                    delegates,
                    role["kind"] in ("orchestrator", "root"),
                    "only the dispatchers hold delegation",
                )

    def test_the_orchestrator_cannot_touch_source(self):
        """It dispatches work; it does not do it."""
        role = self.roles()["orchestrator.json"]
        for intent in ("edit-files", "create-files"):
            self.assertNotIn(intent, role["tools"]["allow"])
        for prohibition in ("commit", "stage", "plan-work", "ask-owner"):
            self.assertIn(prohibition, role["must_not"])

    def test_a_fourth_worker_is_still_refused(self):
        """The invariant the discriminator had to preserve."""
        tree = self.sandbox()
        extra = json.loads((tree / "roles/impl-executor.json").read_text())
        extra["id"] = "second-implementer"
        (tree / "roles/second-implementer.json").write_text(json.dumps(extra, indent=2))

        result = self.gate(tree)
        self.assertEqual(result.returncode, 1, "a fourth worker manifest passed the gate")
        self.assertIn("fixed three-agent", result.stdout + result.stderr)

    def test_a_second_orchestrator_is_refused(self):
        """A run has one dispatcher or it has no boundary."""
        tree = self.sandbox()
        extra = json.loads((tree / "roles/orchestrator.json").read_text())
        extra["id"] = "second-orchestrator"
        (tree / "roles/second-orchestrator.json").write_text(json.dumps(extra, indent=2))

        result = self.gate(tree)
        self.assertEqual(result.returncode, 1)

    def test_a_worker_granted_delegation_is_refused(self):
        tree = self.sandbox()
        path = tree / "roles/impl-executor.json"
        role = json.loads(path.read_text())
        role["tools"]["allow"].append("delegate")
        role["tools"]["deny"] = [d for d in role["tools"]["deny"] if d != "delegate"]
        path.write_text(json.dumps(role, indent=2))

        result = self.gate(tree)
        self.assertEqual(
            result.returncode, 1, "a worker was granted delegation and the gate allowed it"
        )
        self.assertIn("only the orchestrator dispatches", result.stdout + result.stderr)

    def test_an_orchestrator_without_delegation_is_refused(self):
        """It would have nothing to orchestrate.

        Asserts the rule's own message, not merely a non-zero exit. Stripping
        delegation also trips the not-generated check, so an exit-code-only
        assertion passed whether or not this rule existed - which mutation
        testing caught.
        """
        tree = self.sandbox()
        path = tree / "roles/orchestrator.json"
        role = json.loads(path.read_text())
        role["tools"]["allow"] = [t for t in role["tools"]["allow"] if t != "delegate"]
        path.write_text(json.dumps(role, indent=2))

        result = self.gate(tree)
        self.assertEqual(result.returncode, 1)
        self.assertIn("would have nothing to orchestrate", result.stdout + result.stderr)

    def test_the_unenforceable_delegation_scope_is_disclosed(self):
        """Agent(type) binds only for the main thread; the orchestrator is not.

        Leaving this undisclosed would let the grant imply a restriction the
        host does not apply - the exact shape of failure this repository keeps
        closing.
        """
        # The generator, not only the artifact. An earlier version of this
        # test read the committed file alone, so deleting the disclosure from
        # render_agents.py left it passing - it was guarding the output of a
        # build nobody had re-run.
        host = render_agents.load_host("claude-code")
        role = next(r for _, r in render_agents.load_roles() if r["kind"] == "orchestrator")
        notes = " ".join(
            render_agents.disclosures(role, host, render_agents.resolve_tools(role, host)[2])
        )
        self.assertIn("Which agents you may dispatch is **not enforced**", notes)

        generated = (CLAUDE_AGENTS / "orchestrator.md").read_text(encoding="utf-8")
        self.assertIn("Which agents you may dispatch is **not enforced**", generated)

        worker = (CLAUDE_AGENTS / "impl-executor.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "Which agents you may dispatch",
            worker,
            "a worker holds no delegation, so the disclosure is noise there",
        )


class MailboxTests(unittest.TestCase):
    """The four properties the mailbox exists to make true.

    Each test here fails if the property is removed from mailbox.py. They are
    written against behaviour, not implementation, so a rewrite that keeps the
    guarantees keeps the tests.
    """

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

    def post(self, **kwargs):
        kwargs.setdefault("workspace", str(self.workspace))
        kwargs.setdefault("run_id", "r1")
        kwargs.setdefault("persisted_by", "orchestrator")
        return mailbox.post(**kwargs)

    def dispatch_and_report(self, body=b"done\n"):
        self.post(
            kind="task",
            sender="orchestrator",
            recipient="worker:implementer",
            body=b"do the thing\n",
        )
        return self.post(
            kind="report", sender="worker:implementer", recipient="orchestrator", body=body
        )

    # --- verbatim ---------------------------------------------------------

    def test_body_survives_byte_for_byte(self):
        """Trailing whitespace, unicode and blank lines all survive.

        These are exactly what a well-meaning 'clean up the output' step
        destroys, and D5 exists because a reviewer needs the worker's words
        rather than a tidied paraphrase of them.
        """
        awkward = b"verdict   \n\xe2\x9c\x93 \xc3\xa9\ttab\n\n\n"
        path = self.dispatch_and_report(body=awkward)
        _, body = mailbox.parse_envelope(path.read_bytes())
        self.assertEqual(body, awkward)

    def test_an_edited_body_fails_verification(self):
        """Verbatim is checkable, not merely promised."""
        path = self.dispatch_and_report()
        with path.open("ab") as handle:
            handle.write(b"I never said this\n")

        problems = mailbox.verify(str(self.workspace), "r1")
        self.assertTrue(
            any("does not match its recorded hash" in p for p in problems),
            "a tampered envelope verified clean: %s" % problems,
        )

    # --- append-only ------------------------------------------------------

    def test_an_envelope_is_never_overwritten(self):
        self.post(
            kind="task", sender="orchestrator", recipient="worker:implementer", body=b"first\n"
        )
        with self.assertRaises(mailbox.MailboxError) as caught:
            self.post(
                kind="task",
                sender="orchestrator",
                recipient="worker:implementer",
                body=b"second\n",
                seq=1,
            )
        self.assertIn("append-only", str(caught.exception))

    def test_numbering_refuses_to_work_around_an_unreadable_envelope(self):
        """Skipping one silently reuses a sequence number.

        An earlier revision skipped, and two envelopes both came out as seq 1 -
        the module's own failure mode, committed by the module.
        """
        self.post(
            kind="task", sender="orchestrator", recipient="worker:implementer", body=b"fine\n"
        )
        broken = mailbox.mailbox_dir(str(self.workspace), "r1") / "0009-junk.md"
        broken.write_bytes(b"not an envelope at all\n")

        with self.assertRaises(mailbox.MailboxError) as caught:
            self.post(
                kind="report",
                sender="worker:implementer",
                recipient="orchestrator",
                body=b"hello\n",
            )
        self.assertIn("will not parse", str(caught.exception))

    # --- workers never write ----------------------------------------------

    def test_a_worker_cannot_be_recorded_as_the_writer(self):
        """D9. A worker holding a write tool is a grant that should not exist."""
        with self.assertRaises(mailbox.MailboxError) as caught:
            self.post(
                kind="report",
                sender="worker:implementer",
                recipient="orchestrator",
                persisted_by="worker:implementer",
                body=b"hello\n",
            )
        self.assertIn("persisted_by", str(caught.exception))

    def test_a_worker_may_still_be_the_author_of_its_report(self):
        """The worker's words are the worker's; only the writing is not."""
        path = self.dispatch_and_report()
        header, _ = mailbox.parse_envelope(path.read_bytes())
        self.assertEqual(header["from"], "worker:implementer")
        self.assertEqual(header["persisted_by"], "orchestrator")

    # --- silence is never success -----------------------------------------

    def test_a_dispatched_task_with_no_answer_is_a_problem(self):
        self.post(
            kind="task", sender="orchestrator", recipient="worker:implementer", body=b"do it\n"
        )
        problems = mailbox.verify(str(self.workspace), "r1")
        self.assertTrue(
            any("nothing came back" in p for p in problems),
            "a vanished task verified clean: %s" % problems,
        )

    def test_sealing_the_silence_resolves_it(self):
        self.post(
            kind="task", sender="orchestrator", recipient="worker:implementer", body=b"do it\n"
        )
        self.post(
            kind="failure",
            sender="worker:implementer",
            recipient="orchestrator",
            body=b"nothing returned\n",
            failure_mode="killed",
        )
        self.assertEqual(mailbox.verify(str(self.workspace), "r1"), [])

    def test_a_failure_envelope_must_name_its_mode(self):
        """'It failed' without saying how is the silence this replaces."""
        with self.assertRaises(mailbox.MailboxError) as caught:
            self.post(
                kind="failure",
                sender="worker:implementer",
                recipient="orchestrator",
                body=b"nope\n",
            )
        self.assertIn("failure_mode", str(caught.exception))

    # --- diagnostics, not tracebacks --------------------------------------

    def test_a_malformed_envelope_is_reported_not_raised_as_a_traceback(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/mailbox.py"),
                "--workspace",
                str(self.workspace),
                "verify",
                "--run-id",
                "r1",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)


class JobQueueTests(unittest.TestCase):
    """The deterministic half of the orchestrator, and its agreement with the
    mailbox.

    The queue and the mailbox are two records of the same run. Two records that
    can drift are worth less than one unless something compares them, so the
    cross-check gets as much attention here as the state machine.
    """

    RUN = "20260917-demo"

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.ws = str(self.workspace)
        self.preflight()

    def preflight(self, run_id=None, passed=True):
        """Put a startup-check record on file, because init now demands one.

        Written directly rather than by running root_preflight: these tests are
        about the queue, and the check's own behaviour is PreflightTests'
        subject. What this does assert, by existing at all, is that a run
        cannot be queued without it - remove this and every test below fails.
        """
        path = self.workspace / ".root-architect" / "preflight" / ("%s.json" % (run_id or self.RUN))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"run_id": run_id or self.RUN, "passed": passed, "refusals": []}) + "\n"
        )
        return path

    def seed(self, tasks=None):
        tasks = tasks or [
            {"name": "build-parser", "worker": "worker:implementer", "brief": "briefs/parser.json"},
            {
                "name": "check-plan",
                "worker": "worker:spec-validator",
                "brief": "briefs/parser.json",
            },
        ]
        return job_queue.init(self.ws, self.RUN, tasks)

    def answer(self, name="build-parser"):
        """Dispatch a task and post the envelope that answers it."""
        job_queue.mark(self.ws, self.RUN, name, "dispatched")
        path = mailbox.post(
            self.ws,
            self.RUN,
            "report",
            "worker:implementer",
            "orchestrator",
            "orchestrator",
            b"done\n",
        )
        job_queue.mark(self.ws, self.RUN, name, "returned", path.name)
        return path

    # --- the state machine ------------------------------------------------

    def test_transitions_are_monotonic(self):
        """A queue that can move backwards can revise its own history."""
        self.seed()
        self.answer()
        for backwards in ("dispatched", "returned"):
            with self.subTest(to=backwards):
                with self.assertRaises(job_queue.JobQueueError) as caught:
                    job_queue.mark(self.ws, self.RUN, "build-parser", backwards, "whatever.md")
                self.assertIn("monotonic", str(caught.exception))

    def test_an_answered_task_must_name_its_envelope(self):
        self.seed()
        job_queue.mark(self.ws, self.RUN, "build-parser", "dispatched")
        for state in ("returned", "failed"):
            with self.subTest(state=state):
                with self.assertRaises(job_queue.JobQueueError) as caught:
                    job_queue.mark(self.ws, self.RUN, "build-parser", state)
                # mark()'s own wording, not just any mention of an envelope:
                # validate() refuses this on save as well, so an assertion on
                # the word alone passed whether or not mark() checked at all.
                self.assertIn("needs the envelope that answered it", str(caught.exception))

    def test_only_one_task_is_out_at_a_time(self):
        """dispatch_state reads one open dispatch; two would blind the guard."""
        self.seed()
        job_queue.mark(self.ws, self.RUN, "build-parser", "dispatched")
        with self.assertRaises(job_queue.JobQueueError) as caught:
            job_queue.next_task(job_queue.load(self.ws, self.RUN))
        self.assertIn("still dispatched", str(caught.exception))

    def test_next_returns_tasks_in_order_then_nothing(self):
        self.seed()
        self.assertEqual(
            job_queue.next_task(job_queue.load(self.ws, self.RUN))["name"], "build-parser"
        )
        self.answer("build-parser")
        self.assertEqual(
            job_queue.next_task(job_queue.load(self.ws, self.RUN))["name"], "check-plan"
        )
        self.answer("check-plan")
        self.assertIsNone(job_queue.next_task(job_queue.load(self.ws, self.RUN)))

    def test_a_run_is_queued_once(self):
        """Re-initialising would discard what the earlier queue recorded."""
        self.seed()
        with self.assertRaises(job_queue.JobQueueError) as caught:
            self.seed()
        self.assertIn("already exists", str(caught.exception))

    def test_duplicate_task_names_are_refused(self):
        twice = [
            {"name": "same", "worker": "worker:implementer", "brief": "b.json"},
            {"name": "same", "worker": "worker:spec-validator", "brief": "b.json"},
        ]
        with self.assertRaises(job_queue.JobQueueError) as caught:
            job_queue.init(self.ws, self.RUN, twice)
        self.assertIn("twice", str(caught.exception))

    # --- agreement with the mailbox ---------------------------------------

    def test_a_sound_run_verifies(self):
        self.seed()
        self.answer()
        self.assertEqual(job_queue.verify(self.ws, self.RUN), [])

    def test_an_envelope_the_mailbox_does_not_have_is_caught(self):
        """The queue must not record work the record of the work lacks."""
        self.seed()
        job_queue.mark(self.ws, self.RUN, "build-parser", "dispatched")
        job_queue.mark(
            self.ws, self.RUN, "build-parser", "returned", "0002-report-worker-implementer.md"
        )

        problems = job_queue.verify(self.ws, self.RUN)
        self.assertTrue(
            any("not in the mailbox" in p for p in problems),
            "a queue citing a missing envelope verified clean: %s" % problems,
        )

    def test_an_unanswered_task_pointing_at_an_answer_is_caught(self):
        """Bookkeeping that would read as progress."""
        self.seed()
        path = job_queue.queue_path(self.ws, self.RUN)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["tasks"][0]["envelope"] = "0001-task-orchestrator.md"
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")

        problems = job_queue.verify(self.ws, self.RUN)
        self.assertTrue(
            any("already names an envelope" in p for p in problems),
            "a pending task citing an answer verified clean: %s" % problems,
        )

    def test_a_missing_queue_is_reported_not_raised_as_a_traceback(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/job_queue.py"),
                "--workspace",
                self.ws,
                "verify",
                "--run-id",
                self.RUN,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)


class AgentInterfaceTests(unittest.TestCase):
    """The interface gate, and proof that it is load-bearing.

    Every assertion here is written so that reverting the behaviour it guards
    makes it fail. A test that passes whether or not the gate works would be
    worse than no test, because it would certify the gate.
    """

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def run_gate(self, root=None):
        return subprocess.run(
            [sys.executable, str((root or ROOT) / "scripts/validate_interfaces.py")],
            capture_output=True,
            text=True,
            cwd=str(root or ROOT),
        )

    def sandbox(self):
        """A throwaway copy of the repository, for mutation."""
        dest = self.scratch / "tree"
        shutil.copytree(
            ROOT, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "dist")
        )
        return dest

    def interfaces(self):
        return sorted((ROOT / "adapters").glob("*/agent-interface.json"))

    def test_every_interface_is_schema_conformant_and_self_consistent(self):
        validator = Validator(ROOT / "schemas/agent-interface.schema.json")
        for path in self.interfaces():
            with self.subTest(host=path.parent.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(validator.validate(document), [])
                self.assertEqual(
                    document["host"],
                    path.parent.name,
                    "an interface must not describe a host it is not filed under",
                )

    def test_the_gate_passes_on_the_repository_as_it_stands(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_first_party_claims_carry_a_verbatim_quote(self):
        """A paraphrase is where inference re-enters."""
        for path in self.interfaces():
            document = json.loads(path.read_text(encoding="utf-8"))
            for trail, prov in validate_interfaces.walk_provenance(document, []):
                level = prov.get("level")
                if level in ("first-party-doc", "first-party-source"):
                    with self.subTest(host=document["host"], at=".".join(trail)):
                        self.assertTrue(
                            (prov.get("quote") or "").strip(),
                            "a first-party claim without the source's own words "
                            "is a claim nobody can re-check",
                        )

    def test_unsourced_claims_bear_no_weight(self):
        """`unsourced` must never carry evidence filed under the wrong level."""
        for path in self.interfaces():
            document = json.loads(path.read_text(encoding="utf-8"))
            for trail, prov in validate_interfaces.walk_provenance(document, []):
                if prov.get("level") == "unsourced":
                    with self.subTest(host=document["host"], at=".".join(trail)):
                        self.assertIsNone(prov.get("quote"))
                        self.assertIsNone(prov.get("source"))
                        self.assertTrue(
                            (prov.get("caveat") or "").strip(),
                            "an unsourced claim with no caveat cannot be told "
                            "apart from one nobody checked",
                        )

    def test_corpus_derived_claims_state_their_sample_size(self):
        for path in self.interfaces():
            document = json.loads(path.read_text(encoding="utf-8"))
            for trail, prov in validate_interfaces.walk_provenance(document, []):
                if prov.get("level") == "corpus-derived":
                    with self.subTest(host=document["host"], at=".".join(trail)):
                        self.assertIsInstance(prov.get("sample_size"), int)

    # --- mutation: each of these must FAIL the gate -----------------------

    def test_a_capability_going_unsourced_condemns_the_agent_already_shipped(self):
        """The finding this gate exists for, moved to where it still bites.

        It used to grant a worker `delegate` and expect a failure on cursor.
        Once render_agents learned to refuse a delegating role on a host whose
        nesting is unsourced, that pair stopped being built at all - and a test
        asserting a complaint about a combination that no longer exists would
        have passed while proving nothing.

        This is the case that stayed dangerous, and it is not hypothetical: the
        nesting cap is remotely defaulted, so the re-test protocol can downgrade
        claude-code's nesting to unsourced on any given day. When it does, the
        orchestrator file already on disk becomes an artifact resting on an
        assumption. The gate must condemn it rather than let the downgrade pass
        as a documentation change.
        """
        tree = self.sandbox()
        path = tree / "adapters/claude-code/agent-interface.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["delegation"]["nested"]["provenance"] = {
            "level": "unsourced",
            "caveat": "forced unsourced by a test",
        }
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        self.assertTrue(
            (tree / "adapters/claude-code/agents/orchestrator.md").exists(),
            "fixture broken: the built artifact this test attacks is gone",
        )

        result = self.run_gate(tree)
        self.assertEqual(
            result.returncode, 1, "a generated agent kept resting on unsourced nesting"
        )
        self.assertIn("orchestrator.md", result.stderr)
        self.assertIn("unsourced", result.stderr.lower())

    def test_gate_rejects_a_leftover_artifact_for_a_host_that_cannot_carry_it(self):
        """The drift the narrower scope opened up.

        A file left behind from when a role DID target a host is worse than a
        missing one: it looks generated and current.
        """
        tree = self.sandbox()
        stale = tree / "dist/cursor"
        stale.mkdir(parents=True, exist_ok=True)
        (stale / "orchestrator.md").write_text("stale\n", encoding="utf-8")

        result = self.run_gate(tree)
        self.assertEqual(
            result.returncode, 1, "a leftover agent file for an unsupported host passed"
        )
        self.assertIn("leftover", result.stderr)

    def test_gate_rejects_drift_between_interface_and_host_manifest(self):
        """The renderer trusts the manifest; the interface describes the host.

        When they disagree, a generated agent can claim a guarantee the host
        will not keep - so disagreement must not be silent.
        """
        tree = self.sandbox()
        path = tree / "adapters/claude-code/agent-interface.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["fields"]["tools"]["supported"] = False
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")

        result = self.run_gate(tree)
        self.assertEqual(
            result.returncode,
            1,
            "the interface contradicted hosts/claude-code.json and the gate allowed it",
        )
        self.assertIn("drift", result.stderr)

    def test_gate_rejects_a_first_party_claim_with_no_quote(self):
        """Strips the quote from whichever first-party claim comes first.

        Deliberately not pinned to a named field: a claim's provenance LEVEL
        legitimately changes as evidence improves, and an earlier version of
        this test broke when one was upgraded from first-party-doc to
        empirically-verified. Pinning would have made a real improvement look
        like a regression.
        """
        tree = self.sandbox()
        path = tree / "adapters/claude-code/agent-interface.json"
        document = json.loads(path.read_text(encoding="utf-8"))

        for _, prov in validate_interfaces.walk_provenance(document, []):
            if prov.get("level") in ("first-party-doc", "first-party-source"):
                prov.pop("quote")
                break
        else:
            self.fail(
                "no first-party claim to strip - the fixture this test "
                "depends on is gone, so it is no longer testing anything"
            )
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")

        result = self.run_gate(tree)
        self.assertEqual(
            result.returncode,
            1,
            "a first-party claim lost its quote and the gate still called the interface sound",
        )

    def test_gate_rejects_evidence_filed_under_unsourced(self):
        """An unsourced level carrying a source means the level is wrong."""
        tree = self.sandbox()
        path = tree / "adapters/cursor/agent-interface.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["delegation"]["nested"]["provenance"]["source"] = "https://example.invalid"
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")

        result = self.run_gate(tree)
        self.assertEqual(result.returncode, 1)

    def test_gate_reports_rather_than_crashes_on_malformed_json(self):
        """The error path must not error - this repository keeps closing that."""
        tree = self.sandbox()
        (tree / "adapters/cursor/agent-interface.json").write_text("{ not json", encoding="utf-8")

        result = self.run_gate(tree)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()


class RootAgentTests(unittest.TestCase):
    """Root as a main-thread agent, and the rules that keep that claim true.

    ADR 0003 D10. Root's isolation from the workers is one line of frontmatter
    - a dispatch scope the host enforces - so everything that produces that
    line is worth a test, and so is every way of producing it that would be a
    lie.
    """

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.host = render_agents.load_host("claude-code")
        self.root = next(r for _f, r in render_agents.load_roles() if r["kind"] == "root")

    def sandbox(self):
        """A throwaway copy. Numbered, because two per test is normal here -
        a rule usually has a violating half and a control half.
        """
        dest = self.scratch / ("tree%d" % len(list(self.scratch.iterdir())))
        shutil.copytree(
            ROOT, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "dist")
        )
        return dest

    def gate(self, root):
        return subprocess.run(
            [sys.executable, str(root / "scripts/validate_roles.py")],
            capture_output=True,
            text=True,
            cwd=str(root),
        )

    # --- dispatched or not, which decides what the host must support -------

    def test_root_is_the_only_agent_nobody_dispatches(self):
        for _f, role in render_agents.load_roles():
            with self.subTest(role=role["id"]):
                self.assertEqual(render_agents.is_dispatched(role), role["kind"] != "root")

    def test_root_does_not_need_nested_delegation(self):
        """The distinction that decides which hosts can carry root.

        A dispatched delegator needs NESTED delegation; root needs only
        delegation, because nothing spawned root. Cursor is the case that
        separates them: its nesting is unsourced, so the orchestrator may not
        be built there - and root's eligibility must not inherit that refusal.
        """
        orchestrator = next(
            r for _f, r in render_agents.load_roles() if r["kind"] == "orchestrator"
        )
        built, reason = render_agents.role_targets_host(orchestrator, "cursor")
        self.assertFalse(built)
        self.assertIn("nested delegation is unsourced", reason)

        built, reason = render_agents.role_targets_host(self.root, "cursor")
        self.assertTrue(built, reason)

    def test_root_is_refused_where_plain_delegation_is_unsourced(self):
        """The other direction: root still rests on something sourced."""
        tree = self.sandbox()
        path = tree / "adapters/cursor/agent-interface.json"
        interface = json.loads(path.read_text())
        interface["delegation"]["provenance"] = {
            "level": "unsourced",
            "caveat": "blanked for this test",
        }
        path.write_text(json.dumps(interface, indent=2))

        result = subprocess.run(
            [
                sys.executable,
                str(tree / "scripts/render_agents.py"),
                "--host",
                "cursor",
                "--out",
                str(self.scratch / "out"),
            ],
            capture_output=True,
            text=True,
            cwd=str(tree),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("skipped root-architect", result.stdout)
        self.assertIn("delegation is unsourced", result.stdout)

    # --- the scope line itself ---------------------------------------------

    def test_roots_grant_carries_the_host_enforced_scope(self):
        names, enforced, note = render_agents.delegation_scope(self.root, self.host)
        self.assertEqual(names, ["Agent(root-architect-execution:orchestrator)"])
        self.assertTrue(enforced)
        self.assertIn("Dispatch scope is enforced", note)

        generated = (CLAUDE_AGENTS / "root-architect.md").read_text(encoding="utf-8")
        self.assertIn(
            "tools: Read, Grep, Glob, Edit, Write, Bash, "
            "Agent(root-architect-execution:orchestrator)",
            generated,
        )

    def test_the_type_name_follows_the_plugin_manifest(self):
        """A wrong type name fails silently: it matches no agent at all.

        So it is derived from the plugin manifest rather than written twice. A
        rename that did not reach root's grant would leave root able to
        dispatch nothing, with a frontmatter that looks entirely correct.
        """
        tree = self.sandbox()
        manifest = tree / "adapters/claude-code/manifest.template.json"
        plugin = json.loads(manifest.read_text())
        plugin["name"] = "renamed-plugin"
        manifest.write_text(json.dumps(plugin, indent=2))

        result = subprocess.run(
            [
                sys.executable,
                str(tree / "scripts/render_agents.py"),
                "--host",
                "claude-code",
                "--out",
                str(self.scratch / "out"),
            ],
            capture_output=True,
            text=True,
            cwd=str(tree),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.scratch / "out/root-architect.md").read_text(encoding="utf-8")
        self.assertIn("Agent(renamed-plugin:orchestrator)", text)

    def test_the_same_syntax_is_a_guarantee_for_root_and_not_for_the_orchestrator(self):
        """The asymmetry the whole main-thread decision turns on.

        Read from the manifest's main_thread_only flag, not from the host's
        name. It was an `if host == "claude-code"` before root existed, which
        made the claim true by coincidence.
        """
        orchestrator = next(
            r for _f, r in render_agents.load_roles() if r["kind"] == "orchestrator"
        )
        _n, enforced, note = render_agents.delegation_scope(orchestrator, self.host)
        self.assertFalse(enforced)
        self.assertIn("Which agents you may dispatch is **not enforced**", note)

        relaxed = json.loads(json.dumps(self.host))
        relaxed["main_thread"]["delegate_scope"]["main_thread_only"] = False
        _n, enforced, note = render_agents.delegation_scope(orchestrator, relaxed)
        self.assertIsNone(note, "nothing to disclose once the scope binds here")

    def test_a_host_that_cannot_name_the_dispatch_tool_says_so(self):
        """Cursor maps no delegate tool, so root's scope is instruction only."""
        cursor = render_agents.load_host("cursor")
        names, enforced, note = render_agents.delegation_scope(self.root, cursor)
        self.assertEqual(names, [])
        self.assertFalse(enforced)
        self.assertIn("maps no tool name to delegation", note)

        generated = (ROOT / "dist/cursor/root-architect.md").read_text(encoding="utf-8")
        self.assertIn("maps no tool name to delegation", generated)

    # --- the startup prompt -------------------------------------------------

    def test_the_startup_prompt_is_auto_submitted_where_the_host_can(self):
        generated = (CLAUDE_AGENTS / "root-architect.md").read_text(encoding="utf-8")
        self.assertIn('initialPrompt: "Before anything else', generated)
        self.assertIn("## Startup", generated)

    def test_a_host_with_no_auto_submission_discloses_it(self):
        codex = render_agents.load_host("codex")
        self.assertIsNone(render_agents.main_thread_startup(codex))
        notes = " ".join(render_agents.disclosures(self.root, codex, []))
        self.assertIn("does not auto-submit a startup prompt", notes)

        claude = render_agents.main_thread_startup(self.host)
        self.assertEqual(claude, "initialPrompt")
        notes = " ".join(render_agents.disclosures(self.root, self.host, []))
        self.assertNotIn("does not auto-submit", notes)

    def test_the_startup_prompt_is_quoted(self):
        """Prose in frontmatter, where a colon-space silently changes the parse.

        Every other value the renderer writes comes from a constrained
        vocabulary. This one is a sentence, and an unquoted sentence containing
        ": " makes the frontmatter parse as something else - launching root
        without the check it exists to carry.
        """
        tree = self.sandbox()
        path = tree / "roles/root-architect.json"
        role = json.loads(path.read_text())
        role["launch"]["initial_prompt"] = 'note: run "the check" \\ now'
        path.write_text(json.dumps(role, indent=2))

        result = subprocess.run(
            [
                sys.executable,
                str(tree / "scripts/render_agents.py"),
                "--host",
                "claude-code",
                "--out",
                str(self.scratch / "out"),
            ],
            capture_output=True,
            text=True,
            cwd=str(tree),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        line = next(
            entry
            for entry in (self.scratch / "out/root-architect.md")
            .read_text(encoding="utf-8")
            .splitlines()
            if entry.startswith("initialPrompt:")
        )
        self.assertEqual(line, 'initialPrompt: "note: run \\"the check\\" \\\\ now"')

    # --- root returns nothing ----------------------------------------------

    def test_root_is_given_no_return_contract(self):
        """An agent with nobody above it has no schema to satisfy."""
        text = render_agents.render_markdown_yaml(self.root, self.host, "root-architect.json")
        self.assertIn("You return nothing to anybody", text)
        self.assertNotIn("```json", text)

    # --- the manifest rules validate_roles adds -----------------------------

    def test_launch_is_refused_on_a_dispatched_agent(self):
        tree = self.sandbox()
        path = tree / "roles/orchestrator.json"
        role = json.loads(path.read_text())
        role["launch"] = {"main_thread": True, "delegates_to": ["implementer"]}
        path.write_text(json.dumps(role, indent=2))

        result = self.gate(tree)
        self.assertEqual(result.returncode, 1)
        self.assertIn("only root is launched rather than dispatched", result.stdout + result.stderr)

    def test_root_may_not_dispatch_a_worker_directly(self):
        """The topology this architecture exists to prevent, in one field."""
        tree = self.sandbox()
        path = tree / "roles/root-architect.json"
        role = json.loads(path.read_text())
        role["launch"]["delegates_to"] = ["orchestrator", "implementer"]
        path.write_text(json.dumps(role, indent=2))

        result = self.gate(tree)
        self.assertEqual(result.returncode, 1)
        self.assertIn("reaches a worker is the topology", result.stdout + result.stderr)

    def test_a_scope_naming_an_agent_nobody_ships_is_refused(self):
        tree = self.sandbox()
        path = tree / "roles/root-architect.json"
        role = json.loads(path.read_text())
        role["launch"]["delegates_to"] = ["supervisor"]
        path.write_text(json.dumps(role, indent=2))

        result = self.gate(tree)
        self.assertEqual(result.returncode, 1)
        self.assertIn("which no role manifest fills", result.stdout + result.stderr)

    def test_the_manifest_and_the_shipped_guard_must_agree(self):
        """Either half alone is a claim; only together are they a boundary."""
        tree = self.sandbox()
        path = tree / "roles/root-architect.json"
        role = json.loads(path.read_text())
        role["must_not"] = [m for m in role["must_not"] if m != "interfere-with-dispatch"]
        path.write_text(json.dumps(role, indent=2))

        result = self.gate(tree)
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "the one prohibition the shipped hook enforces", result.stdout + result.stderr
        )

        tree = self.sandbox()
        for guard in tree.glob("adapters/*/hooks/root_write_guard.py"):
            guard.unlink()
        result = self.gate(tree)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no adapter ships hooks/root_write_guard.py", result.stdout + result.stderr)


class PreflightTests(unittest.TestCase):
    """ADR 0003 D11: the check that asks whether the boundary is in force.

    Root supplies the observation and this script supplies the verdict, so
    every test here is about the verdict. The one thing it cannot check is a
    root that lies to it, which is stated in the module and not tested because
    it is not true.
    """

    RUN = "20260917-pre"

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.ws = str(self.workspace)

    def observe(
        self,
        tools=("Read", "Grep", "Glob", "Edit", "Write", "Bash", "Agent"),
        agent_types=("root-architect-execution:orchestrator",),
        raw=None,
    ):
        path = self.workspace / "observed.json"
        path.write_text(
            raw
            if raw is not None
            else json.dumps({"tools": list(tools), "agent_types": list(agent_types)})
        )
        return str(path)

    def check(self, **kwargs):
        return root_preflight.run(self.ws, self.RUN, self.observe(**kwargs))

    # --- what it is derived from -------------------------------------------

    def test_expectations_come_from_the_manifests_not_a_second_list(self):
        expected = root_preflight.expectations("claude-code")
        self.assertEqual(expected["delegate_tools"], ["Agent"])
        self.assertEqual(expected["agent_types"], ["root-architect-execution:orchestrator"])

    # --- the two questions D11 names ---------------------------------------

    def test_a_sound_session_passes_and_is_recorded(self):
        record = self.check()
        self.assertTrue(record["passed"])
        on_disk = json.loads(root_preflight.record_path(self.ws, self.RUN).read_text())
        self.assertEqual(
            on_disk["observed"]["agent_types"], ["root-architect-execution:orchestrator"]
        )

    def test_a_missing_dispatch_tool_is_refused(self):
        """The depth cap, or a launch that was never a main-thread agent."""
        with self.assertRaises(root_preflight.PreflightError) as caught:
            self.check(tools=("Read", "Bash"))
        self.assertIn("dispatch tool is missing", str(caught.exception))

    def test_dispatching_more_than_the_scope_is_refused(self):
        """The failure the whole check exists for: the restriction did not bind."""
        with self.assertRaises(root_preflight.PreflightError) as caught:
            self.check(agent_types=("root-architect-execution:orchestrator", "general-purpose"))
        self.assertIn("types you were not granted", str(caught.exception))

    def test_a_scope_that_reaches_nothing_is_refused(self):
        with self.assertRaises(root_preflight.PreflightError) as caught:
            self.check(agent_types=())
        self.assertIn("cannot dispatch", str(caught.exception))

    def test_a_refusal_is_recorded_too(self):
        """A refused run and an unchecked one must not look the same after."""
        with self.assertRaises(root_preflight.PreflightError):
            self.check(agent_types=("anything",))
        record = json.loads(root_preflight.record_path(self.ws, self.RUN).read_text())
        self.assertFalse(record["passed"])
        self.assertTrue(record["refusals"])

    # --- fails closed -------------------------------------------------------

    def test_an_absent_observation_is_a_failure_not_a_pass(self):
        with self.assertRaises(root_preflight.PreflightError) as caught:
            root_preflight.run(self.ws, self.RUN, str(self.workspace / "nope.json"))
        self.assertIn("silence is not a pass", str(caught.exception))

    def test_a_malformed_observation_is_refused(self):
        for raw in (
            '{"tools": "Agent", "agent_types": []}',
            '{"tools": []}',
            '["Agent"]',
            "not json at all",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(root_preflight.PreflightError):
                    root_preflight.run(self.ws, self.RUN, self.observe(raw=raw))

    # --- and what it gates --------------------------------------------------

    def test_a_run_cannot_be_queued_without_a_passing_check(self):
        """What makes D11 a gate rather than advice."""
        tasks = [{"name": "t", "worker": "worker:implementer", "brief": "briefs/t.json"}]
        with self.assertRaises(job_queue.JobQueueError) as caught:
            job_queue.init(self.ws, self.RUN, tasks)
        self.assertIn("no startup check on record", str(caught.exception))

        with self.assertRaises(root_preflight.PreflightError):
            self.check(tools=("Read",))
        with self.assertRaises(job_queue.JobQueueError) as caught:
            job_queue.init(self.ws, self.RUN, tasks)
        self.assertIn("on record as FAILED", str(caught.exception))

        self.check()
        self.assertTrue(job_queue.init(self.ws, self.RUN, tasks).exists())

    def test_an_unreadable_record_proves_nothing(self):
        path = root_preflight.record_path(self.ws, self.RUN)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ truncated")
        ok, why = root_preflight.passed(self.ws, self.RUN)
        self.assertFalse(ok)
        self.assertIn("will not parse", why)

    def test_the_codex_bundle_can_install_itself(self):
        """The bundle is the whole deliverable, or it is a directory.

        Codex needs an explicit bootstrap after the plugin is added, so a
        bundle that ships the agents without the means to install them is
        useless in a way no byte gate would notice - `--check` proves the copy
        was faithful, not that the result can act. So this runs install.py from
        a copy of the bundle with nothing else on the path, and requires it to
        materialize every role.

        ADR 0001 calls Claude Code needing no installer "luck, not design".
        This is the test that luck does not extend to Codex.
        """
        bundle = self.workspace / "codex-bundle"
        shutil.copytree(ROOT / "dist/codex", bundle)
        target = self.workspace / "codex-target"

        result = subprocess.run(
            [
                sys.executable,
                str(bundle / "install.py"),
                "--target",
                str(target),
                "--plugin-root",
                "/opt/installed-plugin",
            ],
            capture_output=True,
            text=True,
            cwd=str(bundle),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        roles = sorted(r["id"] for _f, r in render_agents.load_roles())
        self.assertEqual(sorted(p.stem for p in target.glob("*.toml")), roles)

        # The plugin root reaches the generated file, because a worker that
        # cannot find its role prose has an agent file and no role.
        text = (target / "spec-validator.toml").read_text(encoding="utf-8")
        self.assertIn("/opt/installed-plugin/references/agents/", text)

    def test_the_codex_installer_refuses_rather_than_half_installing(self):
        """Neither position holds the plugin root: write nothing, say why.

        A half-populated .codex/agents is worse than an empty one - Codex would
        load whatever landed, and the roles that did not would simply be
        missing, with no error anywhere to say so.
        """
        lonely = self.workspace / "lonely"
        lonely.mkdir()
        shutil.copy2(ROOT / "adapters/codex/install.py", lonely / "install.py")
        target = self.workspace / "nothing-here"

        result = subprocess.run(
            [sys.executable, str(lonely / "install.py"), "--target", str(target)],
            capture_output=True,
            text=True,
            cwd=str(lonely),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot find the plugin root", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(target.exists(), "it created the target directory before giving up")

    def test_the_two_manifests_agree_with_each_other(self):
        """The defect `claude plugin validate` exists to catch, pinned here too.

        A version bump once moved plugin.json and left the marketplace entry
        behind. That gate still runs in CI, but it now has to be pointed at
        dist/claude-code: at the repository root the same command no longer
        validates a manifest at all, it switches to validating components and
        exits 0 either way. A check that keeps passing while no longer doing
        its job is the shape this repository refuses, so the agreement is
        asserted here where it cannot silently change mode.
        """
        adapter = ROOT / "adapters/claude-code"
        manifest = json.loads((adapter / "manifest.template.json").read_text(encoding="utf-8"))
        marketplace = json.loads(
            (adapter / "marketplace.template.json").read_text(encoding="utf-8")
        )
        entries = [p for p in marketplace["plugins"] if p["name"] == manifest["name"]]
        self.assertEqual(
            len(entries), 1, "the marketplace names no entry for %r" % manifest["name"]
        )
        self.assertEqual(
            entries[0]["version"],
            manifest["version"],
            "plugin.json and the marketplace entry disagree on the "
            "version; plugin.json wins at install time and the "
            "marketplace entry is silently ignored",
        )

    def test_the_check_runs_from_an_installed_bundle(self):
        """The gate has to work where the product runs, not only in the repo.

        roles/, hosts/ and adapters/ looked like development surface and were
        excluded from the bundle. They are not: three bundled scripts read
        them, and without them the capability gate the README tells root to run
        before dispatching reported that no role fills any position - while
        still exiting 0. A gate that cannot run in the product is worse than
        no gate, because the protocol goes on saying it ran.
        """
        # A copy, not dist/ itself: running these writes __pycache__, and the
        # bundle is byte-gated against a fresh build. An install is a copy
        # anyway, so this is also the truer shape of the test.
        bundle = self.workspace / "installed"
        shutil.copytree(ROOT / "dist/claude-code", bundle)
        for script, expected in (
            ("validate_roles.py", "capability gate passed"),
            ("validate_interfaces.py", "interfaces sound"),
        ):
            with self.subTest(script=script):
                result = subprocess.run(
                    [sys.executable, str(bundle / "scripts" / script)],
                    capture_output=True,
                    text=True,
                    cwd=str(bundle),
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(expected, result.stdout)

        result = subprocess.run(
            [
                sys.executable,
                str(bundle / "scripts/root_preflight.py"),
                "--workspace",
                self.ws,
                "--run-id",
                self.RUN,
                "--observed",
                self.observe(),
            ],
            capture_output=True,
            text=True,
            cwd=str(bundle),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("the boundary holds", result.stdout)

    def test_the_cli_refuses_to_invent_an_observation(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/root_preflight.py"),
                "--workspace",
                self.ws,
                "--run-id",
                self.RUN,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("it cannot make one", result.stderr)
