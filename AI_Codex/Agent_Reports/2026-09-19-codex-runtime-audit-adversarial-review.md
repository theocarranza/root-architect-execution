---
type: agent-report
area: codex-adapter
tags: [codex, adversarial-review, runtime, evidence, audit]
created: 2026-09-19
---

# Adversarial review of the Codex adapter runtime audit

## Verdict

**Accept the original report's conclusion that the required runtime is unproven. Revise its evidence claims and delivery plan before using it as an implementation specification.**

The [original audit](2026-09-19-codex-adapter-runtime-audit.md) correctly identifies missing startup integration, fixed worker models, conflicting workflow instructions, missing automatic result capture, and missing monitoring. However, it overstates the existing queue and mailbox safeguards. Local reproductions found that startup can pass without a dispatch tool, two queue tasks can be dispatched together, and an old report can satisfy a later unanswered task. These are defects in the current code, beyond the missing integration identified in the audit.

The proposed startup hook also cannot, by itself, stop a run when that hook is untrusted and therefore never executes. Worker tool restrictions and reliable monitoring need explicit mechanisms and negative tests, not only additional instructions and fields.

## Scope and evidence limits

- Reviewed the working tree at revision `90a5bac808718c9fe8467cb3773bed0e075b8eb9`, branch `main`, on September 19, 2026, America/Recife time. This was a dirty tree, including shared renderer/preflight changes and Gemini work. Findings describe the inspected files, not an untouched release checkout.
- Compared production scripts, schemas, role declarations, generated agents, and the built `dist/codex` bundle. Its comparison with a fresh build passed. No deployed installation was inspected.
- Used the requested OpenAI Docs and OpenAI API Troubleshooting skills. Retrieved official pages directly; documentation establishes supported interfaces, not that this plugin uses them successfully.
- Ran the existing test suite and isolated reproductions using temporary directories. No model request, plugin installation, live child-agent trial, or production-code change occurred.
- The locally available executable reports `codex-cli 0.147.0`, the same version named in the host declaration. A harmless warning about unavailable PATH-alias writes accompanied the version command; it is not a model-service failure.

Severity below means priority for making this workflow reliable: **High** can permit false success or leave a required boundary absent; **Medium** leaves a material implementation decision unresolved.

## Claim-by-claim assessment

| Original claim | Assessment | Evidence |
| --- | --- | --- |
| The four named Codex static checks pass. | Confirmed. | All four passed again; see validation results below. |
| The broad suite fails because the Gemini bundle contains obsolete generated agent paths. | Confirmed, with exact count. | 263 tests ran; two failures report the same five extra Gemini files. |
| Codex startup bootstrap is absent from this adapter. | Confirmed for the shipped adapter. | [Manifest](../../adapters/codex/manifest.template.json), [layout](../../adapters/codex/layout.json), and generated root instructions provide no startup hook. This does not establish the absence of unrelated user/system hooks. |
| A custom root-agent file does not establish the ordinary main session's root identity. | Supported. | The installer writes custom-agent files; it does not launch or select the main session. Official custom-agent documentation describes configuration for spawned sessions. [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents). |
| Root/orchestrator role declarations disagree with the main skill and workflow document. | Confirmed. | [SKILL.md](../../SKILL.md), lines 35–49 and 153–165; [workflows.md](../../docs/02-design/workflows.md), lines 25–55; [root role](../../roles/root-architect.json). |
| Fixed worker model and reasoning values defeat spawn-time escalation. | Confirmed. | Generated worker files set both values; custom-agent values take precedence over spawn values. [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents). |
| The queue refuses a second open task. | False as a general guarantee. | `next_task()` refuses; `mark()` accepts a second dispatched task. Finding 2. |
| A terminal task needs an envelope name. | True but weak. | The transition requires a nonempty name, not a valid, matching result. Finding 2. |
| The mailbox forbids workers from writing envelopes and protects append-only evidence. | Overstated. | It rejects a worker label in `persisted_by`; it does not authenticate the caller or protect files from a writer. Finding 3. |
| Automatic native-return capture and worker/orchestrator watchdogs are missing. | Confirmed in inspected adapter/core code. | No lifecycle hook, native event consumer, child-control loop, or watchdog is shipped. Finding 6 addresses the proposed replacement. |
| Codex root-versus-worker write separation is instructional here. | Supported for this adapter. | Host declarations and generated disclosures say so; no Codex write guard is shipped. This is not proof that all alternative enforcement designs are impossible. |
| Old documentation URLs and dated observations require replacement before being trusted. | Needs qualification. | Both `/codex/subagents` and `/codex/hooks` resolved to current official pages during this review. Age is a reason to recheck a claim, not evidence it is false. |

