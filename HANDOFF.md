# Handoff — 2026-09-17

Both architecture decision records are closed except where noted. The plugin
builds, installs, gates itself, and has now been **run**. This file is what a
next session needs that the ADRs do not say.

## Where things stand

| | |
|---|---|
| ADR 0003 — orchestrated worker isolation | **Complete.** D1–D12 built |
| ADR 0001 — host adapters | Steps 1–3 done; step 4 done for Codex, **open for Cursor** |
| End-to-end run | **Root half proven.** Orchestrator → worker never observed |

216 tests on Python 3.10–3.13, a ten-command outcome gate, and every guard
mutation-tested. `dist/claude-code` and `dist/codex` are byte-gated bundles.

## The one thing to do next: finish the run

[[First End-to-End Run]] records what happened and what it proved. The run
stopped because the **agent process hit its own session limit** immediately
after root posted the task envelope — not because anything failed. Everything
up to that point worked; nothing after it has ever executed.

Unobserved, in the order a run would exercise them:

1. The orchestrator dispatching a worker (root → orchestrator is proven).
2. A worker's report coming back as an envelope, and `check_return.py` judging it.
3. The two PreToolUse guards firing in a live run — `root_write_guard` refusing
   a root edit inside an open dispatch, `worker_git_guard` refusing a worker commit.
4. Root's final commit.

### Reproducing it

```bash
# 1. Build and install into a throwaway HOME
python3 scripts/build_adapter.py --host claude-code
export HOME=/tmp/e2e-home && mkdir -p $HOME
claude plugin marketplace add "$(pwd)/dist/claude-code"
claude plugin install root-architect-execution@root-architect-execution

# 2. Grant the tools root's own frontmatter already scopes.
#    MERGE into settings.json - do not overwrite it. `claude plugin install`
#    records the marketplace and the enabled plugin in that same file, and
#    clobbering it makes `--agent root-architect` report "agent not found".
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("/tmp/e2e-home/.claude/settings.json")
d = json.loads(p.read_text())
perms = d.setdefault("permissions", {})
perms["allow"] = sorted(set(perms.get("allow", [])) | {
    "Bash", "Read", "Edit", "Write", "Grep", "Glob", "Agent", "Skill", "TodoWrite"})
p.write_text(json.dumps(d, indent=2) + "\n")
PY

# 3. Run root as the main thread, with the nesting cap raised
cd /path/to/a/throwaway/git/repo
CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2 claude \
  --agent root-architect --permission-mode acceptEdits --max-turns 120 \
  -p "<the task>" < /dev/null
```

### Four things that cost time last run

- **`--permission-mode dontAsk` silently denies `Bash` and denies `Read`
  outside the workspace.** Root then cannot read its own role prose or reach a
  single gate script. Use `acceptEdits` plus the allow-list above.
- **`--dangerously-skip-permissions` / `bypassPermissions` refuses to run as
  uid 0.** Irrelevant on a normal machine, fatal in a container.
- **`--max-turns` must be generous.** The protocol spends turns on preflight,
  the ledger, the queue and three briefs before any work begins.
- **Redirect stdin** (`< /dev/null`), or the CLI waits on it.

### Budget

A full run is long. Root's half alone consumed a whole session. If the model's
quota is tight, run it in a fresh session with nothing else queued, and give
the task a smaller shape than the slugify one — a single worker task with no
validators would still close items 1–3 above.

## Cursor — blocked on sourcing, not engineering

ADR 0001 step 4's remaining half. Do **not** write the adapter first.

`adapters/cursor/agent-interface.json` records nested delegation as
`unsourced`, and under ADR 0003 D1 that forbids building the orchestrator or
root for that host. Cursor's prose documentation was unreachable from this
environment; its SDK reference describes only main-agent-to-subagent dispatch,
and its guidance discourages the shape without stating a capability.

So the first task is a documentation fetch, from an environment that can reach
`docs.cursor.com`. Then:

- If nesting is sourced → update the interface file with the source's own
  words, and the adapter is short work: `adapters/cursor/` with a
  `layout.json`, a manifest template, and an installer (Cursor has no native
  install path at all, so this one is more like Codex than Claude Code).
- If it is not → leave it `unsourced` and say so. A host that can carry three
  of five roles is not worth shipping as if it carried five.

`hosts/cursor.json` is also still marked inherited and unverified since
2026-09-04; the capability gate prints a warning for it on every run.

## Smaller open items

- **Plugin hooks in a `--agent` process.** `adapters/claude-code/agent-interface.json`
  carries a caveat on `hook_agent_identity`: the identity probe used a
  *project-level* hook, so whether a plugin-shipped `hooks.json` registers in a
  `claude -p --agent` process is inferred rather than measured. The script
  dispatch fallback leans on it. Finishing the run above would measure it
  incidentally — item 3.
- **Antigravity** has a first-party-sourced interface and no
  `hosts/antigravity.json`, so nothing renders for it and
  `validate_interfaces.py` notes that every run. Writing the host manifest is
  the whole job.
- **Three decisions ADR 0001 deferred**, all now unblocked by the adapter
  directories existing: digest authorization for Codex (a mechanism that would
  close the identity gap without identity — `adapters/codex/README.md` has the
  detail), adopting `isolation: worktree` (`adapters/claude-code/README.md`
  names the probe to run first), and whether `host-capability.schema.json`
  still needs an `unused_capabilities` block.

## Conventions worth not rediscovering

- Generated agents live in `adapters/<host>/agents/` and are never hand-edited.
  `dist/<host>/` is built from them and byte-gated; the repository root is
  **not** a loadable plugin any more, so develop against `dist/claude-code`.
- `claude plugin validate .` at the repository root does not fail — it switches
  to validating components and exits 0. Point it at `dist/claude-code`.
- Three scripts run from two positions (repo and installed bundle) and name
  both in order rather than searching upward. `render_agents.both_positions`
  is the shared one; `hooks/root_write_guard.py` deliberately does not use it,
  because it is looking for `scripts/` in the first place.
- The outcome gate is ten commands, listed in `README.md`. None is optional;
  each exists because the suite alone was once green over a real defect.
