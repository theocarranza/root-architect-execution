# Contracts

Four shapes carry the whole loop. Three are JSON Schemas that scripts enforce;
the fourth is the ledger checkpoint, which stays prose because a human reads it.

| Shape | Schema | Enforced by |
| --- | --- | --- |
| Brief | [../schemas/brief.schema.json](../schemas/brief.schema.json) | `dispatch_state.py open` |
| Implementer report | [../schemas/implementer-report.schema.json](../schemas/implementer-report.schema.json) | `check_return.py --role implementer` |
| Validator verdict | [../schemas/validator-verdict.schema.json](../schemas/validator-verdict.schema.json) | `check_return.py --role spec-validator\|quality-validator` |
| Checkpoint | this file | root's own discipline |

Fill every slot. A schema-conformant shape with an empty required field is
incomplete, and the scripts say so rather than letting it through.

## Brief

Root writes this before dispatching, as JSON, then opens the dispatch with it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dispatch_state.py" open \
  --brief /tmp/brief.json --run-id 20260907-task-3
```

```json
{
  "task": "Task 3 — reject a tampered middle result",
  "attempt": 1,
  "max_attempts": 3,
  "role": "implementer",
  "model": "haiku",
  "effort": "low",
  "read_paths": ["scripts/envelope.py", "scripts/tests/test_envelope.py"],
  "write_paths": ["scripts/envelope.py", "scripts/tests/test_envelope.py"],
  "interfaces": ["verify(envelope) keeps its (bool, reason) return shape"],
  "acceptance": [
    {"command": "python3.12 -m unittest scripts.tests.test_envelope",
     "expect": "all pass, at least one new case"}
  ],
  "constraints": [
    "Reachability: only envelope.py changes, and nothing outside scripts/ imports it, so the envelope module's own tests are the full reachable set."
  ],
  "owner_owned_paths": ["AI_Codex/Agent_Sessions/"],
  "expected_result": "A structurally valid payload edit is rejected by the next hash."
}
```

The dispatch prompt is this brief plus the worker's own agent file, which already
carries the role, the grant, the disclosures, and the return contract. Do not
restate them in the prompt — a brief that repeats the role text drifts from it.

`escalation_reason` becomes required from attempt 2. It holds the recorded
evidence of the previous failure, because escalating without one is a hunch.

## Implementer report

Returned as one fenced `json` block, validated before root reads it as a result.

```json
{
  "task": "Task 3 — reject a tampered middle result",
  "attempt": 1,
  "model": "haiku",
  "effort": "low",
  "status": "DONE",
  "files_written": [],
  "files_modified": ["scripts/envelope.py", "scripts/tests/test_envelope.py"],
  "tests": {
    "red":   {"command": "python3.12 -m unittest scripts.tests.test_envelope",
              "counts": "1 failed, 18 passed"},
    "green": {"command": "python3.12 -m unittest scripts.tests.test_envelope",
              "counts": "19 passed"}
  },
  "diff_summary": "Chain each envelope to its predecessor's hash; add a tamper case.",
  "evidence": ["FAIL: test_tampered_middle_result_is_rejected"],
  "notes": ""
}
```

A `DONE` report without both phases is rejected: a test written after the
implementation proves the code runs, not that the test could ever fail. Set
`reused: true` on a phase whose counts carry over from an earlier run at an
unchanged `HEAD` — reuse is legitimate and cheap; unlabelled reuse is a false
claim about this run.

## Validator verdict

Plan-compliance first, on a fresh read-only agent. After `PASS`, quality on a
**different** fresh agent.

```json
{
  "task": "Task 3 — reject a tampered middle result",
  "attempt": 1,
  "role": "quality-validator",
  "status": "FINDINGS",
  "findings": [
    {
      "path": "scripts/envelope.py",
      "requirement": "verify() raises the project's error type naming the field",
      "evidence": "envelope.py:88 `return payload['hash']` leaks a bare KeyError",
      "required_fix": "Raise EnvelopeError naming the missing field.",
      "failure_scenario": "verify({}) raises KeyError('hash') instead of EnvelopeError, so the caller's except clause misses it."
    }
  ],
  "commands_rerun": [
    {"command": "python3.12 -m unittest scripts.tests.test_envelope",
     "observed": "19 passed"}
  ]
}
```

`findings` is empty if and only if `status` is `PASS`. `commands_rerun` must be
empty for `spec-validator`, which has no shell by design — a non-empty list
means the two review roles were combined in one agent. Every quality finding
needs a `failure_scenario`; without one it is a suspicion, not a defect.

Each finding names exactly one required fix. Root returns findings to the **same**
implementer; do not open a new worker until that attempt is exhausted or blocked.

## Checkpoint

Append to the open session ledger after a `PASS` pair, with
`commit hash: pending` because a commit cannot contain its own hash.

**Checkpoint incrementally, not only at task completion.** A run can be killed
by a rate limit at any moment, and everything not written down is re-derived by
the next session at full cost. Append a short `### Progress` note at each of
these points, without waiting for a commit:

