#!/usr/bin/env python3
"""PreToolUse guard: workers never touch Git, and validators never mutate.

Root owns Git. That is a load-bearing rule rather than bookkeeping: root commits
exactly the brief-owned paths after a PASS pair of verdicts, so a worker that
stages or commits destroys the one boundary that makes a task's diff reviewable.
Prose has never been enough — an agent that has just made the tests pass is very
willing to "save the work".

Scoped by the agent identity the PreToolUse payload carries: this fires only
inside a subagent whose agent_type names one of this plugin's roles, so the same
hook file covers agents generated for other hosts and leaves root and unrelated
subagents alone.

Blocks, inside a worker:
  * Git subcommands that stage, record, publish, or rewrite history;
  * for the read-only role, any shell call at all, because that role is
    dispatched with no shell and reaching one means the grant leaked.

Allows read-only Git inspection (status, diff, log, show, rev-parse) — a worker
often needs to see what it changed to write its own diff summary.
"""

import json
import os
import re
import shlex
import sys
from typing import NoReturn

ROLE_BY_AGENT = {
    "impl-executor": "implementer",
    "spec-validator": "spec-validator",
    "quality-validator": "quality-validator",
}

MUTATING_GIT = {
    "commit",
    "add",
    "stage",
    "push",
    "reset",
    "rebase",
    "merge",
    "tag",
    "checkout",
    "switch",
    "restore",
    "cherry-pick",
    "revert",
    "stash",
    "clean",
    "am",
    "apply",
    "mv",
    "rm",
    "branch",
    "remote",
    "fetch",
    "pull",
    "worktree",
    "gc",
    "filter-branch",
    "update-ref",
    "symbolic-ref",
    "notes",
}
READ_ONLY_GIT = {
    "status",
    "diff",
    "log",
    "show",
    "rev-parse",
    "ls-files",
    "blame",
    "describe",
    "shortlog",
    "cat-file",
    "config",
}

SHELL_SPLIT = re.compile(r"(?:&&|\|\||;|\||\n)")


def role_for(agent_type):
    """Map the host's agent identity onto one of this plugin's roles.

    Claude Code reports a plugin-provided agent namespaced as
    "<plugin>:<agent>", while a project-local copy of the same agent file
    reports the bare name. Both are this role; matching only the bare form
    silently disabled this guard for every plugin-installed worker, which is
    exactly the configuration the plugin ships.

    Anything that is not a string cannot be one of this plugin's agents, and
    saying so here is what keeps the identity check itself incapable of
    raising — see main(), which treats every later exception as a denial.
    """
    if not isinstance(agent_type, str):
        return None
    return ROLE_BY_AGENT.get(agent_type.rsplit(":", 1)[-1])


def _allow() -> NoReturn:
    sys.exit(0)


def _report(stream, text):
    """Best-effort write. A stream that cannot take the text is not an error.

    Reporting is how a denial explains itself; it is not how a denial takes
    effect. Only the exit code blocks the call, so a broken pipe or a full
    device must never be allowed to propagate out of here.
    """
    try:
        stream.write(text)
        stream.flush()
    except Exception:
        pass


def _deny(reason: str) -> NoReturn:
    """Unconditionally terminal: exit 2 whatever the streams do.

    Same contract as root_write_guard._deny, and for the same reason. A plain
    print() here raises on a broken pipe or a full device, and even with that
    contained, sys.exit(2) still runs the interpreter's shutdown flush, where
    a failing flush makes Python report 120 regardless of what this function
    decided. Only exit 2 blocks a call; 0, 1 and 120 are all fail-open, so a
    worker `git commit` would go through on a denial this guard had already
    proven.

    So: write and flush both streams under their own handling, then leave via
    os._exit, which cannot be re-entered and runs no shutdown flush.
    """
    _report(
        sys.stdout,
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
        + "\n",
    )
    _report(sys.stderr, reason + "\n")
    os._exit(2)


