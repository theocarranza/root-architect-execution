#!/usr/bin/env python3
"""The job queue: the deterministic half of the orchestrator.

State lives at <workspace>/.root-architect/queue/<run-id>.json, beside the
dispatch state and the mailbox. The orchestrator drives this; it does not
replace the orchestrator's judgment. Ordering, state and bookkeeping live here
precisely so that the agent's attention goes to reading what came back.

    job_queue.py init   --run-id R --tasks-file plan.json
    job_queue.py next   --run-id R
    job_queue.py mark   --run-id R --task build-parser --state dispatched
    job_queue.py mark   --run-id R --task build-parser --state returned \\
                        --envelope 0002-report-worker-implementer.md
    job_queue.py status --run-id R
    job_queue.py verify --run-id R

Four rules this enforces rather than requests:

  * **Transitions are monotonic.** pending -> dispatched -> returned or failed,
    never backwards. A queue that can move a task back to pending can rewrite
    its own history into agreement with a later story.
  * **An answer needs its envelope.** A task cannot be recorded as returned or
    failed without naming the envelope that answered it. Otherwise the queue
    says work happened and nothing can be checked.
  * **One dispatch at a time.** `next` refuses while a task is still out,
    matching dispatch_state's rule - two open dispatches leave the write guard
    unable to say whose paths it is protecting.
  * **The queue must agree with the mailbox.** `verify` cross-checks: every
    envelope the queue names must actually exist. Two records that can drift
    are worth less than one, unless something compares them.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mailbox  # noqa: E402
from jsonschema_mini import SchemaError, Validator  # noqa: E402

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
QUEUE_SUBDIR = Path(".root-architect") / "queue"

# pending -> dispatched -> returned|failed. Nothing else, in either direction.
ALLOWED = {
    "pending": {"dispatched"},
    "dispatched": {"returned", "failed"},
    "returned": set(),
    "failed": set(),
}
TERMINAL = {"returned", "failed"}


class JobQueueError(Exception):
    """Raised when the queue cannot be read, advanced, or trusted.

    Carries a diagnostic rather than a traceback: every caller is a script the
    orchestrator runs between dispatches, and a traceback there says nothing
    about which task is wrong.
    """


def queue_path(workspace, run_id):
    return Path(workspace) / QUEUE_SUBDIR / ("%s.json" % run_id)


def _now():
    return datetime.now(timezone.utc).isoformat()


def load(workspace, run_id):
    path = queue_path(workspace, run_id)
    if not path.is_file():
        raise JobQueueError("no queue for run %s at %s" % (run_id, path))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobQueueError("%s will not parse: %s" % (path, exc))
    validate(document)
    return document


def validate(document):
    try:
        problems = Validator(SCHEMAS / "job-queue.schema.json").validate(document)
    except SchemaError as exc:
        raise JobQueueError("the job-queue schema itself will not load: %s" % exc)
    if problems:
        raise JobQueueError("queue is not schema-conformant: %s"
                            % "; ".join(str(p) for p in problems))

    seen = set()
    for task in document["tasks"]:
        if task["name"] in seen:
            raise JobQueueError(
                "task %r appears twice; names index envelopes and log lines, so "
                "a duplicate makes the record ambiguous" % task["name"])
        seen.add(task["name"])
        if task["state"] in TERMINAL and not task.get("envelope"):
            raise JobQueueError(
                "task %r is %s but names no envelope - an answered task with "
                "nothing to point at is a claim, not a record"
                % (task["name"], task["state"]))


def save(workspace, run_id, document):
    validate(document)
    path = queue_path(workspace, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def init(workspace, run_id, tasks):
    path = queue_path(workspace, run_id)
    if path.exists():
        raise JobQueueError(
            "%s already exists. A run's queue is created once: re-initialising "
            "would discard whatever the earlier one recorded." % path)
    document = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": _now(),
        "tasks": [dict(task, state="pending") for task in tasks],
    }
    return save(workspace, run_id, document)


def find(document, name):
    for task in document["tasks"]:
        if task["name"] == name:
            return task
    raise JobQueueError("no task named %r in run %s" % (name, document["run_id"]))


def next_task(document):
    """The next task to dispatch, or None, or a refusal.

    Refuses while one is still out. The orchestrator judging a return is the
    point of the layer, and it cannot judge two at once without the guards
    losing track of whose write paths are in force.
    """
    out = [t for t in document["tasks"] if t["state"] == "dispatched"]
    if out:
        raise JobQueueError(
            "task %r is still dispatched. Mark it returned or failed before "
            "dispatching another: the write guard reads one open dispatch, and "
            "two would leave it unable to say whose paths it protects."
            % out[0]["name"])
    for task in document["tasks"]:
        if task["state"] == "pending":
            return task
    return None


def mark(workspace, run_id, name, state, envelope=None):
    document = load(workspace, run_id)
    task = find(document, name)
    current = task["state"]

    if state not in ALLOWED:
        raise JobQueueError("unknown state %r" % state)
    if state not in ALLOWED[current]:
        raise JobQueueError(
            "task %r cannot go from %s to %s. Transitions are monotonic - a "
            "queue that can move a task backwards can revise its own history."
            % (name, current, state))
    if state in TERMINAL and not envelope:
        # validate() refuses this too, on save, so nothing inconsistent can be
        # written either way. This check exists for the message: the caller is
        # mid-operation and wants to know what to supply, not which invariant
        # the finished document breaks. Both are kept deliberately; the test
        # asserts THIS wording so the distinction stays load-bearing.
        raise JobQueueError(
            "marking %r as %s needs the envelope that answered it" % (name, state))

    task["state"] = state
    task["updated_at"] = _now()
    if envelope:
        task["envelope"] = envelope
    save(workspace, run_id, document)
    return task


def verify(workspace, run_id):
    """Every way the queue and the mailbox can disagree."""
    problems = []
    try:
        document = load(workspace, run_id)
    except JobQueueError as exc:
        return [str(exc)]

    try:
        envelopes = {p.name for p in mailbox.envelope_paths(
            mailbox.mailbox_dir(workspace, run_id))}
    except Exception as exc:  # pragma: no cover - defensive
        return ["cannot read the mailbox for run %s: %s" % (run_id, exc)]

    for task in document["tasks"]:
        name, state = task["name"], task["state"]
        envelope = task.get("envelope")
        if state in TERMINAL:
            if envelope not in envelopes:
                problems.append(
                    "task %r is %s and names envelope %r, which is not in the "
                    "mailbox. The queue records work the record of the work "
                    "does not contain." % (name, state, envelope))
        elif envelope:
            problems.append(
                "task %r is %s but already names an envelope - an unanswered "
                "task pointing at an answer is a bookkeeping error that would "
                "read as progress" % (name, state))

    dispatched = [t["name"] for t in document["tasks"] if t["state"] == "dispatched"]
    if len(dispatched) > 1:
        problems.append(
            "%d tasks are dispatched at once (%s); the loop runs one at a time"
            % (len(dispatched), ", ".join(dispatched)))

    return problems


def _fail(message):
    print("  %s" % message, file=sys.stderr)
    return 1


def cmd_init(args):
    try:
        tasks = json.loads(Path(args.tasks_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _fail("cannot read %s: %s" % (args.tasks_file, exc))
    if not isinstance(tasks, list):
        return _fail("%s must hold a list of tasks" % args.tasks_file)
    try:
        path = init(args.workspace, args.run_id, tasks)
    except JobQueueError as exc:
        return _fail(str(exc))
    print("queued %d task(s) in %s" % (len(tasks), path))
    return 0


def cmd_next(args):
    try:
        task = next_task(load(args.workspace, args.run_id))
    except JobQueueError as exc:
        return _fail(str(exc))
    if task is None:
        print("nothing pending in run %s" % args.run_id)
        return 0
    print(json.dumps(task, indent=2))
    return 0


def cmd_mark(args):
    try:
        task = mark(args.workspace, args.run_id, args.task, args.state, args.envelope)
    except JobQueueError as exc:
        return _fail(str(exc))
    print("%s -> %s" % (task["name"], task["state"]))
    return 0


def cmd_status(args):
    try:
        document = load(args.workspace, args.run_id)
    except JobQueueError as exc:
        return _fail(str(exc))
    for task in document["tasks"]:
        print("%-10s %-24s %-18s %s"
              % (task["state"], task["name"], task["worker"],
                 task.get("envelope", "")))
    return 0


def cmd_verify(args):
    problems = verify(args.workspace, args.run_id)
    if problems:
        for problem in problems:
            print("  %s" % problem, file=sys.stderr)
        print("\n%d problem(s) in run %s" % (len(problems), args.run_id),
              file=sys.stderr)
        return 1
    print("run %s: the queue and the mailbox agree" % args.run_id)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init")
    init_p.add_argument("--run-id", required=True)
    init_p.add_argument("--tasks-file", required=True)
    init_p.set_defaults(func=cmd_init)

    next_p = sub.add_parser("next")
    next_p.add_argument("--run-id", required=True)
    next_p.set_defaults(func=cmd_next)

    mark_p = sub.add_parser("mark")
    mark_p.add_argument("--run-id", required=True)
    mark_p.add_argument("--task", required=True)
    mark_p.add_argument("--state", required=True,
                        choices=["dispatched", "returned", "failed"])
    mark_p.add_argument("--envelope")
    mark_p.set_defaults(func=cmd_mark)

    status_p = sub.add_parser("status")
    status_p.add_argument("--run-id", required=True)
    status_p.set_defaults(func=cmd_status)

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--run-id", required=True)
    verify_p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