## Findings

### 1. High — adding `--host codex` does not repair startup validation

The audit correctly identifies the omitted host argument, but its remedy leaves the actual Codex check unsound.

**Code:** [root_preflight.py](../../scripts/root_preflight.py), lines 83–102, 140–169, 307–367, and 400; [hosts/codex.json](../../hosts/codex.json), `tool_map`; [dispatch_state.py](../../scripts/dispatch_state.py), lines 172–229.

**Reproduced:**

- Codex observation `{"tools": [], "agent_types": ["orchestrator"]}` passes. The host maps no delegation tool, so the missing-tool test has nothing to require.
- An observation including `spawn_agent` and the ordinary built-in names `default`, `worker`, and `explorer` fails because the check demands an exclusive orchestrator roster. It confuses a policy about what root should select with a host restriction the adapter explicitly says it cannot enforce.
- `passed()` accepts a record with `"passed": "false"`, a different run identifier, and a different host. It checks truthiness without validating record identity or type.
- `dispatch_state.py open` succeeds in a fresh temporary workspace with no preflight record at all. The startup check gates queue creation, not every route that records a dispatch.

These are local input/output reproductions, not observations of a live Codex launch. They nevertheless disprove the check's claimed guarantee.

**Required correction:** separate “can delegate” from “delegation scope is enforced.” An unsupported restriction must stay explicitly unsupported. Validate the preflight record's schema, run, host, and relevant configuration identity; require it at the supported dispatch entry point. A hook calling the current checker would preserve both its false pass and false rejection.

### 2. High — the queue records invalid progress before checking it

**Original claim challenged:** lines 126–129 say the queue refuses a second open task. The proposed terminal-envelope verification is justified, but the report underestimates the existing gap.

**Code:** [job_queue.py](../../scripts/job_queue.py), lines 150–240. `mark()` checks the selected task's transition, then saves it. It does not check other active tasks or read the supplied envelope. `verify()` compares filenames, not envelope contents.

**Reproduced:**

| Operation | Result |
| --- | --- |
| Mark two pending tasks `dispatched`, one after the other. | Both writes succeed; only a later `verify()` reports the conflict. |
| Mark a dispatched task `returned` with `missing.md`. | The terminal state is saved; a later queue verification catches the missing filename. |
| Put plain text in `fake.md`, then mark the task returned with that filename. | Queue verification passes. Mailbox verification, when separately invoked, rejects the file. |

**Required correction:** enforce one active task and validate the matching result before committing a transition. Check run, task/attempt, sender, recipient, kind, and body integrity. Protect concurrent updates and make crash recovery explicit. Merely running a verification command eventually allows invalid state to guide intervening decisions.

### 3. High — mailbox evidence is neither task-bound nor authenticated

**Code:** [mailbox.py](../../scripts/mailbox.py), lines 152–185 and 196–247; [envelope schema](../../schemas/envelope.schema.json), especially `from`, `to`, and `persisted_by`.

**Reproduced:** post a task, its report, and then a second unanswered task to the same worker role. `mailbox.verify()` returns no problems. It tracks answers by worker name across the whole run, so the first report also satisfies the second task. Both queue tasks can then point to that same report and both verifiers pass.

The script also accepts a worker report addressed directly to root. The schema allows the endpoint names independently, without enforcing the intended communication routes. `persisted_by` is supplied by the caller; accepting the string `orchestrator` does not establish that the caller is the orchestrator.

Finally, rewriting a stored body together with its recorded hash passes verification. The hash detects a body-only edit, not a writer replacing both. `post()` refuses an existing filename during ordinary serial use, but performs a separate existence check followed by a truncating write. This is not an atomic append-only storage guarantee. The race was identified by inspection, not exercised here.

**Required correction:** describe the present mechanism as cooperative file bookkeeping. Add task, attempt, and provider-result identity; verify permitted routes and unique answer linkage. Define who may write the evidence directory and how the capture service authenticates origin. Use atomic creation/update rules and a protected integrity record if hostile rewriting is in scope. A report body hash alone cannot establish that its contents came from a worker.

