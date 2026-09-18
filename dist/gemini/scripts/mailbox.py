#!/usr/bin/env python3
"""The mailbox: append-only envelopes between root, the orchestrator and workers.

Envelopes are files under <workspace>/.root-architect/mailbox/<run-id>/, beside
the dispatch state the guards already read. One file per envelope, a metadata
header and then the body as literal bytes.

Four properties this script exists to make true rather than to request:

  * **Append-only.** `post` refuses a path that exists. An envelope is never
    rewritten, so history cannot be revised into agreement with a later story.
  * **Verbatim.** The body is written exactly as handed over - no trimming, no
    newline normalisation, no re-encoding - and the header carries its sha256.
    `verify` recomputes it, so an envelope edited afterwards fails rather than
    passing quietly. Verbatim is checkable here, not merely promised.
  * **Workers never write.** `persisted_by` cannot name a worker. A worker
    constrained enough to be trusted holds no write tool, so an envelope
    claiming a worker wrote it describes a grant that should not exist.
  * **Silence is never success.** `verify` reports a task with no answering
    report, and `seal-failure` turns a worker that died quietly into a record
    that says so.

    mailbox.py post --run-id R --kind report --from worker:implementer \\
                    --to orchestrator --persisted-by orchestrator --body-file f
    mailbox.py list   --run-id R
    mailbox.py verify --run-id R
    mailbox.py seal-failure --run-id R --from worker:implementer \\
                    --failure-mode killed
"""

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jsonschema_mini import SchemaError, Validator  # noqa: E402

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
MAILBOX_SUBDIR = Path(".root-architect") / "mailbox"

HEADER_OPEN = "<!-- root-architect envelope\n"
HEADER_CLOSE = "\n-->\n"
# Header values are one line each and never quoted. Anything needing escaping
# belongs in the body, which is the part with no format at all.
HEADER_LINE = re.compile(r"^([a-z0-9_]+): (.*)$")
INTEGER_KEYS = {"seq"}


class MailboxError(Exception):
    """Raised when an envelope cannot be written, read, or trusted.

    Carries a diagnostic rather than a traceback: every caller here is a script
    root runs between dispatches, and a traceback at that moment tells the
    operator nothing about which envelope is wrong.
    """


def mailbox_dir(workspace, run_id):
    return Path(workspace) / MAILBOX_SUBDIR / run_id


def _now():
    return datetime.now(timezone.utc).isoformat()


def render_header(header):
    lines = [HEADER_OPEN]
    for key in sorted(header):
        lines.append("%s: %s\n" % (key, header[key]))
    return "".join(lines).rstrip("\n") + HEADER_CLOSE


def parse_envelope(raw):
    """Split one envelope's bytes into (header dict, body bytes).

    The body is returned as bytes and never decoded here. Decoding and
    re-encoding is exactly where a 'verbatim' guarantee quietly stops being
    one, so the only thing that ever touches the body is a hash.
    """
    text = raw.decode("utf-8", errors="strict")
    if not text.startswith(HEADER_OPEN):
        raise MailboxError("envelope does not begin with an envelope header")
    end = text.find(HEADER_CLOSE)
    if end == -1:
        raise MailboxError("envelope header is never closed")

    header = {}
    for line in text[len(HEADER_OPEN) : end].split("\n"):
        if not line.strip():
            continue
        match = HEADER_LINE.match(line)
        if not match:
            raise MailboxError("envelope header line is not key: value -> %r" % line)
        key, value = match.group(1), match.group(2)
        header[key] = int(value) if key in INTEGER_KEYS and value.isdigit() else value

    body = raw[len((text[:end] + HEADER_CLOSE).encode("utf-8")) :]
    return header, body


def validate_header(header):
    try:
        problems = Validator(SCHEMAS / "envelope.schema.json").validate(header)
    except SchemaError as exc:
        raise MailboxError("the envelope schema itself will not load: %s" % exc)
    if problems:
        raise MailboxError(
            "envelope header is not schema-conformant: %s" % "; ".join(str(p) for p in problems)
        )
    if header["kind"] == "failure" and not header.get("failure_mode"):
        raise MailboxError(
            "a failure envelope must name its failure_mode - 'the worker "
            "failed' without saying how is the silence this envelope exists "
            "to replace"
        )
    if header["kind"] != "failure" and header.get("failure_mode"):
        raise MailboxError("failure_mode belongs only on a failure envelope")


def envelope_paths(directory):
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix == ".md")


def next_seq(directory):
    """The next free position, or a refusal.

    An envelope that will not parse is NOT skipped. Skipping one means the
    highest seq is unknown, the next write collides, and the collision is
    invisible - which is the failure this module exists to prevent, committed
    by the module itself. An earlier revision did exactly that, and two
    envelopes both came out as seq 1.
    """
    highest = 0
    for path in envelope_paths(directory):
        try:
            header, _ = parse_envelope(path.read_bytes())
        except MailboxError as exc:
            raise MailboxError(
                "cannot number a new envelope: %s will not parse (%s). Repair "
                "or remove it first - numbering around an unreadable envelope "
                "silently reuses a sequence number." % (path.name, exc)
            )
        highest = max(highest, int(header.get("seq", 0)))
    return highest + 1


