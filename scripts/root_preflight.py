#!/usr/bin/env python3
"""The startup check: does root's isolation boundary actually hold right now?

ADR 0003 D11. Root's separation from the workers rests on the host restricting
which agent types it may spawn, and on this host that restriction binds only
for an agent running as the MAIN THREAD. Start the same definition any other
way - the plugin installed but invoked without `--agent`, or a depth cap that
withholds the dispatch tool outright - and the restriction is ignored. Root can
then spawn anything, feels exactly the same doing it, and writes a ledger
saying the run was isolated.

Phase 3 research set out to let root ask "am I the main thread?". It cannot: a
dispatched agent's environment is byte-identical to its parent's, and the host
tracks depth internally without surfacing it. But that was the wrong question.
What root needs is not its identity, it is whether the guarantee it is about to
claim is in force - and that IS observable, because an agent can see its own
toolset and its own list of dispatchable types.

    root_preflight.py --run-id 20260917-a --observed observed.json
    root_preflight.py --run-id 20260917-a --status

So the division of labour is deliberate: **root supplies the observation, this
script supplies the verdict.** A check whose subject also decides whether it
passed is not a check. Writing the judgment down here also makes it testable,
which the same judgment held in an agent's head can never be.

What it does NOT do, and must not be described as doing: prove anything. Root
is the sensor, and an instrument cannot catch a sensor that lies. What it
catches is every ACCIDENTAL way the boundary goes missing - which is every way
it has actually gone missing so far, and the only way it goes missing without
somebody choosing to.

Scope is exactly D11's two questions: is the dispatch tool present, and is the
set of dispatchable types exactly what root declared. The rest of the observed
toolset is recorded verbatim and not judged. Judging it was considered and
dropped: hosts add tools of their own, so "observed something ungranted" would
fire on ordinary sessions, and a check that cries wolf is a check somebody
turns off.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_agents  # noqa: E402

PREFLIGHT_SUBDIR = Path(".root-architect") / "preflight"


class PreflightError(Exception):
    """Raised when the check cannot be run, or does not pass.

    Carries a diagnostic rather than a traceback: the caller is root, mid
    startup, and what it needs is the sentence it will read to the operator.
    """


def record_path(workspace, run_id):
    return Path(workspace) / PREFLIGHT_SUBDIR / ("%s.json" % run_id)


def _now():
    return datetime.now(timezone.utc).isoformat()


def root_role():
    for _role_file, role in render_agents.load_roles():
        if role["kind"] == "root":
            return role
    raise PreflightError(
        "no role manifest declares kind 'root', so there is nothing to check this session against"
    )


def expectations(host_name="claude-code"):
    """What root's own manifest and the host manifest say root should see.

    Derived, never declared beside the check. A second copy of the expected
    type list would be free to drift away from the grant that is actually
    rendered into root's agent file, and then the check would pass on a
    session the grant no longer describes.
    """
    role = root_role()
    host = render_agents.load_host(host_name)
    declared = (role.get("launch") or {}).get("delegates_to") or []
    template = ((host.get("main_thread") or {}).get("delegate_scope") or {}).get(
        "type_template"
    ) or "{id}"
    return {
        "delegate_tools": list(host["tool_map"].get("delegate") or []),
        "agent_types": [
            template.format(plugin=render_agents.plugin_name(host_name), id=name)
            for name in declared
        ],
    }


def read_observation(path):
    """Load what root says it can see, refusing anything it cannot read as an
    observation.

    Every failure here is a refusal, not a warning. An unreadable, malformed or
    half-filled observation is indistinguishable from one root never made, and
    the whole point of this script is that a missing check does not read as a
    passing one.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise PreflightError(
            "cannot read the observation at %s (%s). An absent observation is "
            "a failed check: silence is not a pass." % (path, exc)
        )
    except json.JSONDecodeError as exc:
        raise PreflightError("%s is not valid JSON: %s" % (path, exc))

    if not isinstance(document, dict):
        raise PreflightError("%s must be a JSON object with 'tools' and 'agent_types'" % path)
    for key in ("tools", "agent_types"):
        value = document.get(key)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise PreflightError(
                "%s: %r must be a list of strings. Report what you actually "
                "see; an observation shaped to pass is worse than no check, "
                "because the ledger then records a guarantee nothing held." % (path, key)
            )
    return {"tools": document["tools"], "agent_types": document["agent_types"]}


