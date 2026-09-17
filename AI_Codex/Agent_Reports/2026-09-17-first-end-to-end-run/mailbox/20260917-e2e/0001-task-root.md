<!-- root-architect envelope
body_sha256: cf157749a96bdb22073d6cc45c6789793c1fbc646841de571964e7b4a2686b46
created_at: 2026-09-17T18:22:10.191966+00:00
from: root
kind: task
persisted_by: root
run_id: 20260917-e2e
seq: 1
to: orchestrator
-->
# Task — run 20260917-e2e

## The task

`src/slugify.py` mishandles punctuation and repeated spaces. At HEAD
(fa10c19) the observed behaviour is:

    slugify('Hello,  World!')  ->  'hello,--world!'

It must become `'hello-world'`, and the change must come with a test.

## What "done" looks like

The slug rule is settled by root. It is not open for redesign by you or by a
worker; if you believe it is wrong, ask me rather than change it:

> Lowercase the input. Treat every character that is not an ASCII letter or
> digit as a separator. Collapse each run of one or more separators into a
> single hyphen. Strip leading and trailing hyphens.

Done means all of the following, and nothing more:

1. `implement-slugify` returns a DONE implementer report carrying real observed
   RED and GREEN counts — test written first, failing first, for the right
   reason.
2. `spec-check-slugify` returns PASS from a fresh spec-validator, with
   `commands_rerun` empty.
3. `quality-check-slugify` returns PASS from a *different* fresh
   quality-validator, with the observed suite counts recorded.

Anything short of that is `rejected` or `blocked`, not `accepted`. I would
rather have an accurate `blocked` than an optimistic `accepted`.

## Your inputs

Queue:   `.root-architect/queue/20260917-e2e.json` (3 tasks, in dispatch order)
Briefs:  `.root-architect/briefs/20260917-e2e/*.json` — I wrote them; each names
         its own model and effort, and they are self-contained. Dispatch each
         worker with the brief plus its agent file. Do not restate the role
         text in the prompt, and do not paraphrase the brief.

## Environment facts you will otherwise rediscover the hard way

- **pytest is not installed.** unittest from the standard library only.
- The acceptance command, which I verified executable in a scratchpad before
  writing it into the briefs:

      PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v

- `tests/` does not exist yet. The implementer creates `tests/test_slugify.py`.
- Nothing else in the repository imports `slugify`, so that suite is the full
  reachable set. There is no wider baseline for you to run.

## Boundaries

- You never edit source and you never commit. Root commits, once, at the end.
- Workers never commit; a Git mutation from a worker is refused by a hook.
- Same implementer for findings, up to three attempts, then `blocked`. Record
  the escalation reason before escalating; the brief gate requires it from
  attempt 2.
- `check_return.py` first, every time. A malformed return earns exactly one
  corrective retry and that retry does not consume an implementation attempt.
- A worker that returns nothing gets a `seal-failure` envelope naming the mode.
  Silence is never success.

## Reaching me

Post a `question` envelope to `root` and stop on it. I am waiting on this run
and I will answer. Use it for a scope decision, a conflict the briefs do not
settle, three failed attempts, or anything that would otherwise tempt you to
widen the task. Do not speak to the operator; I relay.

Return the orchestrator outcome as one fenced JSON block matching
`orchestrator-outcome.schema.json`.