### 4. High — the proposed bootstrap cannot enforce its own absence

The original report requires an untrusted hook to cause a blocked run. Official packaging documentation says untrusted plugin hooks are skipped. A skipped program cannot report its own absence or prevent the main session from working. This is a missing control path in the proposed design, not a disagreement with the goal. [Plugin packaging](https://developers.openai.com/es-419/plugins/build/plugins#servidores-mcp-incluidos-y-hooks-de-ciclo-de-vida).

**Required correction:** identify a separately enforced launch or run-admission check that refuses to start the governed workflow without verified bootstrap evidence. Explicitly state its limits if the user can bypass that launcher. Do not promise that a plugin hook makes every ordinary Codex session fail closed.

Also cover the documented `clear` startup source, in addition to `startup`, `resume`, and `compact`. [Hooks](https://learn.chatgpt.com/docs/hooks#sessionstart).

### 5. High — the delivery plan does not satisfy its worker-tool requirement

The audit requires workers to lack delegation and receive only their allowed tools, but its completion criteria do not test either restriction. Adding tier variants changes model selection, not tool access.

**Code:** [hosts/codex.json](../../hosts/codex.json) declares tool allowlists and denylists unsupported. [Generated worker files](../../adapters/codex/agents/impl-executor.toml) render prohibitions as prose. [render_agents.py](../../scripts/render_agents.py), lines 681–749, does not emit a worker-specific delegation switch.

Current official configuration documents `agents.enabled` as a switch for multi-agent tools. Custom-agent files can carry supported configuration keys. That makes a worker configuration with delegation disabled a candidate worth testing; it does **not** establish that this repository currently enforces it, or that it supplies a general per-tool allowlist. [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference), [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents).

The `Agent` spelling in the audit also needs care: the hook guide names `spawn_agent` and its `Agent` matcher alias. A hook matcher is not an agent permission declaration. [Hooks](https://learn.chatgpt.com/docs/hooks#tool-coverage).

**Required correction:** add installed-host negative tests for worker spawning, worker tool access, and orchestrator dispatch. Either implement and prove the restriction or explicitly accept a weaker supported mode. Include actual sandbox behavior: the documented parent runtime overrides can supersede custom-agent sandbox defaults. [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents#approvals-and-sandbox-controls).

### 6. Medium — capture and monitoring need a concrete controller and failure ordering

The report identifies the right missing features, but naming hooks, deadlines, and envelope fields does not specify what runs the monitor or preserves results before the orchestrator judges them.

Official `SubagentStop` payloads include `agent_id` and nullable `last_assistant_message`. This is a candidate capture input; it does not establish exact ordering, complete output, or one delivery per result. Transcript format is explicitly unstable. [Hooks](https://learn.chatgpt.com/docs/hooks#subagentstop).

For a controller design, the official App Server interface documents thread status events, approval-wait flags, final item events, steering, and interruption. Those are concrete interfaces to investigate. Access to the correct installed-session children remains untested; a plugin hook does not automatically become an App Server client. [Codex App Server](https://learn.chatgpt.com/docs/app-server#events).

**Required correction:** choose the capture/control interface and prove correlation to the exact run, task, attempt, child, and final result. Define the captured representation, such as final message text encoded as UTF-8, rather than unspecified native bytes. Define the process that wakes on deadlines, what happens when it dies, duplicate-event handling, and recovery after persistence succeeds but queue advancement fails.

The report's timeout ordering also needs revision: it proposes recording failure before asking for status. Specify how a still-running worker is stopped or quarantined and how a late successful return is preserved without reversing a terminal state. Do not start replacement work while the old writer may still be active. Approval waits, model failures, missing events, and idle agents require different evidence; a deadline alone cannot identify the cause.

### 7. Medium — the variant proposal overlooks existing schema fields and migration constraints

The fixed-model diagnosis is correct. The renderer uses each role's default tier and effort; declared escalation alternatives are not rendered into selectable worker variants. [render_agents.py](../../scripts/render_agents.py), lines 730–745.

However, the audit says the role schema should gain `model` and `reasoning`. Both already exist as structured objects containing defaults and escalation lists. The current validator also rejects multiple manifests for one role position. [Role schema](../../schemas/agent-role.schema.json), lines 61–100; [validate_roles.py](../../scripts/validate_roles.py), lines 108–120.

**Required correction:** define whether variants are generated from one family declaration or represented as additional manifests, and explain how that fits the one-role-per-position rule. Keep portable tier choices separate from host model identifiers. Treat the seven proposed variants as a design choice, not an OpenAI requirement. Also justify raising both validator families' minimum tier to `mid`: today's generated validators use `gpt-5.6-luna` with medium reasoning, and this review obtained no comparative cost or quality evidence for changing that baseline.

## Smaller factual and provenance corrections

1. The orchestrator's actual shell instructions name `dispatch_state.py`, `mailbox.py`, and `check_return.py`. They omit `job_queue.py`, despite saying they drive the queue. The audit's “queue and mailbox scripts” description misses this concrete inconsistency. [Orchestrator role](../../roles/orchestrator.json), line 12; [role prose](../../references/agents/orchestrator.md), lines 9–11.
2. Queue tasks already have `updated_at`, and a run has `created_at`. There is no provider heartbeat or meaningful live progress timestamp. Say that precisely instead of suggesting the state contains no timestamps. [Queue schema](../../schemas/job-queue.schema.json).
3. The interface evidence is not simply an old documentation link: it names vendor source revision `f3da386`, retrieved September 17, with explicit caveats. This review did not independently fetch that vendor-source revision. Preserve the distinction between source inspection, official prose, and a live trial. [Codex interface](../../adapters/codex/agent-interface.json).
4. The architecture document already qualifies guard enforcement with “where host identity is available.” A Codex-specific note would improve clarity, but this is weaker evidence of overclaiming than the queue/mailbox statements reproduced above. [Architecture](../../docs/01-architecture/architecture.md), line 29.
5. “Generation and installation are validated” should mean generation, packaging, and local materialization tests only. Neither audit establishes registration, hook trust, startup, or nested execution in an installed Codex session.

## Validation results

| Check | Observed result |
| --- | --- |
| `python3 scripts/validate_roles.py --host codex` | Passed: five roles, one host. |
| `python3 scripts/render_agents.py --host codex --check` | Passed: five generated agent files match. |
| `python3 scripts/validate_interfaces.py` | Passed: five interfaces and five roles checked; Codex nesting is labelled first-party-source, not empirically verified. |
| `python3 scripts/build_adapter.py --host codex --check` | Passed: 46 bundle files match a fresh build. |
| `python3 -m unittest discover -s tests -t .` | 263 tests in 68.105 seconds; 261 passed, two failed. |
| Temporary-directory adversarial probes | Confirmed Findings 1–3; production files were not modified. |

Both suite failures are in `tests.test_plugin.AdapterBuildTests`: `test_committed_bundle_matches_a_fresh_build` for Gemini, and `test_gemini_adapter_produces_expected_bundle_structure_and_roles`. Both report the same five extra files under `dist/gemini/adapters/gemini/agents/`: `impl-executor.md`, `orchestrator.md`, `quality-validator.md`, `root-architect.md`, and `spec-validator.md`. No Codex test failure was reported. Passing tests do not negate the uncovered counterexamples.

The troubleshooting skill did not identify an OpenAI service failure: none was supplied or produced. The failures above are local code/test results, not authentication, billing, rate-limit, or model-access errors. Future live acceptance should retain concrete error responses before assigning those causes.

## Revised acceptance order

1. Correct the audit's queue/mailbox claims and the conflicting role instructions. Define the supported launch and enforcement boundaries.
2. Repair and negatively test preflight, dispatch admission, queue transitions, task/attempt linkage, and permitted mailbox routes.
3. Prove the smallest installed root → orchestrator → worker cycle, including worker delegation denial and effective permissions. Record unsupported restrictions honestly.
4. Add capture and lifecycle integration through a selected runtime interface. Test missing/null results, duplicate events, crashes between writes, and late output after a timeout.
5. Add tier selection using an explicit schema migration. Record requested configuration separately from observed effective configuration.
6. Run the original acceptance cases plus untrusted/disabled/changed hooks, `clear`, a forged preflight, two dispatched tasks, reused/wrong-kind/tampered envelopes, worker spawning, monitor failure, and restart recovery.

These are recommendations for follow-up work, not changes performed in this review.

## Reproduction appendix

Run the following from the repository root. It imports the production modules and writes only inside an automatically removed temporary directory. The minimal preflight record in `new_queue()` deliberately demonstrates the current admission contract; it is not a valid proposed design.

```python
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
import job_queue as queue
import mailbox
import root_preflight as pre

with tempfile.TemporaryDirectory(prefix="codex-audit-") as tmp:
    workspace = Path(tmp)
    observed = workspace / "observed.json"
    observed.write_text(json.dumps({"tools": [], "agent_types": ["orchestrator"]}))
    result = pre.run(workspace, "20260919-empty-tools", observed, host_name="codex")
    print("empty toolset passes:", result["passed"])

    def new_queue(run, names):
        record = pre.record_path(workspace, run)
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"passed": True}))
        queue.init(workspace, run, [
            {"name": name, "worker": "worker:implementer", "brief": "brief.json"}
            for name in names
        ])

    run = "20260919-two-open"
    new_queue(run, ["first", "second"])
    for name in ["first", "second"]:
        queue.mark(workspace, run, name, "dispatched")
    print("two dispatched:", [t["state"] for t in queue.load(workspace, run)["tasks"]])

    run = "20260919-fake-envelope"
    new_queue(run, ["first"])
    queue.mark(workspace, run, "first", "dispatched")
    directory = mailbox.mailbox_dir(workspace, run)
    directory.mkdir(parents=True)
    (directory / "fake.md").write_text("not an envelope")
    queue.mark(workspace, run, "first", "returned", "fake.md")
    print("fake envelope queue verification:", queue.verify(workspace, run))

    run = "20260919-reused-report"
    new_queue(run, ["first", "second"])
    mailbox.post(workspace, run, "task", "orchestrator", "worker:implementer",
                 "orchestrator", b"first task")
    report = mailbox.post(workspace, run, "report", "worker:implementer",
                          "orchestrator", "orchestrator", b"first result only")
    mailbox.post(workspace, run, "task", "orchestrator", "worker:implementer",
                 "orchestrator", b"second task, unanswered")
    for name in ["first", "second"]:
        queue.mark(workspace, run, name, "dispatched")
        queue.mark(workspace, run, name, "returned", report.name)
    print("reused result verification:", queue.verify(workspace, run),
          mailbox.verify(workspace, run))
    header, _ = mailbox.parse_envelope(report.read_bytes())
    body = b"replaced result"
    header["body_sha256"] = hashlib.sha256(body).hexdigest()
    report.write_bytes(mailbox.render_header(header).encode() + body)
    print("rewritten body and hash verification:", mailbox.verify(workspace, run))

    record = pre.record_path(workspace, "20260919-invalid-preflight")
    record.write_text(json.dumps({"passed": "false", "run_id": "other", "host": "other"}))
    print("invalid preflight accepted:", pre.passed(workspace, "20260919-invalid-preflight"))
```

Observed output:

```text
empty toolset passes: True
two dispatched: ['dispatched', 'dispatched']
fake envelope queue verification: []
reused result verification: [] []
rewritten body and hash verification: []
invalid preflight accepted: (True, None)
```

The separate dispatch-admission probe used a schema-valid brief and invoked `dispatch_state.py open --workspace <temporary-directory> --run-id 20260919-no-preflight --brief <brief.json>`. It exited 0 and created an open dispatch while the preflight directory did not exist. This records a dispatch; it does not launch a model.

## Source fingerprints

These hashes identify the reviewed working-tree bytes, including the pre-existing uncommitted preflight change.

| File | SHA-256 |
| --- | --- |
| Original audit | `655b760a88063babbe4d2316afb16f376824ce8e22d97f9588d11b35d4e7ca3a` |
| `scripts/root_preflight.py` | `5e9fb6360f1adc1ab81556d8579d82e2704962364a8e840059a81736979d36ac` |
| `scripts/job_queue.py` | `443b83ce792b80d82100bb315654d0ee18dcce8e6a29e973c46ece329cfcea6a` |
| `scripts/mailbox.py` | `d29c0f8d27e630677c5f8181981ceda8bc0d92561411bc3bd0cd9a3a45c2a2c3` |
| `scripts/dispatch_state.py` | `09fb0b8514e5fc5c06b70880153f177da342e287205370cca22c6df632ab48d7` |
| `hosts/codex.json` | `5c253c4a8670ff66ffe53e866e69fea2f70d006439737d3bd5b171372a5926bc` |

Official documentation was retrieved during this review. Links above support the associated claims; they are not evidence that an installed plugin passed a runtime trial.
