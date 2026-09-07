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


def state_dir(workspace):
    return Path(workspace).resolve() / STATE_SUBDIR


def active_dispatch(workspace):
    """Return (path, dispatch) for the single open dispatch, or (None, None)."""
    directory = state_dir(workspace)
    if not directory.is_dir():
        return None, None
    for candidate in sorted(directory.glob("dispatch-*.json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # An unreadable state file must not silently disable the guards.
            continue
        if data.get("status") == "open":
            return candidate, data
    return None, None


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

    existing_path, existing = active_dispatch(args.workspace)
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
    errors = Validator(SCHEMAS / "dispatch.schema.json").validate(dispatch)
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
    dispatch = json.loads(target.read_text(encoding="utf-8"))
    if dispatch["status"] != "open":
        return _fail("dispatch %s is already %s" % (args.run_id, dispatch["status"]))
    dispatch["status"] = "aborted" if args.outcome == "blocked" else "closed"
    dispatch["closed_at"] = datetime.now(timezone.utc).isoformat()
    dispatch["outcome"] = args.outcome
    errors = Validator(SCHEMAS / "dispatch.schema.json").validate(dispatch)
    if errors:
        return _fail("close would produce an invalid dispatch:\n  "
                     + "\n  ".join(errors))
    target.write_text(json.dumps(dispatch, indent=2) + "\n", encoding="utf-8")
    print("%s %s (%s)" % (dispatch["status"], args.run_id, args.outcome))
    return 0


def cmd_active(args):
    path, dispatch = active_dispatch(args.workspace)
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
