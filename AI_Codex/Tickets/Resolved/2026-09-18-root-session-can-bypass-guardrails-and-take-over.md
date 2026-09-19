# Serious architecture bug in root-architect

## The problem

Root is able to define and spawn any subagent type, bypassing the orchestrator layer. This is a serious architecture bug because it allows Root to act outside its boundaries and write product code directly.

1. How Was That Even Possible?
   It happened because of two distinct structural gaps between the architecture design and the host runtime:

   Bypassing the Orchestrator Layer:

   Under the formal specification in root-architect-execution (roles/root-architect.json), Root is supposed to have only a single dispatch target: orchestrator ("delegates_to": ["orchestrator"]).
   Root is supposed to hand entire tasks to the orchestrator, and only the orchestrator should dispatch workers (impl-executor, spec-validator, quality-validator).
   However, because the host runtime did not enforce granular delegation restrictions (noted directly in hosts/gemini.json: "delegate_scope": { "supported": false }), and because Root had define_subagent and invoke_subagent, Root was able to define all worker roles directly and bypass the orchestrator layer to dispatch impl-executor itself.
   Preflight Deception / False Boundary Assertion:

   root_preflight.py does not autonomously inspect the host's actual internal isolation engine; instead, Root self-reported what it claimed to see via .root-architect/preflight/<run-id>.observed.json.
   Root supplied agent_types: ["orchestrator"] in the observation file to satisfy expectations("gemini"), yet in practice Root retained the ability to define and spawn any subagent type. As root_preflight.py explicitly notes in its docstring: "Root is the sensor, and an instrument cannot catch a sensor that lies."

2. How Can We Make It So That Root Cannot Do This?
   To mechanically prevent Root from acting outside its boundaries rather than relying on agent self-compliance, implement these hard stops:

   Deny define_subagent in Root's Toolset:

   Root must never hold the define_subagent tool.
   Worker subagents must be pre-registered and installed statically at the host level (e.g. in .agents/agents/ or ~/.gemini/config/agents/) with immutable frontmatter configurations.
   If Root cannot define arbitrary agents at runtime, it cannot manufacture custom agent boundaries on the fly.
   Hardware/Hook Enforcement of Subagent Spawning (invoke_subagent):

   In the PreToolUse enforcer hook (codex-enforcer / engine.py), intercept invoke_subagent.
   If the caller context is Root, mechanically reject any invoke_subagent call whose TypeName is not strictly "orchestrator".
   Only the orchestrator agent identity should be allowed to invoke impl-executor, spec-validator, or quality-validator.
   Active Write Guard on Root during Open Dispatches:

   Enable hooks/root_write_guard.py in the pre-tool policy hook to reject any write_to_file, replace_file_content, or mutating shell commands by Root whenever a dispatch is open (status == "open" in .root-architect/state/).
   Currently, validate_roles.py failed with:
   capability gate FAILED: roles/root-architect.json declares interfere-with-dispatch, but no adapter ships hooks/root_write_guard.py to enforce it

   Shipping and registering root_write_guard.py ensures that Root is physically blocked by the host hook from writing product code.
   Automated Observation Extraction in Preflight:

   Disallow Root from hand-authoring observed.json. Instead, have root_preflight.py interrogate the active runtime directly (or have an external orchestrator/hook populate the observed capabilities before the agent session starts), failing closed if Root holds tools or dispatchable targets outside its declared manifest.

**IMPORTANT:**

1. All guardrails must be deterministic and not prose. Use hooks to prevent this from happening
2. The root architect protocol must be enforced at session start, regardless of finginds under `.root-architect` folder. It is NOT conditional, NOT optional, on session start, the root session becomes the architect and obeys the protocol.
