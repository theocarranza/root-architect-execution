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
import re
import shlex
import sys

ROLE_BY_AGENT = {
    "impl-executor": "implementer",
    "spec-validator": "spec-validator",
    "quality-validator": "quality-validator",
}

MUTATING_GIT = {
    "commit", "add", "stage", "push", "reset", "rebase", "merge", "tag",
    "checkout", "switch", "restore", "cherry-pick", "revert", "stash",
    "clean", "am", "apply", "mv", "rm", "branch", "remote", "fetch", "pull",
    "worktree", "gc", "filter-branch", "update-ref", "symbolic-ref", "notes",
}
READ_ONLY_GIT = {
    "status", "diff", "log", "show", "rev-parse", "ls-files", "blame",
    "describe", "shortlog", "cat-file", "config",
}

SHELL_SPLIT = re.compile(r"(?:&&|\|\||;|\||\n)")


def role_for(agent_type):
    """Map the host's agent identity onto one of this plugin's roles.

    Claude Code reports a plugin-provided agent namespaced as
    "<plugin>:<agent>", while a project-local copy of the same agent file
    reports the bare name. Both are this role; matching only the bare form
    silently disabled this guard for every plugin-installed worker, which is
    exactly the configuration the plugin ships.
    """
    name = (agent_type or "").rsplit(":", 1)[-1]
    return ROLE_BY_AGENT.get(name)


def _allow():
    sys.exit(0)


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    print(reason, file=sys.stderr)
    sys.exit(2)


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
            for candidate in words[i + 1:]:
                if candidate.startswith("-"):
                    continue
                yield candidate
                break
            break


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        _allow()

    role = role_for(payload.get("agent_type"))
    if role is None:
        _allow()

    tool = payload.get("tool_name")

    if role == "spec-validator":
        if tool in {"Bash", "BashOutput", "KillShell", "PowerShell"}:
            _deny(
                "Worker guard: the plan-compliance validator is dispatched "
                "read-only with no shell. Reaching one means the tool grant "
                "leaked. If a command needs running, that is the quality "
                "validator's job — record it as a finding instead.")
        if tool in {"Edit", "Write", "NotebookEdit", "MultiEdit"}:
            _deny("Worker guard: the plan-compliance validator fixes nothing. "
                  "Report a finding; root re-briefs the implementer.")
        _allow()

    if role == "quality-validator" and tool in {"Edit", "Write", "NotebookEdit",
                                                "MultiEdit"}:
        _deny("Worker guard: the quality validator fixes nothing. Report the "
              "defect with a concrete failure scenario; root re-briefs the "
              "implementer.")

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
                "allowed." % (sub, role))
    _allow()


if __name__ == "__main__":
    main()
