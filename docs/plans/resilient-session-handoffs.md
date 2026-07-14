# Resilient Session Handoffs

Status: active.

## Purpose

Replace direct agent authorship of authoritative handoff files with an
orchestrator-owned submission protocol. Agents propose a small structured session
result; DevLab validates it during the same role session and publishes the
canonical result and human-readable handoff only after acceptance.

This plan is the implementation reference for the handoff boundary. The broader
cross-cutting concerns remain in `architectural-improvements.md`; atomic tracker
writes and general concurrent-process policy are not expanded into this feature.

## Problem

The current handoff is simultaneously:

- a human-readable account of the completed role session;
- context for later role sessions;
- a machine-readable source of workflow transition facts.

A nondeterministic agent directly writes the authoritative Markdown artifact,
then exits. The orchestrator subsequently recovers control facts by strictly
parsing headings, embedded structured sections, identifiers, and prose
conventions. A representation mistake can therefore stop an otherwise successful
session after the agent best able to correct it has gone away.

Repairing malformed final Markdown can reduce failures, but it preserves the
wrong ownership boundary and requires additional classification, isolation,
retry, and provenance machinery. DevLab should instead accept or reject a
candidate while the original role session is active.

The fundamental distinction is:

```text
Agent owns: proposed transition facts and narrative content.
DevLab owns: session identity, validation, authoritative publication, and
workflow transitions.
```

Structured syntax reduces transport and contract uncertainty. It does not prove
that claims are true, so DevLab must continue validating accepted values against
durable workspace state.

## Goals

- Give every role session a small, versioned, role-aware result schema.
- Let the original agent submit, receive complete actionable validation feedback,
  correct the candidate, and resubmit before exiting.
- Derive trusted identity and observable facts instead of asking the agent to
  reproduce them.
- Publish authoritative session results and Markdown handoffs only through
  DevLab-owned code.
- Complete all semantic validation before applying handoff-driven workflow
  mutations.
- Give failures stable typed reasons without branching on message text.
- Preserve current downstream human and prompt access to readable handoffs.
- Bound submission attempts operationally and measure their cost across
  providers and roles.
- Retain one role per session and one task per developer/reviewer session.
- Provide one constrained correction session only when the original role exits
  without an accepted result.

## Non-goals

- Do not make a normal role retry the response to a missing or invalid result.
- Do not initially introduce a `handoff-fixer` workflow role.
- Do not trust schema-valid claims without semantic validation.
- Do not let a correction session edit product files or durable workflow state.
- Do not add unbounded submission or correction loops.
- Do not require provider-specific structured-output support.
- Do not add concurrent agents, broad workspace rollback, or a database.
- Do not redesign task, finding, milestone, or clarification storage as part of
  the submission protocol.

## Target Flow

Use this lifecycle for each role session:

```text
DevLab creates trusted session envelope and role-specific candidate template
    -> agent performs ordinary role work
    -> agent fills candidate and invokes submission command/tool
    -> DevLab validates syntax, contract, and workspace semantics
       -> rejected: return all actionable errors to the same agent
       -> accepted: atomically publish canonical result and Markdown handoff
    -> agent exits only after acceptance
    -> outer orchestrator verifies the accepted result
    -> apply workflow transitions, archive, and integrate version control
```

If the agent exits without acceptance, the outer orchestrator may invoke one
opt-in constrained correction session. The correction must use the same
submission operation and cannot directly publish or edit authoritative results.

## Session Envelope

Before invoking a role, DevLab should create a trusted session envelope such as:

```toml
schema_version = 1
session_id = "20260715T101500_002_developer"
role = "developer"
task = "T0041"
milestone = "M0003"
```

The envelope is orchestrator-owned. The candidate must not repeat fields that
DevLab already knows, including role, session ID, active task, active milestone,
or requested workflow command.

