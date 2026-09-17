#!/usr/bin/env python3
"""Install the built bundle into a throwaway HOME and prove its parts resolve.

`build_adapter.py --check` proves `dist/<host>/` agrees byte for byte with the
sources it claims to come from. That is a statement about *copying*, and it is
silent about the only question an installer actually asks: does the host load
this? A bundle can be byte-perfect and still fail to install -- a manifest the
host parses but rejects, an `agents/` directory the host looks for somewhere
else, a skill whose folder name no longer matches its frontmatter. Every one of
those passes a byte comparison and breaks a real install.

So this is the gate that runs the host against the artifact. It adds the built
bundle as a marketplace, installs it, asks the host to enumerate what it found,
and fails unless every role in `roles/` came back as an agent and the skill came
back as a skill. The expectations are derived, never hard-coded: add a fourth
role and this gate demands a fourth agent without being edited.

Everything happens inside a temporary HOME. The contributor's own plugin
configuration is never read and never written, which is what makes this safe to
put in an outcome gate people run locally rather than only in CI.

What it deliberately does NOT prove: that the two PreToolUse hooks enforce
anything. Hooks are read at session start, so an install mid-session leaves them
installed and inert, and no amount of installing inside one process changes
that. The hook is asserted to be *registered*; whether it fires is the guards'
own test suite's job.

    smoke_install.py --host claude-code
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = ROOT / "dist"


class SmokeError(Exception):
    """The bundle built, and the host would not load it."""


def expectations(host):
    """What the host must report back, derived from the sources.

    Derived rather than listed so the gate cannot quietly stop covering a role
    somebody adds later.
    """
    roles = sorted(p.stem for p in (ROOT / "roles").glob("*.json"))
    if not roles:
        raise SmokeError("no roles found; nothing to expect")
    adapter = ROOT / "adapters" / host
    manifest = json.loads(
        (adapter / "manifest.template.json").read_text(encoding="utf-8"))
    # hooks.json nests the events under a "hooks" key. Reading the top level
    # yielded the literal string "hooks", which then matched the report's own
    # "Hooks (1)" heading -- an assertion that passed no matter what shipped.
    # That is the vacuous-coverage failure this repository has rejected before,
    # so the event names are read from where they actually live.
    document = json.loads(
        (adapter / "hooks/hooks.json").read_text(encoding="utf-8"))
    events = sorted(document.get("hooks", {}))
    if not events:
        raise SmokeError("adapters/%s/hooks/hooks.json declares no events to "
                         "look for" % host)
    return {
        "plugin": manifest["name"],
        "version": manifest["version"],
        "agents": roles,
        "hooks": events,
    }


def hook_targets(bundle):
    """Every script hooks.json points at, resolved inside the bundle.

    Registration is not the same as reachability. Deleting a guard script while
    leaving hooks.json intact produces a bundle the host installs happily and
    reports the hook for -- and the guard then fails the first time it fires,
    which for this plugin means the only enforcement it has. build_adapter.py
    --check would also catch the missing file, but a gate that claims to prove
    installability should not depend on a different gate for the part that
    makes the install useful.
    """
    manifest = bundle / "hooks/hooks.json"
    if not manifest.is_file():
        raise SmokeError(
            "the bundle ships no hooks/hooks.json, so it registers no guards "
            "at all. This plugin's entire enforcement story is those two "
            "PreToolUse hooks.")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SmokeError("the bundle's hooks/hooks.json cannot be read: %s" % e)
    missing = []
    for entries in document.get("hooks", {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                for raw in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"\']+)",
                                      hook.get("command", "")):
                    if not (bundle / raw).is_file():
                        missing.append(raw)
    return sorted(set(missing))


def component_inventory(report):
    """Just the inventory block, never the prose around it.

    Every assertion here searches this slice rather than the whole report,
    because the plugin's own description names its parts: it says "Two
    PreToolUse hooks enforce...", so a substring search over the full text
    reported a hook as registered even when the bundle shipped none. A probe
    that deleted hooks.json passed. Narrowing the haystack is what makes the
    assertion mean what it says.
    """
    match = re.search(r"^Component inventory$(.*?)^\s*$", report,
                      re.M | re.S)
    if not match:
        raise SmokeError(
            "the host's output has no component inventory to check; its "
            "format may have changed, and this gate must not pass on a "
            "report it cannot read:\n\n%s" % report.strip())
    return match.group(1)


def run(args, home, timeout=180):
    environment = dict(os.environ, HOME=str(home))
    return subprocess.run(args, capture_output=True, text=True,
                          env=environment, cwd=str(home), timeout=timeout)


def smoke(host, bundle=None):
    bundle = Path(bundle) if bundle else DIST / host
    if not bundle.is_dir():
        raise SmokeError("no bundle at %s; run build_adapter.py --host %s first"
                         % (bundle, host))
    if shutil.which("claude") is None:
        return None  # caller decides whether an absent CLI is fatal

    want = expectations(host)

    unreachable = hook_targets(bundle)
    if unreachable:
        raise SmokeError(
            "hooks.json points at scripts the bundle does not ship: %s. The "
            "host would register the hook and the guard would fail the first "
            "time it fired." % ", ".join(unreachable))

    with tempfile.TemporaryDirectory() as scratch:
        home = Path(scratch) / "home"
        home.mkdir()

        added = run(["claude", "plugin", "marketplace", "add", str(bundle)], home)
        if added.returncode != 0:
            raise SmokeError("the host refused the bundle as a marketplace:\n%s"
                             % (added.stdout + added.stderr).strip())

        target = "%s@%s" % (want["plugin"], want["plugin"])
        installed = run(["claude", "plugin", "install", target], home)
        if installed.returncode != 0:
            raise SmokeError("the host refused to install the bundle:\n%s"
                             % (installed.stdout + installed.stderr).strip())

        listed = run(["claude", "plugin", "details", want["plugin"]], home)
        if listed.returncode != 0:
            raise SmokeError("the host installed the bundle but cannot describe "
                             "it:\n%s" % (listed.stdout + listed.stderr).strip())
        report = listed.stdout

    inventory = component_inventory(report)

    missing = [name for name in want["agents"]
               if not re.search(r"\b%s\b" % re.escape(name), inventory)]
    if missing:
        raise SmokeError(
            "installed, but the host did not report these agents: %s\n\n%s"
            % (", ".join(missing), report.strip()))

    if not re.search(r"Skills\s*\(\s*[1-9]", inventory):
        raise SmokeError("installed, but the host reported no skills:\n\n%s"
                         % report.strip())

    for hook in want["hooks"]:
        if not re.search(r"Hooks\s*\(\s*[1-9][^\n]*\b%s\b" % re.escape(hook),
                         inventory):
            raise SmokeError(
                "installed, but the host did not register the %s hook. The "
                "guards are the plugin's only enforcement; a bundle that ships "
                "without them installs clean and protects nothing.\n\n%s"
                % (hook, report.strip()))

    return want, report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="claude-code")
    parser.add_argument("--bundle", help="defaults to dist/<host>")
    parser.add_argument(
        "--require-cli", action="store_true",
        help="fail instead of skipping when the claude CLI is absent; CI sets "
             "this so a runner without the CLI cannot silently pass the gate")
    args = parser.parse_args(argv)

    try:
        outcome = smoke(args.host, args.bundle)
    except subprocess.TimeoutExpired as e:
        print("smoke install timed out: %s" % e, file=sys.stderr)
        return 1
    except SmokeError as e:
        print("smoke install FAILED: %s" % e, file=sys.stderr)
        return 1

    if outcome is None:
        message = ("the claude CLI is not on PATH, so it is unproven that the "
                   "built bundle installs and that its agents, skill and hooks "
                   "resolve")
        if args.require_cli:
            print("smoke install FAILED: %s" % message, file=sys.stderr)
            return 1
        print("smoke install SKIPPED: %s" % message)
        return 0

    want, _report = outcome
    print("installs clean: %s %s -> %d agents (%s), skill present, hooks %s"
          % (want["plugin"], want["version"], len(want["agents"]),
             ", ".join(want["agents"]), ", ".join(want["hooks"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