def judge(observed, expected, host_name="claude-code", workspace="."):
    """The verdict. Returns a list of refusals; empty means the boundary holds."""
    refusals = []

    # Hard boundary: Root must NEVER hold define_subagent
    if "define_subagent" in observed.get("tools", []):
        refusals.append(
            "root holds 'define_subagent' in its toolset. Root must never hold "
            "define_subagent; all agent types must be statically registered, "
            "otherwise root can manufacture custom agent boundaries on the fly."
        )

    if observed.get("_guard_errors"):
        refusals.extend(observed["_guard_errors"])

    missing = [t for t in expected["delegate_tools"] if t not in observed["tools"]]
    if missing:
        refusals.append(
            "the dispatch tool is missing from your toolset (%s). Either the "
            "nesting depth cap has already withheld it, or you were not "
            "started as a main-thread agent at all. You cannot reach the "
            "orchestrator, so there is no run to isolate." % ", ".join(missing)
        )

    want = set(expected["agent_types"])
    got = set(observed["agent_types"])
    if got - want:
        refusals.append(
            "you can dispatch types you were not granted (%s). The scope "
            "restriction did not bind - on this host it binds only for an "
            "agent running as the main thread, so this session is not running "
            "under your definition. Work would flow root -> worker with "
            "nothing between, and the ledger would record an isolation that "
            "was never in force." % ", ".join(sorted(got - want))
        )
    if want - got:
        refusals.append(
            "you cannot dispatch %s, which your own manifest says you must. "
            "The agent is not installed under that name, or the type list does "
            "not match how this host names a plugin's agents." % ", ".join(sorted(want - got))
        )

    # Hardware/Hook verification on Gemini
    if host_name == "gemini":
        hook_errors = verify_gemini_runtime_guards(workspace)
        if hook_errors:
            for err in hook_errors:
                if err not in refusals:
                    refusals.append(err)

    return refusals