def post(
    workspace, run_id, kind, sender, recipient, persisted_by, body, failure_mode=None, seq=None
):
    directory = mailbox_dir(workspace, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    seq = next_seq(directory) if seq is None else seq

    header = {
        "run_id": run_id,
        "seq": seq,
        "kind": kind,
        "from": sender,
        "to": recipient,
        "persisted_by": persisted_by,
        "created_at": _now(),
        "body_sha256": hashlib.sha256(body).hexdigest(),
    }
    if failure_mode:
        header["failure_mode"] = failure_mode
    validate_header(header)

    safe_sender = sender.replace(":", "-")
    path = directory / ("%04d-%s-%s.md" % (seq, kind, safe_sender))
    if path.exists():
        raise MailboxError(
            "%s already exists. Envelopes are append-only: a run that needs to "
            "correct an earlier one posts a new envelope saying so, because a "
            "rewritten history cannot be told from an accurate one." % path.name
        )

    with path.open("wb") as handle:
        handle.write(render_header(header).encode("utf-8"))
        handle.write(body)
    return path


def read_all(workspace, run_id):
    out = []
    for path in envelope_paths(mailbox_dir(workspace, run_id)):
        header, body = parse_envelope(path.read_bytes())
        out.append((path, header, body))
    return out


def verify(workspace, run_id):
    """Every way an envelope can lie, checked."""
    problems = []
    seen_seq = {}
    tasks = {}
    answered = set()

    directory = mailbox_dir(workspace, run_id)
    if not directory.is_dir():
        return ["no mailbox at %s - the run never opened one" % directory]

    for path in envelope_paths(directory):
        name = path.name
        try:
            header, body = parse_envelope(path.read_bytes())
            validate_header(header)
        except MailboxError as exc:
            problems.append("%s: %s" % (name, exc))
            continue

        actual = hashlib.sha256(body).hexdigest()
        if actual != header["body_sha256"]:
            problems.append(
                "%s: body does not match its recorded hash - the envelope was "
                "edited after it was written, so nothing in this run's record "
                "can be trusted verbatim" % name
            )

        if header["run_id"] != run_id:
            problems.append(
                "%s: filed under run %s but claims run %s" % (name, run_id, header["run_id"])
            )

        seq = int(header["seq"])
        if seq in seen_seq:
            problems.append("%s: reuses seq %d, already taken by %s" % (name, seq, seen_seq[seq]))
        seen_seq[seq] = name

        if header["kind"] == "task":
            tasks[header["to"]] = name
        elif header["kind"] in ("report", "failure"):
            answered.add(header["from"])

    for worker, task_name in sorted(tasks.items()):
        if worker not in answered:
            problems.append(
                "%s was dispatched to %s and nothing came back. Silence is not "
                "success: seal it with a failure envelope naming the mode, or "
                "the run records a task that simply stopped existing." % (task_name, worker)
            )

    return problems


def _fail(message):
    print("  %s" % message, file=sys.stderr)
    return 1


def cmd_post(args):
    body = Path(args.body_file).read_bytes() if args.body_file else b""
    try:
        path = post(
            args.workspace,
            args.run_id,
            args.kind,
            getattr(args, "from"),
            args.to,
            args.persisted_by,
            body,
            args.failure_mode,
        )
    except MailboxError as exc:
        return _fail(str(exc))
    print("posted %s" % path)
    return 0


def cmd_seal_failure(args):
    body = (
        "No report was returned by %s.\n\n"
        "This envelope was written by the orchestrator, not by the worker. The "
        "worker produced nothing, and a run in which a task simply vanishes is "
        "indistinguishable from one that succeeded quietly - so the absence is "
        "recorded as an envelope rather than left as a gap.\n\n"
        "failure mode: %s\n" % (getattr(args, "from"), args.failure_mode)
    ).encode("utf-8")
    try:
        path = post(
            args.workspace,
            args.run_id,
            "failure",
            getattr(args, "from"),
            "orchestrator",
            "orchestrator",
            body,
            args.failure_mode,
        )
    except MailboxError as exc:
        return _fail(str(exc))
    print("sealed %s" % path)
    return 0


def cmd_list(args):
    try:
        entries = read_all(args.workspace, args.run_id)
    except MailboxError as exc:
        return _fail(str(exc))
    if not entries:
        print("no envelopes for run %s" % args.run_id)
        return 0
    for _path, header, body in entries:
        print(
            "%4s  %-8s %-24s -> %-14s %d bytes"
            % (
                header.get("seq"),
                header.get("kind"),
                header.get("from"),
                header.get("to"),
                len(body),
            )
        )
    return 0


def cmd_verify(args):
    problems = verify(args.workspace, args.run_id)
    if problems:
        for problem in problems:
            print("  %s" % problem, file=sys.stderr)
        print("\n%d problem(s) in run %s" % (len(problems), args.run_id), file=sys.stderr)
        return 1
    count = len(envelope_paths(mailbox_dir(args.workspace, args.run_id)))
    print(
        "run %s is sound: %d envelope(s), every body matches its hash, every "
        "dispatched task answered" % (args.run_id, count)
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    post_p = sub.add_parser("post")
    post_p.add_argument("--run-id", required=True)
    post_p.add_argument(
        "--kind", required=True, choices=["task", "report", "failure", "question", "answer"]
    )
    post_p.add_argument("--from", required=True)
    post_p.add_argument("--to", required=True)
    post_p.add_argument("--persisted-by", required=True)
    post_p.add_argument("--body-file")
    post_p.add_argument("--failure-mode")
    post_p.set_defaults(func=cmd_post)

    seal = sub.add_parser("seal-failure")
    seal.add_argument("--run-id", required=True)
    seal.add_argument("--from", required=True)
    seal.add_argument("--failure-mode", required=True)
    seal.set_defaults(func=cmd_seal_failure)

    list_p = sub.add_parser("list")
    list_p.add_argument("--run-id", required=True)
    list_p.set_defaults(func=cmd_list)

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--run-id", required=True)
    verify_p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
