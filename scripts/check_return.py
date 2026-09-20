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
STRICT_FENCE = re.compile(
    r"\A[ \t\r\n]*```json[ \t]*\r?\n(?P<body>.*?)\r?\n```[ \t\r\n]*\Z", re.DOTALL
)

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
        return None, (
            "no fenced json block found; the contract is one fenced ```json block and nothing else"
        )
    if len(blocks) > 1:
        return None, ("found %d fenced blocks; return exactly one" % len(blocks))
    return blocks[0], None


def capture_provider_return(raw_body, encoding, provider_metadata):
    """Keep final text bytes and provider observations in distinct fields.

    This is intentionally not a formatter: callers receive the same bytes they
    supplied, including blank lines and CRLF.  Decoding happens only when the
    strict return contract needs to parse JSON.
    """
    if not isinstance(raw_body, bytes):
        raise ValueError("provider final text must be bytes")
    if encoding != "utf-8":
        raise ValueError("unsupported declared encoding: %r" % encoding)
    if not isinstance(provider_metadata, dict):
        raise ValueError("provider metadata must be an object")
    return {"body": raw_body, "encoding": encoding, "provider_metadata": dict(provider_metadata)}


def extract_strict(raw_body, encoding):
    """Parse exactly one JSON fence and reject any prose around it."""
    if not isinstance(raw_body, bytes):
        return None, "captured return body is not raw bytes"
    try:
        text = raw_body.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        return None, "captured return cannot be decoded as declared %s: %s" % (encoding, exc)
    match = STRICT_FENCE.fullmatch(text)
    if not match:
        return None, "strict return requires exactly one ```json fence and no extra prose"
    try:
        payload = json.loads(match.group("body"))
    except ValueError as exc:
        return None, "block is not valid JSON: %s" % exc
    if not isinstance(payload, dict):
        return None, "return JSON top level must be an object"
    return payload, None


def cross_field_errors(payload, role, task, attempt, observed_config=None):
    errors = []
    if not isinstance(payload, dict):
        return ["return JSON top level must be an object"]
    if task and payload.get("task") != task:
        errors.append("task: returned %r but root dispatched %r" % (payload.get("task"), task))
    if attempt and payload.get("attempt") != attempt:
        errors.append(
            "attempt: returned %r but root dispatched attempt %r"
            % (payload.get("attempt"), attempt)
        )

    if observed_config is not None:
        if not isinstance(observed_config, dict):
            errors.append("recorded observed configuration must be an object")
        else:
            for field in ("model", "effort"):
                observed = observed_config.get(field)
                if observed is not None and payload.get(field) != observed:
                    errors.append(
                        "%s: returned %r but controller recorded observed effective %r"
                        % (field, payload.get(field), observed)
                    )

    if role == "implementer":
        if payload.get("status") == "DONE":
            tests = payload.get("tests") or {}
            for phase in ("red", "green"):
                if not tests.get(phase):
                    errors.append(
                        "tests.%s: a DONE report must carry observed %s counts; "
                        "a test written after the implementation proves nothing "
                        "about whether it can fail" % (phase, phase.upper())
                    )
        return errors

    returned_role = payload.get("role")
    if returned_role != role:
        errors.append("role: returned %r but root dispatched %r" % (returned_role, role))
    findings = payload.get("findings")
    status = payload.get("status")
    if status == "PASS" and findings:
        errors.append("status: PASS cannot carry findings")
    if status == "FINDINGS" and not findings:
        errors.append("status: FINDINGS must carry at least one finding")
    if role == "spec-validator" and payload.get("commands_rerun"):
        errors.append(
            "commands_rerun: the plan-compliance validator has no "
            "shell by design; a non-empty rerun list means the two "
            "review roles were combined in one agent"
        )
    if role == "quality-validator":
        for i, finding in enumerate(findings or []):
            if not finding.get("failure_scenario"):
                errors.append(
                    "findings[%d].failure_scenario: a quality finding "
                    "needs concrete inputs or state and the wrong "
                    "output that follows" % i
                )
    return errors


def retain_raw_bytes(directory, envelope_id, raw_body):
    """Preserve malformed captured bytes before requesting any correction."""
    if not envelope_id or "/" in envelope_id or "\\" in envelope_id:
        raise ValueError("captured envelope identity is not a safe filename")
    destination = Path(directory)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = destination / (envelope_id + ".raw")
    if path.exists():
        raise ValueError("raw return already retained for envelope %s" % envelope_id)
    path.write_bytes(raw_body)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=sorted(CONTRACT))
    parser.add_argument(
        "--file", required=True, help="file holding the worker's reply, or '-' for stdin"
    )
    parser.add_argument("--task")
    parser.add_argument("--attempt", type=int)
    parser.add_argument(
        "--governed-envelope-id",
        help="captured-envelope identity required for governed validation; unsupported until controller identity exists",
    )
    parser.add_argument("--raw-retain-dir", help="where malformed governed raw bytes are retained")
    parser.add_argument("--observed-model")
    parser.add_argument("--observed-effort")
    parser.add_argument(
        "--legacy-file",
        action="store_true",
        help="validate an historic file only; it is not governed evidence",
    )
    args = parser.parse_args(argv)

    raw_body = sys.stdin.buffer.read() if args.file == "-" else Path(args.file).read_bytes()
    if args.governed_envelope_id:
        if not args.raw_retain_dir:
            print("governed return requires --raw-retain-dir", file=sys.stderr)
            return 1
        try:
            retain_raw_bytes(args.raw_retain_dir, args.governed_envelope_id, raw_body)
        except (OSError, ValueError) as exc:
            print("cannot retain malformed raw return: %s" % exc, file=sys.stderr)
            return 1
        # RuntimeService intentionally cannot authenticate a shared-user caller.
        # Do not read an arbitrary file and call it the captured identity.
        print(
            "governed return validation is unsupported: no authenticated controller service "
            "can load captured envelope %s by identity" % args.governed_envelope_id,
            file=sys.stderr,
        )
        return 1

    if not args.legacy_file:
        print(
            "governed return validation requires --governed-envelope-id; use --legacy-file "
            "only for historic, non-governed file validation",
            file=sys.stderr,
        )
        return 1

    try:
        text = raw_body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        print("malformed legacy return: cannot decode utf-8: %s" % exc, file=sys.stderr)
        return 1

    raw, problem = extract(text)
    if problem or raw is None:
        print("malformed return: %s" % (problem or "no return block"), file=sys.stderr)
        return 1
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        print("malformed return: block is not valid JSON: %s" % exc, file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("malformed legacy return: JSON top level must be an object", file=sys.stderr)
        return 1
    errors = Validator(SCHEMAS / CONTRACT[args.role]).validate(payload)
    observed = {
        key: value
        for key, value in (("model", args.observed_model), ("effort", args.observed_effort))
        if value is not None
    }
    errors += cross_field_errors(
        payload, args.role, args.task, args.attempt, observed_config=observed or None
    )
    if errors:
        print("malformed return, send it back once:", file=sys.stderr)
        for error in errors:
            print("  %s" % error, file=sys.stderr)
        return 1

    summary = payload.get("status")
    if args.role == "implementer":
        print("well-formed implementer report: %s" % summary)
    else:
        print(
            "well-formed %s verdict: %s (%d findings)"
            % (args.role, summary, len(payload.get("findings") or []))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