The submission process must bind to the active envelope without trusting a path
or identity supplied by the candidate. The implementation may use an invocation
environment variable plus the envelope path, but correctness must not depend on
security through obscurity. DevLab agents already have target-workspace access;
the boundary protects protocol integrity rather than defending against a
malicious local process.

## Candidate Schema

Start with TOML because DevLab already uses it and Python can parse it without a
new dependency. Keep the schema deliberately small:

```toml
schema_version = 1
outcome = "completed"
commit_message = "Implement session timeout validation"

done = [
  "Added idle and absolute timeout validation.",
  "Added timeout boundary tests.",
]
changed_artifacts = [
  "src/auth/session.py",
  "tests/test_session.py",
]
open_issues = []
addressed_findings = []
next_session_hint = "Review boundary behavior and error responses."
```

Common outcomes should initially be limited to:

- `completed`;
- `needs_clarification`;
- `failed`.

Add role-specific fields only where the orchestrator needs an explicit assertion:

```toml
# planner
planning_complete = false

# reviewer
review_outcome = "approved"
```

Clarification requests should be native structured data rather than TOML embedded
inside Markdown. Keep their existing domain semantics and stable choice IDs.

Do not duplicate observable facts unnecessarily. DevLab should derive or verify:

- changed paths from the session/workspace baseline;
- eligible addressed findings from the active task and trackers;
- allowed outcomes and role-specific fields from the active role;
- task, milestone, role, session, and command identity from the envelope.

The agent may summarize changed artifacts for narrative quality, but the
orchestrator must use its own changed-path evidence for safety decisions.

## Candidate Creation

Provide a command that writes the correct role-specific template, for example:

```bash
devlab session handoff init
```

It should create or refresh only the active session's disposable candidate. The
template should include allowed enum values or concise comments where TOML
permits them. Agents fill values rather than reconstructing the schema from a
prompt.

Prompt instructions should be compact:

```text
Before exiting, submit the session result with:

  devlab session handoff submit

The session is complete only when DevLab reports Accepted. Correct any reported
errors and resubmit. Do not edit the published result or handoff directly.
```

Provider-native typed tools may later invoke the same application operation, but
the CLI is the portable baseline and the core operation must not depend on a
specific provider.

## Submission and Validation

Add a reusable application operation behind a CLI adapter. Exact module and type
names can follow the implementation shape, but responsibilities must remain:

- `handoffs.py` owns candidate/result schemas, parsing, and contract validation;
- `orchestrator.py` owns role-specific workflow policy and semantic acceptance;
- `WorkspaceSnapshot` supplies cached read-only cross-domain state;
- `Workspace` handles remain the mutation boundary after acceptance;
- `agents.py` contains only provider-specific invocation mechanics;
- `cli.py` adapts the in-session command without owning validation policy.

The submit operation should:

1. Load the trusted active envelope.
2. Parse the candidate with explicit size limits.
3. Validate its version and common schema.
4. Validate role-specific fields and outcomes.
5. Validate references and assertions against a fresh read-only snapshot.
6. Return all independently detectable errors in one response.
7. On success, publish the canonical structured result and rendered Markdown
   handoff atomically.

Rejection must not mutate workflow state or publish a partial result. Diagnostics
should name the field, rejected value, allowed values where useful, and the
authoritative state causing a conflict.

Example:

```text
Handoff rejected:

1. review_outcome
   Expected one of: approved, changes_requested.
   Received: passed.

2. addressed_findings[0]
   F0099 is not associated with active task T0041.
   Allowed values: F0012, F0014.

All other fields are valid. Correct the candidate and submit it again.
```

## Typed Failures

Use stable reason codes internally and render human-readable messages only at
adapter boundaries. Do not branch on exception text.

Initial categories should cover:

