#!/usr/bin/env python3
"""The interface gate: check what each host offers, then check we only rely on
what is actually sourced.

Two questions, and the second is the one that matters:

  1. Is every adapters/<host>/agent-interface.json schema-conformant, and does
     every claim in it carry provenance strong enough to hold the weight the
     claim is bearing?
  2. Does every role, on every host it could target, depend only on capabilities
     that host DECLARES and SOURCES?

Question 2 is the one this project learned the hard way. A role that withholds
delegation on a host with no tool allowlist is not withholding anything; a role
that requires nested delegation on a host where nesting is unsourced is a guess
wearing a guarantee's clothes. Both shipped, in prose, before anything checked.

The rule the whole file turns on: a claim may be relied upon only at the
strength of its weakest supporting source, and `unsourced` bears no weight at
all. Absence from a corpus is not absence from an interface.

    validate_interfaces.py                 # every host with an interface
    validate_interfaces.py --host cursor   # one host
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jsonschema_mini  # noqa: E402
import render_agents  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ADAPTERS = ROOT / "adapters"
SCHEMA = ROOT / "schemas" / "agent-interface.schema.json"

# Ordered weakest to strongest. `unsourced` is deliberately first and
# deliberately load-bearing: it is the only level that may never be depended on.
STRENGTH = {
    "unsourced": 0,
    "corpus-derived": 1,
    "empirically-verified": 2,
    "first-party-source": 3,
    "first-party-doc": 3,
}
QUOTE_REQUIRED = {"first-party-doc", "first-party-source"}


def interface_paths(host=None):
    if not ADAPTERS.is_dir():
        return []
    found = []
    for child in sorted(ADAPTERS.iterdir()):
        if host is not None and child.name != host:
            continue
        candidate = child / "agent-interface.json"
        if candidate.is_file():
            found.append(candidate)
    return found


def walk_provenance(node, trail):
    """Yield (path, provenance) for every provenance block in the document.

    Provenance can sit at any depth, so this walks rather than enumerating
    known locations. A new field added to the schema is covered automatically;
    enumerating would mean a new field silently escapes the check.
    """
    if isinstance(node, dict):
        if "level" in node and "provenance" not in node:
            yield trail, node
            return
        for key, value in node.items():
            if key == "provenance" and isinstance(value, dict):
                yield trail + [key], value
            else:
                yield from walk_provenance(value, trail + [key])


def check_provenance_shape(path, document, problems):
    """Conditional rules the JSON schema cannot express on its own."""
    for trail, prov in walk_provenance(document, []):
        where = "%s: %s" % (path.parent.name, ".".join(trail) or "<root>")
        level = prov.get("level")
        if level not in STRENGTH:
            problems.append("%s declares unknown provenance level %r" % (where, level))
            continue

        if level == "unsourced":
            # An unsourced claim carrying a source or a quote is a claim whose
            # author had evidence and filed it in the wrong place. Catch it,
            # because the level is what the gate reads, not the prose.
            for key in ("source", "quote", "sample_size"):
                if prov.get(key):
                    problems.append(
                        "%s is unsourced but carries %s - if there is evidence, "
                        "the level is wrong; if there is not, remove it" % (where, key))
            if not prov.get("caveat"):
                problems.append(
                    "%s is unsourced and gives no caveat - an unsourced claim must "
                    "say what was looked for and not found, or the next reader "
                    "cannot tell it from one nobody checked" % where)
            continue

        if not prov.get("source"):
            problems.append("%s is %s but names no source" % (where, level))
        if level in QUOTE_REQUIRED and not prov.get("quote"):
            problems.append(
                "%s is %s but carries no verbatim quote - a paraphrase is where "
                "inference re-enters" % (where, level))
        if level == "corpus-derived" and not prov.get("sample_size"):
            problems.append(
                "%s is corpus-derived but gives no sample_size - a claim from an "
                "unstated number of files cannot be weighed" % where)


def strength_of(prov):
    return STRENGTH.get((prov or {}).get("level"), 0)


def role_needs(role):
    """What a role's own declarations imply it needs from a host.

    Derived from the grant rather than declared beside it. A derived need
    changes when the grant changes; a declared one drifts away from it.
    """
    tools = role.get("tools", {})
    allow = set(tools.get("allow", []))
    deny = set(tools.get("deny", []))
    must_not = set(role.get("must_not", []))

    needs = {}
    if "delegate" in allow:
        # Every role in this project is DISPATCHED - root spawns it. So a role
        # granted delegate is a spawned agent that spawns, which is nested
        # delegation, not merely delegation. Deriving this from the grant is
        # deliberate: a separate `requires_nested_delegation` key would be a
        # second place to state one fact, free to drift away from the first.
        needs["delegation"] = "the role is granted delegate"
        needs["nested_delegation"] = (
            "the role is granted delegate, and every role here is itself "
            "dispatched - so it would be a spawned agent spawning")
    if "delegate" in deny or "spawn-agents" in must_not:
        needs["withhold_delegation"] = (
            "the role denies delegate or declares must_not spawn-agents")
    return needs


def check_role_against_host(role_file, role, path, document, problems):
    """Whether what is BUILT for this host rests on anything unsourced.

    The scope narrowed once render_agents learned to refuse a role a host
    cannot carry. Before that, this function had to catch "role needs nesting,
    host's nesting is unsourced" on its own. Now the renderer never builds that
    pair, so asking the question of an unbuilt pair would report a combination
    that does not exist - and skipping it would leave nothing behind.

    So the question is asked of the artifact instead: for every role that IS
    generated for this host, is every capability it depends on sourced? And for
    every role that is NOT, is the absence real rather than a stale file left
    looking current? The first is the guarantee; the second is the drift.
    """
    host = document["host"]
    needs = role_needs(role)
    where = "role %s on host %s" % (role_file, host)

    built, reason = render_agents.role_targets_host(role, host)
    artifact = generated_artifact(role, host)

    if not built:
        if artifact is not None and artifact.exists():
            problems.append(
                "%s: %s exists although the role is not built for this host "
                "(%s) - a leftover artifact reads as current"
                % (where, artifact, reason))
        return

    if "nested_delegation" in needs:
        nested = document.get("delegation", {}).get("nested", {})
        if strength_of(nested.get("provenance")) == 0:
            problems.append(
                "%s: %s, and an agent file IS generated here, but nested "
                "delegation is UNSOURCED on this host - a shipped artifact may "
                "not rest on an assumption" % (where, needs["nested_delegation"]))
        elif not nested.get("supported"):
            problems.append("%s: %s, but this host cannot nest delegation"
                            % (where, needs["nested_delegation"]))

    if "delegation" in needs:
        delegation = document.get("delegation", {})
        if not delegation.get("supported"):
            problems.append("%s: %s, but this host does not support delegation"
                            % (where, needs["delegation"]))
        elif strength_of(delegation.get("provenance")) == 0:
            problems.append("%s: %s, but this host's delegation support is unsourced"
                            % (where, needs["delegation"]))

    # A role that withholds delegation on a host with no tool allowlist is NOT
    # an error: render_agents already emits a disclosure saying the grant is an
    # instruction only. Disclosing an unenforceable guarantee is the designed
    # behaviour, so the gate must not reject it - it would be rejecting the
    # repository's own answer to this exact problem.


def generated_artifact(role, host):
    """Where this role's agent file lands for this host, or None if unknown.

    Checks for the manifest before loading it: load_host exits the process on a
    missing file rather than raising, which is right for a CLI and wrong to
    call speculatively. A host with an interface but no manifest renders
    nothing, so there is no artifact to look for.
    """
    if not (ROOT / "hosts" / ("%s.json" % host)).is_file():
        return None
    manifest = render_agents.load_host(host)
    extension = ".toml" if manifest["format"] == "toml" else ".md"
    return ROOT / manifest["bundled_dir"] / (role["id"] + extension)


# Concept -> the field names a host might spell it with. The interface file
# uses each host's OWN spelling, so a concept is looked up through aliases
# rather than a fixed key. Where a host has no such key at all, the interface
# records the concept name itself with supported:false, which is why the
# concept name is its own last alias.
CONCEPT_FIELDS = {
    "tool_allowlist": ["tools", "tool_allowlist"],
    "tool_denylist": ["disallowedTools", "tool_denylist"],
}


def concept_supported(document, concept):
    """True when any spelling of this concept is declared supported."""
    fields = document.get("fields", {})
    for alias in CONCEPT_FIELDS[concept]:
        if alias in fields:
            return bool(fields[alias].get("supported"))
    return None


def check_manifest_agreement(document, problems):
    """The interface describes the host; hosts/<host>.json tells the renderer
    what to emit. When they disagree, one of them is lying to the renderer -
    and the renderer is what decides whether a generated file states a
    guarantee or a disclosure.
    """
    host = document["host"]
    manifest_path = ROOT / "hosts" / ("%s.json" % host)
    if not manifest_path.is_file():
        # An interface may legitimately land before its host manifest does;
        # that is a gap to report, not a contradiction to fail on.
        print("  note: %s has an interface but no hosts/%s.json yet - nothing "
              "renders for this host" % (host, host))
        return

    manifest = json.loads(manifest_path.read_text())
    caps = manifest.get("capabilities", {})
    for concept, aliases in CONCEPT_FIELDS.items():
        declared = concept_supported(document, concept)
        if declared is None:
            problems.append(
                "%s: hosts/%s.json speaks about %s but the interface records no "
                "field for it under any of %s - record it with supported:false "
                "and a provenance rather than omitting it, so absence is not "
                "mistaken for nobody having looked"
                % (host, host, concept, "/".join(aliases)))
            continue
        if concept not in caps:
            continue
        if bool(caps[concept]["supported"]) != declared:
            problems.append(
                "%s: hosts/%s.json says %s supported=%s but the interface says "
                "%s - the renderer trusts the manifest, so this drift decides "
                "whether a generated agent claims a guarantee the host will not "
                "keep" % (host, host, concept, caps[concept]["supported"], declared))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="check one host instead of every one")
    args = parser.parse_args(argv)

    paths = interface_paths(args.host)
    if not paths:
        target = args.host or "any host"
        print("no agent-interface.json found for %s" % target, file=sys.stderr)
        return 1

    problems = []
    documents = []
    for path in paths:
        try:
            document = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            problems.append("%s is not valid JSON: %s" % (path.parent.name, exc))
            continue
        try:
            jsonschema_mini.validate_file(SCHEMA, document)
        except jsonschema_mini.SchemaError as exc:
            problems.append("%s fails the interface schema: %s" % (path.parent.name, exc))
            continue
        check_provenance_shape(path, document, problems)
        documents.append((path, document))

    roles = render_agents.load_roles()
    for path, document in documents:
        check_manifest_agreement(document, problems)
        for role_file, role in roles:
            check_role_against_host(role_file, role, path, document, problems)

    if problems:
        for problem in problems:
            print("  %s" % problem, file=sys.stderr)
        print("\n%d problem(s) across %d interface(s)"
              % (len(problems), len(paths)), file=sys.stderr)
        return 1

    print("interfaces sound: %d host(s), %d role(s) checked against each"
          % (len(documents), len(roles)))
    for path, document in documents:
        nested = document.get("delegation", {}).get("nested", {})
        level = (nested.get("provenance") or {}).get("level", "?")
        state = {True: "yes", False: "no", None: "unknown"}[nested.get("supported")]
        print("  %-12s nested delegation: %-7s (%s)" % (document["host"], state, level))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
