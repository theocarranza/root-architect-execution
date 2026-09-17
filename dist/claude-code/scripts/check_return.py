#!/usr/bin/env python3
"""Validate one worker's return against its contract before root acts on it.

This is the validation gate. A worker return is data, not instruction: root
reads the verdict, never the worker's reasoning about what root should do next.
Checking the shape mechanically is what stops a plausible-sounding paragraph
from standing in for a PASS.

    check_return.py --role implementer      --file return.txt
    check_return.py --role spec-validator   --file return.txt --task T3 --attempt 2

Beyond the JSON Schema, this enforces the cross-field rules a schema cannot
express, each of which has cost this workstream a real defect:

  * A DONE implementer report must carry both RED and GREEN counts. Tests
    written after the implementation prove the code runs, not that the test
    could ever fail.
  * findings is empty if and only if status is PASS.
  * A spec-validator verdict must rerun nothing: it has no shell by design, so
    a non-empty commands_rerun means the roles were combined.
  * A quality verdict's findings each need a concrete failure scenario.
  * The returned role must be the role root dispatched.

Exit 0 means the return is well-formed. Exit 1 means send it back; that
corrective retry does not consume an implementation attempt, because nothing
was implemented differently.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jsonschema_mini import Validator  # noqa: E402

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)

CONTRACT = {
    "implementer": "implementer-report.schema.json",
    "spec-validator": "validator-verdict.schema.json",
    "quality-validator": "validator-verdict.schema.json",
}


def extract(text):
    """Pull the single fenced JSON block out of a worker's reply."""
    blocks = FENCE.findall(text)
    if not blocks:
        stripped = text.strip()
        if stripped.startswith("{"):
            return stripped, None
        return None, ("no fenced json block found; the contract is one fenced "
                      "```json block and nothing else")
    if len(blocks) > 1:
        return None, ("found %d fenced blocks; return exactly one"
                      % len(blocks))
    return blocks[0], None


def cross_field_errors(payload, role, task, attempt):
    errors = []
    if task and payload.get("task") != task:
        errors.append("task: returned %r but root dispatched %r"
                      % (payload.get("task"), task))
    if attempt and payload.get("attempt") != attempt:
        errors.append("attempt: returned %r but root dispatched attempt %r"
                      % (payload.get("attempt"), attempt))

    if role == "implementer":
        if payload.get("status") == "DONE":
            tests = payload.get("tests") or {}
            for phase in ("red", "green"):
                if not tests.get(phase):
                    errors.append(
                        "tests.%s: a DONE report must carry observed %s counts; "
                        "a test written after the implementation proves nothing "
                        "about whether it can fail" % (phase, phase.upper()))
        return errors

    returned_role = payload.get("role")
    if returned_role != role:
        errors.append("role: returned %r but root dispatched %r"
                      % (returned_role, role))
    findings = payload.get("findings")
    status = payload.get("status")
    if status == "PASS" and findings:
        errors.append("status: PASS cannot carry findings")
    if status == "FINDINGS" and not findings:
        errors.append("status: FINDINGS must carry at least one finding")
    if role == "spec-validator" and payload.get("commands_rerun"):
        errors.append("commands_rerun: the plan-compliance validator has no "
                      "shell by design; a non-empty rerun list means the two "
                      "review roles were combined in one agent")
    if role == "quality-validator":
        for i, finding in enumerate(findings or []):
            if not finding.get("failure_scenario"):
                errors.append("findings[%d].failure_scenario: a quality finding "
                              "needs concrete inputs or state and the wrong "
                              "output that follows" % i)
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=sorted(CONTRACT))
    parser.add_argument("--file", required=True,
                        help="file holding the worker's reply, or '-' for stdin")
    parser.add_argument("--task")
    parser.add_argument("--attempt", type=int)
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.file == "-" else \
        Path(args.file).read_text(encoding="utf-8")

    raw, problem = extract(text)
    if problem:
        print("malformed return: %s" % problem, file=sys.stderr)
        return 1
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        print("malformed return: block is not valid JSON: %s" % exc,
              file=sys.stderr)
        return 1

    errors = Validator(SCHEMAS / CONTRACT[args.role]).validate(payload)
    errors += cross_field_errors(payload, args.role, args.task, args.attempt)
    if errors:
        print("malformed return, send it back once:", file=sys.stderr)
        for error in errors:
            print("  %s" % error, file=sys.stderr)
        return 1

    summary = payload.get("status")
    if args.role == "implementer":
        print("well-formed implementer report: %s" % summary)
    else:
        print("well-formed %s verdict: %s (%d findings)"
              % (args.role, summary, len(payload.get("findings") or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
