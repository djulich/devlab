# Durable Research Sessions

Status: **in progress**. Phases 1 and 2 are implemented through bounded
researcher invocation and durable result completion; exact-route resume
consumption and reporting remain.

This plan adds an on-demand, bounded research session that an architect,
planner, or developer can request when a discoverable fact cannot be resolved
reliably within the requesting role's session. The result becomes a durable,
validated workflow artifact and DevLab then resumes the interrupted route.

The first implementation is deliberately a concrete DevLab software-workflow
capability. It should expose potentially reusable mechanics clearly, but it
must not extract a domain-neutral workflow kernel before a second workflow
demonstrates that the same semantics are genuinely shared.

## Goal

DevLab should let a role stop boundedly for research without guessing, losing
its route, or relying on conversational memory.

The initial vertical slice should provide these outcomes:

- architect, planner, and developer sessions can request one research question
  through the structured session-result contract;
- DevLab records the question and exact resume route before invoking any
  researcher;
- one bounded researcher session produces a validated result with evidence,
  sources, recommendation, confidence, and unresolved questions;
- the canonical result is stored in the target repository with request and
  session provenance;
- the interrupted role resumes through the same command, role, task, and
  milestone route and receives the result in its prompt;
- reporting and validation paths describe research state without mutating it;
- research does not directly change specifications, plans, tasks, findings,
  ADRs, dependencies, product files, or workflow transitions.

Research resolves discoverable facts. Clarification obtains operator intent.
When a question depends on a preference, requirement, risk acceptance, secret,
or authority that only the operator can provide, the role must request a
clarification instead.

## Architectural Boundary

The feature contains three deliberately distinct layers.

### Potentially reusable workflow mechanics

- accept a typed request from a bounded role session;
- durably interrupt and preserve the exact requesting route;
- invoke one bounded auxiliary session;
- validate and persist its result and provenance;
- resume only the preserved route;
- retain recoverable state across process failure, session limits, and restart.

These mechanics are a candidate for a future kernel, not a new abstraction to
extract in this change. Keep their representation explicit enough that a later
second workflow can compare semantics against them.

### Research capability

- question, context, desired outcome, and acceptance criteria;
- evidence and source references;
- recommendation and rationale;
- confidence and unresolved questions;
- a completed result even when the evidence is inconclusive.

This schema may eventually be useful outside software development, but the
first implementation belongs to DevLab.

### Software-workflow policy

- only architect, planner, and developer may request research initially;
- the requesting command and route determine how work resumes;
- the resumed software role decides whether the result changes a design plan,
  ADR, dependency choice, task, implementation, or later transition;
- reviewer and integrator requests are deferred until usage demonstrates how
  auxiliary research should interact with their judgment and task/milestone
  transition contracts;
- research results are supporting evidence, not operator decisions or automatic
  workflow authority.

Do not add configurable role eligibility or generic request-type registration.
Those are correctness-critical policy and should remain enforced in code.

## Lifecycle and State Machine

Use a separate research record rather than extending clarifications or findings.

```text
requesting role submits needs_research
  -> DevLab validates request and creates requested research record
  -> DevLab stores the exact resume route
  -> researcher session runs
     -> valid result: record completed result, then resume requesting route
     -> operational/invalid-output failure: keep request and resume route durable
     -> session limit before invocation: stop successfully with research pending
  -> resumed role consumes result
  -> resume pointer clears only after the matching role session is accepted
```

`requested` means the question still needs a researcher session. `completed`
means a structurally valid result exists; it does not mean the recommendation
is correct or the evidence is conclusive. A low-confidence result with explicit
unresolved questions is valid and should return judgment to the requesting
role.

Do not add a `failed` terminal research status initially. Provider failures,
invalid result artifacts, and interrupted processes are retryable session
failures while the record remains `requested`. If live usage later needs
operator cancellation or abandonment, design it as an explicit durable
operation rather than inferring it from an invocation failure.

The run loop must inspect an active research resume pointer before ordinary
role selection. This permits a later invocation of the same command to run the
pending researcher after a session-limit stop or process restart.

The requester and researcher each consume one session from `max_sessions`.
DevLab must never exceed the bound to finish research automatically.

## Durable Storage

Add a file-backed tracker and canonical records:

```text
.devlab/research/
  RS0001_postgresql-advisory-lock-semantics.md
```

Suggested front matter:

```toml
+++
id = "RS0001"
title = "PostgreSQL advisory-lock semantics"
status = "requested"
asking_role = "planner"
asking_session_id = "20260811T101500_002_planner"
command = "plan"
scope = "milestone:M2"
task = ""
milestone = "M2"
created_at = "2026-08-11T10:15:00Z"
+++
```

Canonical request body:

