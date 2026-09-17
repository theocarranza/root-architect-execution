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

        if role["returns"] != "none":
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
        # Delegation is the orchestrator's defining capability and a worker's
        # defining prohibition, so the rule is keyed on kind rather than
        # applied blanket. Before the orchestrator existed the blanket rule was
        # correct; it is the discriminator that keeps it correct now.
        delegates = "delegate" in role["tools"]["allow"]
        if role["kind"] == "worker" and delegates:
            problems.append("roles/%s is a worker and grants delegate; only the "
                            "orchestrator dispatches" % role_file)
        if role["kind"] == "orchestrator" and not delegates:
            problems.append("roles/%s is the orchestrator and does not grant "
                            "delegate; it would have nothing to orchestrate"
                            % role_file)

        # `launch` belongs to the one agent that is launched rather than
        # dispatched. The schema cannot say this - it has no `not` - so the
        # rule lives here, where it can also say why.
        if role["kind"] != "root" and "launch" in role:
            problems.append("roles/%s declares launch, but only root is "
                            "launched rather than dispatched; a dispatched "
                            "agent has no launch of its own to describe"
                            % role_file)
        if role["kind"] == "root":
            check_root(role_file, role, problems)

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

    # No separate count cap over `kind`. A fourth worker would have to reuse one
    # of the three worker positions, and a second orchestrator the orchestrator
    # position, so the one-manifest-per-position check above already refuses
    # both. A cap here looked like defence in depth and was in fact unreachable:
    # mutation testing caught it passing whether present or not.
    return roles


def check_root(role_file, role, problems):
    """Root's own invariants, none of which the schema can reach.

    Each one is a way the boundary could be declared and not be there: a root
    that dispatches workers directly, a scope naming agents nobody ships, or a
    manifest that disagrees with the guard shipped to enforce it.
    """
    launch = role["launch"]
    if not launch.get("main_thread"):
        problems.append("roles/%s is root and does not declare main_thread; the "
                        "dispatch scope binds only for a main-thread agent, so "
                        "a root launched otherwise has no boundary" % role_file)

    positions = {r["role"] for _f, r in render_agents.load_roles()}
    for target in launch["delegates_to"]:
        if target not in positions:
            problems.append("roles/%s may dispatch %r, which no role manifest "
                            "fills; the scope would name an agent nobody ships"
                            % (role_file, target))
    if "implementer" in launch["delegates_to"]:
        problems.append("roles/%s lets root dispatch a worker directly. Work "
                        "flows root -> orchestrator -> workers; a root that "
                        "reaches a worker is the topology this architecture "
                        "exists to prevent" % role_file)

    # The manifest and the shipped guard have to agree about the one
    # prohibition the guard enforces. Either alone is a claim.
    if "interfere-with-dispatch" not in role["must_not"]:
        problems.append("roles/%s does not declare interfere-with-dispatch, but "
                        "the write guard refuses root's writes inside "
                        "an open dispatch. The agent file would omit the one "
                        "prohibition the shipped hook enforces" % role_file)
    # Two named positions, because this gate runs in two trees. In the
    # repository ADR 0001 step 3 put the hooks under adapters/<host>/hooks/,
    # one per host that ships them; in an installed bundle the layout has
    # already placed them at hooks/. Root's manifest is host-independent, so
    # what it needs is that SOME position holds the guard - a prohibition
    # nothing anywhere enforces is the claim this pairing exists to catch.
    guards = (sorted((ROOT / "adapters").glob("*/hooks/root_write_guard.py"))
              + [ROOT / "hooks" / "root_write_guard.py"])
    if not any(guard.is_file() for guard in guards):
        problems.append("roles/%s declares interfere-with-dispatch, but no "
                        "adapter ships hooks/root_write_guard.py to enforce it"
                        % role_file)


def check_host(name, roles, problems):
    host = render_agents.load_host(name)
    out_dir = ROOT / host["bundled_dir"]
    extension = ".toml" if host["format"] == "toml" else ".md"
    render = (render_agents.render_toml if host["format"] == "toml"
              else render_agents.render_markdown_yaml)

    for role_file, role in roles:
        allowed, reason = render_agents.role_targets_host(role, name)
        if not allowed:
            # Not a problem: the renderer deliberately does not build this role
            # here, and demanding the file would demand the thing the interface
            # gate refuses.
            if (out_dir / (role["id"] + extension)).exists():
                problems.append("%s: %s exists but should not - %s"
                                % (name, out_dir / (role["id"] + extension), reason))
            continue
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