| When | What to record, in two or three lines |
| --- | --- |
| Dispatching a worker or reviewer | task, role, model, effort, and what it was asked to prove |
| A worker or reviewer returns | its verdict, and the findings root accepted or rejected |
| A malformed return is sent back | that it happened, so the corrective retry is visible and is not mistaken for an attempt |
| Root reproduces a finding | the reproduction and its result, especially a negative one |
| Root makes a design ruling | the ruling and the reason, before acting on it |
| Scope is widened or frozen | which paths, and why |

These cost a few lines each, and they are what makes an interrupted task
resumable rather than repeatable.

```text
time:
task:
attempt:
worker model:
worker effort:   # a level only where the host can set one; otherwise
                 # "not settable on this host" — never name a level nothing applied
spec validator:
quality reviewer:
commands:
  command:
  counts:        # mark "reused" where they carry over from an unchanged HEAD
commit hash: pending | <prior hash from git history>
next:
```

Close the dispatch, stage only brief-owned paths plus this ledger, run
`git diff --cached --check`, and make one narrow commit. Do not edit or amend
it, and do not create a bookkeeping-only second commit afterwards. At the next
substantive checkpoint, backfill the prior hash from git history. For the final
task, report its hash in the owner report and backfill it only in a later
substantive authorized commit.

One commit per task.

## First owner report

After takeover, before task 1 product work:

```text
branch:
session path:
preserved dirty paths:
capability gate:      # validate_roles.py + render_agents.py --check output
baseline:
  command:
  counts:
worker model routing:
reviewer model routing:
task 1 started: yes | no
```

Do not ask the owner to restate architecture already decided in the governing
plan or instance handoff.

## Common mistakes

| Excuse | Reality |
| --- | --- |
| "I'll write this small file in root" | Re-brief the worker. Root writing product code is a failed delegation, and the write guard refuses it while the dispatch is open. |
| "The hook is in the way, I'll close the dispatch" | Closing a dispatch to edit its paths yourself is the same failure with an extra step. Close it with `--outcome blocked` and say so in the ledger. |
| "`inherit` is fine" | Name the model. Every host defaults to inherit. |
| "Record effort: medium" | Only where the host can set it. The generated agent file says which. |
| "Sonnet is safer than haiku" | Start cheapest; escalate one tier on recorded evidence, not on a hunch. |
| "One reviewer for spec and quality" | Two fresh agents, spec first. A verdict with the wrong role is rejected mechanically. |
| "The worker can commit" | Root commits brief-owned paths only. A worker's Git mutation is refused by a hook. |
| "The return is close enough to the shape" | Run `check_return.py`. One corrective retry, and it does not consume an attempt. |
| "The prior gate is close enough" | Do not start the next outcome until the prior gate is executable and checkpointed. |
| "Nothing else could possibly touch it" | Put the reachability argument in `constraints`, or run the full set. |
| "The suites passed earlier" | Reuse is valid only from an unchanged `HEAD`, and must be labelled. |
| "Targeted evidence is enough to close the outcome" | Outcome gates run the full baseline. |
| "This dirty path is in the way" | Owner-owned dirty paths are out of scope until the owner places one in a brief. |
| "I'll just tweak the generated agent file" | Edit the role manifest and regenerate. The capability gate fails on a hand-edit. |
| "The worker can spawn a helper" | Workers must not spawn agents. Re-brief or split the task. |
| "Ask the owner to confirm the architecture" | Do not ask the owner to restate decided architecture. |