```md
# RS0001: PostgreSQL advisory-lock semantics

## Question
Can a session-scoped PostgreSQL advisory lock safely serialize these workers?

## Context
The design needs one active scheduler across multiple service replicas.

## Desired Outcome
Recommend a locking approach and identify cleanup behavior after disconnects.

## Acceptance Criteria
- Compare session-level and transaction-level advisory locks.
- Use PostgreSQL primary documentation.
- Explain failure and connection-pool implications.
```

After successful research, the tracker changes `status` to `completed`, adds
`researcher_session_id`, `researcher_provider`, `researcher_model`, and
`completed_at` from accepted session metadata, and appends canonical result
sections. If a provider exposes no stable model identifier, preserve an empty
model value rather than inventing one:

```md
## Summary
...

## Evidence
- Claim supported by source S1.

## Sources
- S1: PostgreSQL documentation — https://...

## Recommendation
...

## Confidence
medium

## Unresolved Questions
- Whether the target connection pool guarantees connection affinity.
```

Allowed confidence values are `high`, `medium`, and `low`. Evidence entries
should cite source IDs. Sources may be URLs, repository-relative paths, or
stable identifiers such as standards and package documentation. Require at
least one source, but do not require a network URL: repository research and
offline authoritative material are valid.

Research record parsing and mutation belong in a focused `research.py` tracker.
Expose reads through `WorkspaceSnapshot` and mutations through a
`Workspace.research()` handle. Other modules must not parse research files
directly.

## Request Contract

Extend the structured session-result candidate with:

```toml
outcome = "needs_research"

[research]
title = "PostgreSQL advisory-lock semantics"
scope = "milestone:M2"
question = "Can a session-scoped PostgreSQL advisory lock safely serialize these workers?"
context = "The design needs one active scheduler across multiple service replicas."
desired_outcome = "Recommend a locking approach and identify cleanup behavior."
acceptance_criteria = [
  "Compare session-level and transaction-level advisory locks.",
  "Use PostgreSQL primary documentation.",
  "Explain failure and connection-pool implications.",
]
```

Validation rules:

- `[research]` is required exactly when `outcome = "needs_research"`;
- only architect, planner, and developer candidates accept that outcome;
- title, question, context, desired outcome, and acceptance criteria are
  non-empty and size-bounded consistently with other candidate fields;
- scope uses the established workspace/planning/milestone/task vocabulary and
  must agree with the active route where one exists;
- one candidate requests at most one research session;
- clarification and research are mutually exclusive in one candidate;
- role-specific state transitions, developer validation, planning completion,
  and commit/tag effects do not occur for a request outcome;
- changed product/workflow artifacts are rejected or restored according to the
  same request-session isolation policy used for clarification requests.

The canonical handoff renderer may include a `## Research Request` section for
human inspection, but structured TOML remains the authoritative submission.

## Researcher Role and Result Contract

Add a packaged minimal researcher prompt and an auxiliary role name such as
`researcher`. Like `clarification-resolver`, this is invoked by orchestration
and is not selected by `WorkspaceSnapshot.assess_state()` as an ordinary
software role.

The researcher should receive:

- the canonical request record;
- concise target-workspace context and relevant ADR/spec/plan/task material;
- source-quality and citation requirements;
- an explicit prohibition on editing authoritative workspace artifacts;
- the exact path and schema for its result candidate.

Do not automatically load every workspace artifact. Initial relevance rules
should be deterministic and conservative: include the request, target context,
ADR index or directly relevant ADRs, active design/project plan, and the active
task when applicable. Report its estimated prompt size through the existing
prompt-context facilities where practical.

The researcher writes only a staged JSON or TOML result under:

```text
.devlab/session-artifacts/researcher/result.json
```

Suggested result shape:

```json
{
  "schema_version": 1,
  "research_id": "RS0001",
  "summary": "...",
  "evidence": [
    {"claim": "...", "source_ids": ["S1"]}
  ],
  "sources": [
    {"id": "S1", "title": "...", "location": "https://...", "source_type": "primary"}
  ],
  "recommendation": "...",
  "confidence": "medium",
  "unresolved_questions": ["..."]
}
```

Validation must reject unknown fields, duplicate source IDs, evidence that
references unknown sources, empty required fields, unsupported schema versions,
and a mismatched research ID. It should not attempt to prove that a URL or claim
is true. Source verification remains researcher judgment and later role review;
the contract enforces inspectability and internal consistency.

Researcher workspace changes outside its staged result are forbidden. Snapshot
and restore/reject them using the established clarification-resolver containment
approach, with authoritative `.devlab` state always protected. The orchestrator,
not the researcher, converts the validated candidate into the canonical record.

Resolve the researcher through normal agent configuration with an explicit
fallback policy documented and tested. Prefer a dedicated `[roles.researcher]`
configuration when present; otherwise inherit the blocked role's resolved
provider configuration so existing workspaces do not require an immediate
configuration migration. Include the effective executable configuration in the
existing fingerprint and authorization model before it can be invoked.

