#!/usr/bin/env python3
"""Open, close, and inspect the dispatch state that both guard hooks read.

Root owns this script. A dispatch with status "open" under
<workspace>/.root-architect/state/ is the run's only active signal, exactly the
way the reference architecture keeps one durable checkpoint rather than a
scattering of flags.

    dispatch_state.py open   --workspace . --brief brief.json
    dispatch_state.py close  --workspace . --run-id 20260907-task-3 \\
                             --outcome accepted
    dispatch_state.py active --workspace .
    dispatch_state.py verify --workspace .

`open` refuses a second concurrent dispatch: the loop runs one dependent task at
a time, and two open dispatches would leave the write guard unable to say whose
paths it is protecting.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jsonschema_mini import Validator  # noqa: E402

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
STATE_SUBDIR = Path(".root-architect") / "state"


class DispatchStateError(Exception):
    """Raised when a dispatch state file cannot be read, parsed, or validated.

    Carries the path to the offending file and a list of human-readable error
    strings describing what went wrong.
    """

    def __init__(self, path, errors):
        self.path = path
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__(str(self))

    def __str__(self):
        return "%s:\n  %s" % (self.path, "\n  ".join(self.errors))


def state_dir(workspace):
    return Path(workspace).resolve() / STATE_SUBDIR


def _validate_dispatch(data, schema_path):
    """Validate dispatch data against schema, raising DispatchStateError on failure.

    Catches FileNotFoundError from missing schema files, and OSError/ValueError
    (including json.JSONDecodeError, a ValueError subclass) from schema files
    that exist but cannot be read or do not hold valid JSON, converting both
    into DispatchStateError so the guard hooks see a consistent exception type.
    """
    try:
        return Validator(schema_path).validate(data)
    except FileNotFoundError as e:
        raise DispatchStateError(schema_path, ["schema file not found: %s" % e])
    except (OSError, ValueError) as e:
        raise DispatchStateError(
            schema_path, ["schema file is not valid JSON: %s" % e])


def active_dispatch(workspace):
    """Return (path, dispatch) for the single open dispatch, or (None, None).

    Walks dispatch-*.json files in sorted order applying three validation rules
    and checks ALL files before returning, to ensure no unparseable records
    exist that might hide a corruption:

    (a) Unreadable or unparseable JSON, OR JSON that parses but whose top-level
        value is not an object (for example a list, null, a number, or a bare
        string) -> raise DispatchStateError, because the file cannot be proven
        to not be the open dispatch: a non-object top level has no readable
        `status` field either. Skipping it would reopen the fail-open hole this
        task removes: if it is actually the open dispatch, the guard would not
        see it.

    (b) Parses as JSON with status field 'closed' or 'aborted' -> SKIP it,
        because a record that is provably not open cannot change the answer to
        'is a delegation open?'. Its other fields may be malformed, but the
        status field is readable and definitive.

    (c) Parses and status is 'open', or status is missing/unrecognized -> FULLY
        VALIDATE against schema and raise DispatchStateError on any error,
        because we cannot trust the status field if others are corrupt.

    Returns (None, None) when the state directory is absent or contains no open
    dispatch records.
    """
    directory = state_dir(workspace)
    if not directory.is_dir():
        return None, None

    open_dispatch_found = None
    for candidate in sorted(directory.glob("dispatch-*.json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            # Rule (a): unreadable or unparseable -> raise
            raise DispatchStateError(candidate, ["not valid JSON: %s" % e])

        if not isinstance(data, dict):
            # Rule (a): parsed but not an object -> raise, same reasoning as
            # unparseable JSON since there is no readable `status` field.
            raise DispatchStateError(
                candidate,
                ["JSON parsed but is not an object (got %s)"
                 % type(data).__name__])

        status = data.get("status")
        if status in ("closed", "aborted"):
            # Rule (b): provably archived -> skip without further validation
            continue

        # Rule (c): open or unrecognized status -> fully validate
        errors = _validate_dispatch(data, SCHEMAS / "dispatch.schema.json")
        if errors:
            raise DispatchStateError(candidate, errors)

        if status == "open" and open_dispatch_found is None:
            open_dispatch_found = (candidate, data)

    return open_dispatch_found if open_dispatch_found else (None, None)


def _fail(message):
    print("blocked: %s" % message, file=sys.stderr)
    return 1


def cmd_open(args):
    brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
    errors = Validator(SCHEMAS / "brief.schema.json").validate(brief)
    if brief.get("attempt", 1) > 1 and not brief.get("escalation_reason"):
        errors.append("$.escalation_reason: required once attempt > 1")
    if errors:
        return _fail("brief is not schema-conformant:\n  " + "\n  ".join(errors))

    try:
        existing_path, existing = active_dispatch(args.workspace)
    except DispatchStateError as e:
        return _fail("state file corrupted: %s" % e)

    if existing:
        return _fail(
            "dispatch %s is still open (%s). One dependent task at a time; "
            "close it before opening another." % (existing["run_id"], existing_path)
        )

    dispatch = {
        "schema_version": 1,
        "run_id": args.run_id,
        "status": "open",
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "brief": brief,
    }
    try:
        errors = _validate_dispatch(dispatch, SCHEMAS / "dispatch.schema.json")
    except DispatchStateError as e:
        return _fail("dispatch is not schema-conformant: %s" % e)

    if errors:
        return _fail("dispatch is not schema-conformant:\n  " + "\n  ".join(errors))

    directory = state_dir(args.workspace)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ("dispatch-%s.json" % args.run_id)
    target.write_text(json.dumps(dispatch, indent=2) + "\n", encoding="utf-8")
    print("open %s" % target)
    print("root write guard now protects: %s"
          % (", ".join(brief["write_paths"]) or "(no write paths)"))
    return 0


def cmd_close(args):
    directory = state_dir(args.workspace)
    target = directory / ("dispatch-%s.json" % args.run_id)
    if not target.exists():
        return _fail("no dispatch %s under %s" % (args.run_id, directory))

    try:
        dispatch = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _fail("cannot read state file %s: %s" % (target, e))

    try:
        errors = _validate_dispatch(dispatch, SCHEMAS / "dispatch.schema.json")
    except DispatchStateError as e:
        return _fail("state file is corrupted: %s" % e)

    if errors:
        return _fail("state file is corrupted at %s:\n  %s" % (target, "\n  ".join(errors)))

    if dispatch["status"] != "open":
        return _fail("dispatch %s is already %s" % (args.run_id, dispatch["status"]))

    dispatch["status"] = "aborted" if args.outcome == "blocked" else "closed"
    dispatch["closed_at"] = datetime.now(timezone.utc).isoformat()
    dispatch["outcome"] = args.outcome
    try:
        errors = _validate_dispatch(dispatch, SCHEMAS / "dispatch.schema.json")
    except DispatchStateError as e:
        return _fail("close would produce an invalid dispatch: %s" % e)

    if errors:
        return _fail("close would produce an invalid dispatch:\n  "
                     + "\n  ".join(errors))
    target.write_text(json.dumps(dispatch, indent=2) + "\n", encoding="utf-8")
    print("%s %s (%s)" % (dispatch["status"], args.run_id, args.outcome))
    return 0


def cmd_active(args):
    try:
        path, dispatch = active_dispatch(args.workspace)
    except DispatchStateError as e:
        return _fail("state file corrupted: %s" % e)

    if not dispatch:
        print("no open dispatch")
        return 0
    brief = dispatch["brief"]
    print("open %s" % path)
    print("  task:        %s" % brief["task"])
    print("  role:        %s" % brief["role"])
    print("  attempt:     %d of %d" % (brief["attempt"], brief["max_attempts"]))
    print("  model:       %s" % brief["model"])
    print("  effort:      %s" % brief["effort"])
    print("  write paths: %s" % (", ".join(brief["write_paths"]) or "(none)"))
    return 0


def cmd_verify(args):
    """Report on every dispatch-*.json file, exiting 1 if any is corrupt.

    Unlike active_dispatch, verify reports on ALL files including archived
    records, because the complete picture is valuable in diagnostics and does
    not affect the guard hooks' decision. A schema-error in an archived record
    is still reported as CORRUPT.
    """
    directory = state_dir(args.workspace)
    if not directory.is_dir():
        print("no state directory: %s" % directory)
        return 0

    files = sorted(directory.glob("dispatch-*.json"))
    if not files:
        print("no dispatch files under %s" % directory)
        return 0

    exit_code = 0
    for candidate in files:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print("CORRUPT %s" % candidate)
            print("  not valid JSON: %s" % e)
            exit_code = 1
            continue

        try:
            errors = _validate_dispatch(data, SCHEMAS / "dispatch.schema.json")
        except DispatchStateError as e:
            # Schema file missing is also reported as CORRUPT in verify
            print("CORRUPT %s" % candidate)
            for error in e.errors:
                print("  %s" % error)
            exit_code = 1
            continue

        if errors:
            print("CORRUPT %s" % candidate)
            for error in errors:
                print("  %s" % error)
            exit_code = 1
        else:
            status = data.get("status", "unknown")
            run_id = data.get("run_id", "unknown")
            print("ok %s %s" % (status, run_id))

    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_open = sub.add_parser("open", help="open a dispatch from a brief file")
    p_open.add_argument("--workspace", default=".")
    p_open.add_argument("--brief", required=True)
    p_open.add_argument("--run-id", required=True)
    p_open.set_defaults(func=cmd_open)

    p_close = sub.add_parser("close", help="close or abort the open dispatch")
    p_close.add_argument("--workspace", default=".")
    p_close.add_argument("--run-id", required=True)
    p_close.add_argument(
        "--outcome", required=True,
        choices=["accepted", "findings-returned", "blocked", "attempts-exhausted"])
    p_close.set_defaults(func=cmd_close)

    p_active = sub.add_parser("active", help="show the open dispatch, if any")
    p_active.add_argument("--workspace", default=".")
    p_active.set_defaults(func=cmd_active)

    p_verify = sub.add_parser("verify", help="check all dispatch files for corruption")
    p_verify.add_argument("--workspace", default=".")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