def git_subcommands(command):
    """Yield the subcommand of every `git ...` segment in a shell command."""
    for segment in SHELL_SPLIT.split(command):
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        for i, word in enumerate(words):
            if word.rsplit("/", 1)[-1] != "git":
                continue
            for candidate in words[i + 1 :]:
                if candidate.startswith("-"):
                    continue
                yield candidate
                break
            break


def main():
    """Safety net: once inside a worker, an internal error denies.

    The split matters. Everything up to the identity check is deliberately
    incapable of raising, so anything that reaches this handler was raised
    after this guard established it is running inside one of this plugin's
    workers — the untrusted side of the boundary. Unproven state there is
    treated as a block, never as a bare exit 1, which PreToolUse reads as
    non-blocking and would let a worker commit through.

    Malformed hook *input* is the other direction and is handled in _main():
    a payload this guard cannot read is not evidence of a worker, and denying
    it would block root's own shell, which is what the protocol's stop
    conditions rely on to recover.
    """
    try:
        _main()
    except SystemExit:
        raise
    except Exception as e:
        _deny(
            "Worker guard: an internal error occurred while checking this "
            "call inside a worker, so it cannot be verified safe:\n  %r\n"
            "This guard fails closed on internal errors, never open." % (e,)
        )


def _main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        # A guard that cannot read its input must not block real work.
        _allow()

    if not isinstance(payload, dict):
        # Not a JSON object: cannot read agent_type from it, so there is no
        # evidence this is a worker at all. Malformed hook input, not a
        # worker's attempt to reach Git.
        _allow()

    role = role_for(payload.get("agent_type"))
    if role is None:
        _allow()

    tool = payload.get("tool_name")
    if not isinstance(tool, str):
        # Identity is established — this IS one of this plugin's workers — and
        # the tool cannot be named. The two validator branches below would
        # raise on an unhashable tool_name and deny via main()'s net anyway;
        # the implementer branch compares with != and would quietly allow. So
        # the decision is made once, here, in the fail-closed direction, for
        # every role.
        _deny(
            "Worker guard: this call arrived inside the %s worker with a "
            "tool name this guard cannot read (%r), so it cannot be proven "
            "not to be a Git call. This guard fails closed." % (role, tool)
        )

    if role == "spec-validator":
        if tool in {"Bash", "BashOutput", "KillShell", "PowerShell"}:
            _deny(
                "Worker guard: the plan-compliance validator is dispatched "
                "read-only with no shell. Reaching one means the tool grant "
                "leaked. If a command needs running, that is the quality "
                "validator's job — record it as a finding instead."
            )
        if tool in {"Edit", "Write", "NotebookEdit", "MultiEdit", "apply_patch"}:
            _deny(
                "Worker guard: the plan-compliance validator fixes nothing. "
                "Report a finding; root re-briefs the implementer."
            )
        _allow()

    if role == "quality-validator" and tool in {
        "Edit",
        "Write",
        "NotebookEdit",
        "MultiEdit",
        "apply_patch",
    }:
        _deny(
            "Worker guard: the quality validator fixes nothing. Report the "
            "defect with a concrete failure scenario; root re-briefs the "
            "implementer."
        )

    if tool != "Bash":
        _allow()

    command = (payload.get("tool_input") or {}).get("command") or ""
    for sub in git_subcommands(command):
        if sub in READ_ONLY_GIT:
            continue
        if sub in MUTATING_GIT or sub not in READ_ONLY_GIT:
            _deny(
                "Worker guard: `git %s` is refused inside the %s worker. Root "
                "owns Git and commits exactly the brief-owned paths after both "
                "verdicts pass; a worker commit destroys the boundary that "
                "makes the task's diff reviewable. Report the work in your "
                "return and let root stage it.\n"
                "Read-only inspection (status, diff, log, show, rev-parse) is "
                "allowed." % (sub, role)
            )
    _allow()


if __name__ == "__main__":
    main()