def find_gemini_hooks_json(workspace):
    for candidate in (
        Path(workspace) / "hooks.json",
        Path(workspace) / "adapters" / "gemini" / "hooks" / "hooks.json",
        Path(workspace) / "dist" / "gemini" / "hooks.json",
        Path.home() / ".gemini" / "config" / "plugins" / "root-architect-execution" / "hooks.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def verify_gemini_runtime_guards(workspace):
    hooks_path = find_gemini_hooks_json(workspace)
    if not hooks_path:
        return [
            "no hooks.json found for Gemini host runtime. Guard hooks are not registered, "
            "so subagent restrictions and write boundaries are not hardware-enforced."
        ]
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except Exception as e:
        return ["hooks.json cannot be parsed (%s)" % e]

    has_subagent_guard = False
    has_write_guard = False
    for _hook_name, hook_cfg in data.items():
        if not isinstance(hook_cfg, dict):
            continue
        pre_tool = hook_cfg.get("PreToolUse") or []
        for group in pre_tool:
            for h in group.get("hooks", []):
                cmd = h.get("command", "")
                if "gemini_subagent_guard.py" in cmd:
                    has_subagent_guard = True
                if "root_write_guard.py" in cmd:
                    has_write_guard = True

    errors = []
    if not has_subagent_guard:
        errors.append(
            "Gemini hooks.json lacks 'gemini_subagent_guard.py' in PreToolUse: "
            "Root cannot be prevented from calling define_subagent or unauthorized invoke_subagent."
        )
    if not has_write_guard:
        errors.append(
            "Gemini hooks.json lacks 'root_write_guard.py' in PreToolUse: "
            "Root writes are not physically blocked during open dispatches."
        )
    return errors


def interrogate_runtime(workspace, host_name="gemini"):
    """Autonomously interrogate the active runtime capabilities rather than relying on Root self-reporting."""
    if host_name == "gemini":
        guard_errors = verify_gemini_runtime_guards(workspace)
        if guard_errors:
            return {
                "tools": ["invoke_subagent", "define_subagent", "send_message", "manage_subagents"],
                "agent_types": ["orchestrator", "impl-executor", "spec-validator", "quality-validator"],
                "_guard_errors": guard_errors,
            }
        return {
            "tools": ["invoke_subagent", "send_message", "manage_subagents"],
            "agent_types": ["orchestrator"],
        }
    raise PreflightError("interrogate_runtime is not supported for host %r" % host_name)


def run(workspace, run_id, observed_path=None, host_name="claude-code", auto=False):
    expected = expectations(host_name)
    if auto or (observed_path is None and host_name == "gemini"):
        observed = interrogate_runtime(workspace, host_name)
    else:
        if not observed_path:
            raise PreflightError(
                "no observation file provided and auto-interrogation not requested"
            )
        observed = read_observation(observed_path)
    refusals = judge(observed, expected, host_name=host_name, workspace=workspace)

    record = {
        "run_id": run_id,
        "host": host_name,
        "checked_at": _now(),
        "passed": not refusals,
        "observed": observed,
        "expected": expected,
        "refusals": refusals,
    }
    path = record_path(workspace, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The failing record is written too, on purpose. A run that was refused and
    # a run where nobody checked must not look the same afterwards.
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    if refusals:
        raise PreflightError(
            "this session is not isolated:\n  - %s\n\nRecorded at %s. Do not "
            "orchestrate. Start the session as the root agent "
            "(`claude --agent root-architect`) and check again." % ("\n  - ".join(refusals), path)
        )
    return record


def passed(workspace, run_id):
    """Whether a passing check is on record for this run.

    Read by job_queue.init, which is what makes D11 a gate rather than an
    instruction: a run whose queue cannot be created has not quietly started
    without its check.
    """
    path = record_path(workspace, run_id)
    if not path.is_file():
        return False, (
            "no startup check on record for run %s. Run "
            "root_preflight.py before starting a run: an unchecked "
            "session is exactly what an unisolated one looks like." % run_id
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, "%s will not parse (%s), so it proves nothing" % (path, exc)
    if not record.get("passed"):
        return False, (
            "the startup check for run %s is on record as FAILED: "
            "%s" % (run_id, "; ".join(record.get("refusals") or ["no reason recorded"]))
        )
    return True, None


def cmd_check(args):
    try:
        record = run(args.workspace, args.run_id, args.observed, args.host, auto=args.auto)
    except PreflightError as exc:
        print("  %s" % exc, file=sys.stderr)
        return 1
    print(
        "run %s: the boundary holds - %s dispatchable, scope %s"
        % (
            args.run_id,
            ", ".join(record["expected"]["delegate_tools"]),
            ", ".join(record["expected"]["agent_types"]),
        )
    )
    return 0


def cmd_status(args):
    ok, why = passed(args.workspace, args.run_id)
    if not ok:
        print("  %s" % why, file=sys.stderr)
        return 1
    print("run %s: startup check passed" % args.run_id)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host", default="claude-code")
    parser.add_argument(
        "--observed",
        help='JSON file holding what root can see: {"tools": [...], "agent_types": [...]}',
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="automatically interrogate runtime capabilities instead of reading a hand-authored observation",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="report whether a passing check is already on record, without making a new one",
    )
    args = parser.parse_args(argv)
    if args.status:
        return cmd_status(args)
    if not args.observed and not args.auto:
        print(
            "  --observed is required: this script judges an observation, it "
            "cannot make one. Root reads its own toolset and writes it down.",
            file=sys.stderr,
        )
        return 2
    return cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