## Resume Semantics

Reuse the single `[resume]` workflow-state slot, but make its blocker kind
explicit rather than teaching reporting code to infer meaning only from an ID
prefix. Extend `ResumeState` with a compatible discriminator such as:

```toml
[resume]
blocked_by = "RS0001"
blocked_kind = "research"
command = "plan"
role = "planner"
task = ""
milestone = "M2"
```

Existing clarification state without `blocked_kind` must continue to parse as
`clarification` during a compatibility window. New writes should always include
the discriminator. Do not add a second independent resume pointer: only one
workflow route can be interrupted at a time.

After a valid result, keep the resume pointer while the requesting role is
being resumed. Clear it only after an accepted matching session that does not
create another research or clarification request. Route validation must fail
closed if the command, role, task, or milestone no longer matches.

If the resumed role requests follow-up research, create a new research record
and replace the resume blocker while preserving the same route. `max_sessions`
continues to provide the outer bound. Diagnostics should count this explicitly
so repeated research does not become invisible looping.

## Prompt Integration

The matching resumed role prompt should include the completed research record
in a clearly labeled section with:

- research ID and original question;
- summary, evidence, sources, recommendation, confidence, and unresolved
  questions;
- instruction that the result is evidence, not an automatic requirement;
- instruction to request operator clarification if remaining uncertainty is a
  choice rather than a discoverable fact.

Initially include the completed record only through the active resume route.
Do not add all historical research to every prompt. Later roles can discover
committed research files through normal workspace access, and evidence from
live usage can justify scoped indexes or explicit reference metadata later.

## Orchestration and Ownership

Keep responsibilities in their existing owners:

- `research.py`: record schema, parsing, formatting, ID allocation, and tracker
  mutations;
- `workspace.py`: cached research reads and mutation handle;
- `handoffs.py`: requesting-role candidate parsing and validation;
- `prompts.py` and packaged prompt resources: researcher and resumed-role prompt
  assembly;
- `agent_config.py`, `roles.py`, and `agents.py`: role resolution and
  provider-specific invocation without moving route policy into providers;
- `workflow_state.py`: compatible typed resume blocker;
- `orchestrator.py`: eligibility, interruption, auxiliary invocation, result
  processing, exact-route resume, session bounds, and recovery;
- reporting/doctor/diagnostics modules: read-only presentation and validation;
- `session_logging.py` and session metadata: researcher lifecycle and
  provenance reporting.

When this substantial orchestration feature lands, reassess `run_loop` as
recommended by `docs/plans/orchestrator-quality-improvements.md`. Extract only
a cohesive session-invocation or auxiliary-session slice if it reduces
duplication without hiding workflow transition policy. Do not create a generic
kernel module merely to share researcher and clarification-resolver code.

## Reporting, Diagnostics, and Events

Update operator-facing output so a pending request is distinguishable from an
operator clarification:

- `devlab status` and verbose workflow-state reporting show the research ID,
  question/title, requesting route, and whether the next action is to run the
  researcher or resume the requesting role;
- `devlab doctor` validates record filenames, IDs, status/result consistency,
  active resume references, route fields, and staged-artifact hygiene;
- run summaries use an existing command (`devlab plan` or `devlab implement`)
  as the next command rather than introducing `devlab research` initially;
- append workflow events for `research_requested`, `research_completed`, and
  optionally `research_resume_completed` with IDs and route provenance;
- diagnostics report request count, researcher session count, low-confidence
  results, unresolved-question totals, and repeated requests on one route.

Reporting, doctor, prompt-size inspection, and diagnostics must remain
read-only. They must never create a record, repair status, clear a pointer, or
run a researcher.

## Failure and Recovery Behavior

Specify and test these boundaries:

- crash after record creation but before resume-state write cannot leave an
  ambiguous runnable route; the transition helper must fail closed whenever a
  requested record and resume pointer are an incomplete pair, and doctor must
  identify the inconsistency;
- crash after resume-state write but before researcher invocation resumes by
  invoking the researcher;
- provider failure or invalid researcher output leaves the request `requested`
  and preserves the route for an explicit retry;
- crash after result persistence but before requester invocation resumes the
  requesting role without rerunning research;
- crash after the matching requester result is accepted but before pointer
  clearing is handled idempotently without repeating committed workflow effects;
- executable-configuration changes follow the existing frozen-snapshot and
  authorization boundary; research must not bypass the successful interruption
  behavior introduced for configuration-changing task cycles;
- automatic version control commits the durable request/result at the same safe
  boundaries used for other session artifacts and never commits forbidden
  researcher edits.

