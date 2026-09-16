#!/usr/bin/env python3
"""The capability gate: check the declarations, then check what they generated.

Run this before dispatching anything. It answers three questions that a run has
no cheap way to recover from getting wrong:

  1. Are the role and host manifests schema-conformant?
  2. Do the three loop roles exist, exactly once each?
  3. Does every generated host file still match the manifests it came from?

Question 3 is the one that bites. A hand-edit to a generated agent file survives
review, ships, and then silently disagrees with the manifest every checkpoint
quotes — so the run records a model or a grant that nothing applied.

    validate_roles.py               # every host with a manifest
    validate_roles.py --host codex  # one host
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_agents  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_ROLES = {"implementer", "spec-validator", "quality-validator"}


def check_roles(problems):
    roles = render_agents.load_roles()
    seen = {}
    for role_file, role in roles:
        seen.setdefault(role["role"], []).append(role_file)

        prose = ROOT / role["prose"]
        if not prose.exists():
            problems.append("roles/%s names prose at %s, which does not exist"
                            % (role_file, role["prose"]))

        contract = ROOT / "schemas" / role["returns"]
        if not contract.exists():
            problems.append("roles/%s returns %s, which does not exist"
                            % (role_file, role["returns"]))

        # A read-only role that grants a shell is a contradiction the schema
        # cannot catch: both halves are individually valid.
        if role["mutation"] == "read-only":
            for intent in ("run-commands", "edit-files", "create-files"):
                if intent in role["tools"]["allow"]:
                    problems.append(
                        "roles/%s is read-only but grants %s"
                        % (role_file, intent))
        if role["mutation"] == "read-and-run":
            for intent in ("edit-files", "create-files"):
                if intent in role["tools"]["allow"]:
                    problems.append(
                        "roles/%s is read-and-run but grants %s"
                        % (role_file, intent))
        if "delegate" in role["tools"]["allow"]:
            problems.append("roles/%s grants delegate; workers must not spawn "
                            "agents" % role_file)

        overlap = set(role["tools"]["allow"]) & set(role["tools"]["deny"])
        if overlap:
            problems.append("roles/%s both allows and denies %s"
                            % (role_file, ", ".join(sorted(overlap))))

        tiers = ["cheap", "mid", "strong"]
        chain = [role["model"]["default"]] + role["model"]["escalation"]
        if [tiers.index(t) for t in chain] != sorted(tiers.index(t) for t in chain):
            problems.append("roles/%s model escalation is not strictly "
                            "increasing: %s" % (role_file, " -> ".join(chain)))
        levels = ["low", "medium", "high", "xhigh", "max"]
        chain = [role["reasoning"]["default"]] + role["reasoning"]["escalation"]
        if [levels.index(t) for t in chain] != sorted(levels.index(t) for t in chain):
            problems.append("roles/%s effort escalation is not strictly "
                            "increasing: %s" % (role_file, " -> ".join(chain)))

    for missing in sorted(REQUIRED_ROLES - set(seen)):
        problems.append("no role manifest fills the %r position" % missing)
    for name, files in sorted(seen.items()):
        if len(files) > 1:
            problems.append("the %r position is filled %d times (%s); the loop "
                            "is a fixed three-agent architecture"
                            % (name, len(files), ", ".join(files)))
    return roles


def check_host(name, roles, problems):
    host = render_agents.load_host(name)
    out_dir = ROOT / host["bundled_dir"]
    extension = ".toml" if host["format"] == "toml" else ".md"
    render = (render_agents.render_toml if host["format"] == "toml"
              else render_agents.render_markdown_yaml)

    for role_file, role in roles:
        target = out_dir / (role["id"] + extension)
        if not target.exists():
            problems.append("%s: %s has not been generated (run render_agents.py "
                            "--host %s)" % (name, target, name))
            continue
        expected = render(role, host, role_file)
        if target.read_text(encoding="utf-8") != expected:
            problems.append("%s: %s no longer matches roles/%s and "
                            "hosts/%s.json; regenerate rather than hand-editing"
                            % (name, target, role_file, name))

    for field in host["required_fields"]:
        if field not in ("name", "description", "developer_instructions"):
            problems.append("%s: unrecognised required field %r; the renderer "
                            "does not know how to emit it" % (name, field))
    return host


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", action="append", dest="hosts")
    args = parser.parse_args(argv)

    problems = []
    roles = check_roles(problems)

    names = args.hosts or sorted(p.stem for p in (ROOT / "hosts").glob("*.json"))
    stale = []
    for name in names:
        host = check_host(name, roles, problems)
        if host and "INHERITED" in host["source"]:
            stale.append((name, host["verified_on"]))

    if problems:
        print("capability gate FAILED:", file=sys.stderr)
        for problem in problems:
            print("  %s" % problem, file=sys.stderr)
        return 1

    print("capability gate passed: %d roles, %d host(s) — %s"
          % (len(roles), len(names), ", ".join(names)))
    for name, date in stale:
        print("  note: hosts/%s.json is inherited and unverified since %s. Its "
              "disclosures may understate or overstate what that host enforces."
              % (name, date))
    return 0


if __name__ == "__main__":
    sys.exit(main())