| Category | Examples | Same-session action |
| --- | --- | --- |
| Syntax | malformed TOML, unsupported encoding | correct candidate |
| Contract | missing field, wrong type, invalid enum, forbidden role field | correct candidate |
| Reference | unknown or ineligible task/finding/milestone | inspect authoritative state and correct |
| Semantic conflict | reviewer/planner assertion contradicts workspace state | correct if evidence supports it; otherwise report failure or clarification |
| Safety/limits | oversized candidate, invalid path, forbidden changed state | stop or produce a safe failure result |
| Session protocol | missing/stale envelope, submission after acceptance | stop and report orchestrator error |

The result type should retain all failures so one submission does not produce a
sequence of avoidable single-field retries.

## Validation Before Mutation

The submission operation is read-only until publication, and publication itself
does not apply task, finding, milestone, clarification, or planner workflow
transitions. The outer orchestrator applies those transitions only after it
observes a fully accepted result.

Refactor the current post-session path into:

1. **Accept**: validate candidate syntax, contract, and semantic preconditions;
   publish canonical artifacts.
2. **Apply**: consume the accepted result, update domain state, archive, and
   perform version-control integration.

Planner consistency checks must occur before `_apply_planner_workflow_state()`.
Every rejected candidate and every missing-result stop must leave
handoff-driven workflow state unchanged.

Publication should use a shared atomic replacement helper when available. Until
that architectural slice lands, use the narrowest safe implementation without
moving file-format ownership out of `handoffs.py`.

## Canonical Result and Markdown Handoff

On acceptance, DevLab writes an authoritative structured result containing the
trusted envelope identity plus validated candidate values. Agents must not edit
this file directly.

DevLab also renders the existing Markdown handoff shape from accepted data so
operators and later prompts retain readable context. The orchestrator must not
parse rendered Markdown for workflow decisions. During migration, compatibility
readers may support older workspaces and history artifacts, but new sessions use
the accepted structured result as their control interface.

Archive both canonical result and rendered handoff with the same session
identity. Diagnostics should make their relationship explicit.

## Submission Budget and Efficiency

Submission validation is a local operation inside the existing role session, not
a new model session. Still, repeated correction consumes tokens and time, so
DevLab must measure rather than normalize retries.

Record at least:

- number of candidate submissions;
- rejection reasons per submission;
- time from first submission to acceptance;
- whether a candidate was accepted on the first attempt;
- provider, role, and schema version;
- whether an outer correction session was required.

Initial design targets are:

- median submissions per successful role session: `1`;
- 95th percentile submissions: no more than `2`;
- mechanical syntax/shape rejection after template initialization: exceptional;
- no ordinary session should make more than three submissions automatically;
- one validation response should report all independently detectable problems.

These are acceptance targets, not assumed model-performance claims. If live
evaluation misses them, simplify the schema, derive more fields, improve
diagnostics, or use native structured tool adapters. Do not merely raise the
limit.

## Missing Accepted Result and Constrained Correction

The outer orchestrator decides success from an accepted canonical result, not
provider exit code or candidate existence.

After a successful provider exit:

- accepted result exists: continue normally;
- rejected candidate exists but no accepted result: optionally invoke one
  constrained correction session with validation diagnostics;
- no candidate or result exists: optionally invoke one constrained correction
  session with the template, workspace evidence, and logs;
- correction does not produce acceptance: stop and preserve diagnostics.

Correction is opt-in initially because it invokes another paid session. It should
reuse the failed role/provider configuration before introducing a specialist.
The correction prompt must prohibit rerunning task work and require use of the
same submission operation.

Enforce that correction changes only disposable candidate state. Accepted
results, product files, and workflow state are forbidden. Allow exactly one
correction invocation and never recursively correct a correction result.

Do not add deterministic Markdown repair. Markdown is rendered from accepted
structured data and is no longer an agent-authored control artifact.

## Compatibility and Migration

Preserve existing handoff history and prompt context. The migration should:

- continue reading archived Markdown from older sessions;
- use canonical results for new workflow decisions;
- render new Markdown in a familiar shape;
- avoid rewriting historical artifacts;
- keep current CLI exit-code behavior unless structured `RunResult` policy is
  changed separately;
- version the candidate and canonical result schemas from the first release.

Decide explicitly whether an in-progress workspace created by an older DevLab
version may finish its active session through the legacy handoff path or must
restart that session with a new envelope. Prefer a clear diagnostic over silent
mixed-protocol inference.

## Implementation Slices

### 1. Read-only acceptance boundary and typed failures

- Add typed validation reasons and aggregate diagnostics.
- Reorder current semantic checks so all validation precedes handoff-driven
  mutation, especially planner workflow-state application.
- Add focused no-mutation tests for every failure path.
- Preserve valid legacy handoff behavior in this preparatory slice.

### 2. Versioned candidate, envelope, and canonical result

- Define minimal common and role-specific schemas in `handoffs.py`.
- Create trusted session envelopes before role invocation.
- Add role-specific candidate template generation.
- Add parsing, size limits, canonical result rendering, and Markdown rendering.
- Unit test schema boundaries and round trips independently of orchestration.

### 3. In-session submission operation

- Add reusable submit/validate application logic and CLI adapter.
- Bind submission to the active envelope.
- Validate against a fresh `WorkspaceSnapshot` without domain mutation.
- Aggregate actionable errors and atomically publish only accepted results.
- Update packaged role prompts to require acceptance before exit.

### 4. Orchestrator consumption and compatibility

- Make `run_loop()` require an accepted result for new-protocol sessions.
- Apply transitions only after acceptance.
- Archive structured and rendered artifacts together.
- Retain legacy history display and prompt assembly.
- Add end-to-end tests for each role and outcome.

### 5. Efficiency evaluation and refinement

- Add scripted rejection/correction scenarios.
- Run representative live sessions across configured providers and roles.
- Report first-attempt acceptance, submission counts, rejection categories,
  latency, and semantic conflicts.
- Simplify or derive fields until the submission-budget targets are met.

### 6. One constrained correction invocation

- Add opt-in configuration for one correction session.
- Reuse original role/provider configuration with a correction-only prompt.
- Enforce candidate-only changes and require normal submission acceptance.
- Test missing candidate, rejected candidate, provider failure, forbidden edits,
  still-invalid correction, and no recursive retry.

### 7. Optional native tool adapters

If provider capabilities and evaluation evidence justify it, expose the same
submission operation as a provider-native typed tool. Keep schema and semantic
acceptance provider-neutral and retain the CLI baseline.

Only consider a separately configurable handoff specialist if correction-session
evaluations demonstrate a material advantage.

## Testing

Focused tests should cover:

- every typed failure category and aggregate diagnostics;
- rejected candidates causing no workflow-domain mutation;
- role-specific template generation and schema enforcement;
- trusted identity coming from the envelope rather than candidate content;
- semantic conflicts against tasks, findings, milestones, and planner state;
- successful acceptance and atomic canonical publication;
- canonical Markdown rendering without reparsing for decisions;
- valid accepted results preserving existing role transitions;
- legacy history and prompt compatibility;
- provider success without an accepted result;
- submission metrics and attempt bounds;
- one successful constrained correction;
- correction provider failure, forbidden edits, and no second correction;
- unchanged CLI exit behavior for unrecovered failures.

Run after each slice:

```bash
uv --cache-dir /tmp/uv-cache run ruff check src tests
uv --cache-dir /tmp/uv-cache run pytest
```

## Completion Criteria

The initial feature is complete when new role sessions initialize a versioned
candidate, receive actionable same-session validation feedback, and cause DevLab
to publish canonical structured and Markdown artifacts only after semantic
acceptance; rejected or missing results leave handoff-driven workflow state
unchanged; representative evaluations meet the submission-budget targets; and
one opt-in correction session safely handles the exceptional missing-acceptance
case.