Prefer explicit, idempotent transition helpers over prose-based recovery. If
the current single resume write cannot provide an atomic enough transition,
record an append-only workflow event or add a narrowly defined state field;
do not rely on session logs as authoritative state.

## Implementation Phases

### Phase 1: Records and request contract

1. Add research domain types, tracker, canonical formatting, and focused tests.
   Detailed task plan: [`research-domain-tracker.md`](research-domain-tracker.md).
2. Expose read/mutation access through `WorkspaceSnapshot` and `Workspace`.
   Implemented with cached snapshot queries and invalidating mutation handles.
3. Extend structured session results and handoff rendering with
   `needs_research` and `[research]`.
   Implemented with strict candidate parsing, canonical result/handoff
   round trips, and packaged submission guidance.
4. Enforce requesting-role eligibility, scope/route consistency, exclusivity
   with clarification, and no normal role transition.
   Implemented with exact active-route validation before durable mutation and
   request outcomes isolated from ordinary role transitions and validation.
5. Add the compatible typed resume blocker and doctor validation. Implemented
   with legacy clarification compatibility and read-only record/pointer checks.

At the end of this phase, a request can be durably recorded but should stop
safely with `research_pending` because automatic researcher invocation is not
yet implemented.

### Phase 2: Bounded researcher invocation

Implemented with a minimal auxiliary-role prompt, strict staged JSON result
schema, explicit provider configuration with requesting-role fallback,
conservative prompt context, workspace edit isolation, canonical completion
with session provenance, workflow events, bounded session accounting, and
retryable requested state on failure.

### Phase 3: Exact-route resume

1. Route requested research before ordinary role selection on restart.
2. Include completed results only in the matching resumed-role prompt.
3. Validate command/role/task/milestone identity before continuation.
4. Clear or replace the resume pointer only at the defined accepted-session
   boundary.
5. Cover follow-up research, clarification after research, session limits, and
   process-restart behavior.

### Phase 4: Reporting and documentation

1. Extend status, workflow-state reports, run summaries, doctor, session
   history, and diagnostics.
2. Document the research/clarification distinction, agent configuration,
   artifact schema, retry behavior, and trust boundary in the operator guide,
   design overview, README, context terminology, and packaged conventions.
3. Add a deterministic evaluation in which a planning or development route
   requests research, consumes its result, and completes without hidden state.
4. Refresh `docs/todo.md` to describe implemented behavior and evidence-driven
   follow-ups.

## Required Tests

Add focused coverage for at least:

- tracker round trips, ID allocation, malformed front matter, and status/result
  consistency;
- request-candidate parsing, role eligibility, route scope, mutual exclusion,
  and role-transition suppression;
- backward-compatible clarification resume parsing plus typed new writes;
- workspace snapshot caching and mutation invalidation;
- researcher result schema, citations, duplicate/unknown sources, confidence,
  and mismatched IDs;
- forbidden researcher edits and preservation of authoritative workflow files;
- session-limit stop before research and restart into the pending researcher;
- provider failure, malformed result, successful result, and low-confidence
  inconclusive result;
- exact planner, architect, and developer route resume;
- stale or mismatched route rejection;
- pointer persistence and clearing across each failure boundary;
- automatic version-control and executable-configuration authorization behavior;
- read-only status, doctor, prompt reporting, and diagnostics;
- an end-to-end scripted workflow containing request, research, resume, and
  ordinary completion.

Run the complete development validation for implementation changes:

```bash
make check
```

## Acceptance Criteria

The feature is complete when:

- a supported software role can request one discoverable-fact investigation
  through a code-validated contract;
- the request and exact resume route survive session limits and process restart;
- exactly one bounded researcher session can produce a canonical result with
  validated evidence/source references and session provenance;
- incomplete research is representable honestly through confidence and
  unresolved questions without becoming a failed workflow transition;
- the requesting route consumes the result and only then clears the resume
  pointer;
- research cannot directly mutate product or authoritative workflow artifacts;
- clarification remains the only route for operator intent;
- status, doctor, summaries, events, diagnostics, and documentation expose the
  lifecycle without mutating it;
- workflow policy remains explicit in DevLab and no speculative generic kernel,
  role registry, or configurable transition policy is introduced;
- focused tests and `make check` pass.

## Deferred Work

- reviewer or integrator research requests;
- multiple parallel or concurrent research requests;
- operator-created ad hoc research outside an interrupted workflow route;
- a standalone `devlab research` command;
- automatic source retrieval, URL reachability checks, or factual verification;
- automatic ADR, task, plan, dependency, finding, or specification mutation
  from a result;
- global research indexes or automatic inclusion of all historical research;
- cancellation/abandonment operations without evidence from live use;
- extracting a generic subordinate-session or workflow-kernel API;
- moving the capability into a shared research package before another concrete
  domain validates its semantics.
