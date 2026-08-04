# Unattended Workflow Progress and Rework Reduction

## Context

A partial unattended DevLab run against a broad trading-bot specification exposed
three related workflow weaknesses:

- every implemented task entered at least one developer/reviewer rework cycle;
- the run used 28 role sessions while only three tasks had closed and a fourth was
  still active;
- a developer session claimed completion without changing product code or advancing
  task state, after which DevLab committed session artifacts and selected the same
  developer route again.

The observed rework had different causes and should not be treated as one metric:

- one task needed only a missing validation statement in a developer handoff;
- one task had a genuine environment-loading defect;
- one task omitted invariants and audit contracts required by an ADR;
- one large persistence task exposed scope, replay, temporal, and migration-upgrade
  defects over several successive reviews.

The final duplicate developer session occurred because the agent reported a
successful fix but left one broad acceptance criterion unchecked. DevLab accepted
the handoff, did not move the task from `changes_requested` to `in_review`, committed
workflow artifacts, and selected the developer again.

## Goal

Reduce procedural rework, repeated no-progress sessions, and fragmented reviewer
feedback while preserving:

- unattended operation whenever another bounded action has a reasonable chance of
  advancing the workflow;
- independent developer and reviewer roles;
- one task per developer/reviewer session;
- durable, auditable workflow state;
- conservative transitions that do not approve incomplete work;
- target-owned validation and environment policy;
- clean failure when continued agent invocation is unlikely to help.

The governing rule is:

> Continue when one bounded action has a reasonable chance of advancing the
> workflow; stop before repeating an action that has already failed to produce
> progress.

## Implementation Status

Implemented on 2026-08-05. The delivered policy keeps profile-default validation
failure soft at task level, while explicit task validation receives one bounded
developer correction before `validation_failed`. This distinction was confirmed by
the mixed-language scripted evaluation: a repository-wide profile command can be
expected to fail after the first task in an intentionally incremental milestone.

Implemented behavior includes semantic developer submission validation, restricted
checkbox correction, durable session-progress events and diagnostics, one bounded
non-advancing recovery, centralized validation resolution and records, bounded
explicit-task validation recovery, structural task gates, non-blocking compound
criterion warnings, and consolidated reviewer/scenario guidance. Live evaluation
remains continuous evidence for tuning heuristics and defaults, not a prerequisite
for enforcement.

## Non-Goals

This plan does not initially:

- combine developer and reviewer roles;
- permit reviewers to routinely implement non-trivial fixes;
- allow multiple tasks in one developer or reviewer session;
- skip integrator or architecture-review sessions automatically;
- reject every workflow-only commit;
- infer semantic acceptance solely from passing tests;
- make heuristic task-quality warnings blocking;
- change default agent models or reasoning effort without evaluation evidence.

## Design Principles

### Repair before restart

Errors found while the original agent is still active should be returned through
the session submission protocol. Correcting a handoff or task postcondition inside
that invocation is cheaper and better informed than starting another role session.

### Bound recovery

Unattended recovery is useful only while it is bounded. One narrowly scoped recovery
attempt is allowed where it has a clear chance of success. Repeating the same route
after that attempt is evidence of a stalled workflow and must stop cleanly.

### Classify facts, not claims

Progress classification uses repository and workflow facts. A handoff's
`changed_artifacts` and `done` claims are supporting evidence, not proof that the
repository or task state changed.

### Distinguish procedural and product rework

Diagnostics should not count a missing handoff statement as equivalent to a
reviewer finding a behavioral defect. First-pass approval and rework metrics should
identify why another cycle was needed.

### Deterministic evidence gates enforcement

Live evaluations are useful for measuring incidence and tuning policy, but they are
not a prerequisite for implementing later milestones. A live run that does not
reproduce a rare fault says little about guard correctness. Conservative enforcement
depends on deterministic regression and edge-case tests.

## Milestone 1: Semantic Handoff Validation and Bounded Repair

### Workspace-aware developer completion validation

Extend session handoff submission with role-specific semantic validation after the
candidate has been parsed but before an accepted result is published.

For a developer candidate with `outcome = "completed"`:

- resolve the assigned task through `WorkspaceSnapshot` and the task tracker;
- verify the task matches the session envelope and remains developable;
- require every acceptance criterion in the task's `## Acceptance Criteria`
  section to be checked;
- require an empty `open_issues` list;
- return precise submission errors, including the remaining unchecked criterion;
- do not change task status during submission.

The normal post-session handoff processing remains responsible for moving a
completed task to `in_review`. Outcomes `failed` and `needs_clarification` may retain
unchecked criteria.

Candidate syntax and generic result structure remain in `handoffs.py`.
Workspace-aware workflow policy belongs in `orchestrator.py`, using task storage only
through the workspace/task-tracker boundary.

Suggested internal shape:

```python
def _validate_candidate_against_workspace(
    snapshot: WorkspaceSnapshot,
    envelope: SessionEnvelope,
    candidate: HandoffCandidate,
) -> tuple[str, ...]:
    ...
```

### Same-session repair

`devlab session handoff submit` returns actionable semantic errors to the active
agent. The agent may edit its assigned task and handoff candidate, then resubmit
without consuming another session.

### One restricted recovery attempt

If the role process exits without resolving a semantic submission error, DevLab may
invoke one correction session. This is different from the existing artifact-only
repair for malformed handoff serialization.

The semantic correction session may edit only:

- acceptance-criteria checkboxes in the assigned task file;
- the active role's handoff candidate and published session artifacts.

It may not edit product code, task metadata or status, requested changes, plans,
milestones, findings, workflow state, profiles, or agent configuration. DevLab must
compare file content before and after correction and reject changes outside this
allowlist. If correction still fails, stop with `recovery_exhausted`. Do not create a
normal successful-session commit for an unaccepted session.

### Tests

- Completed developer result with all criteria checked is accepted.
- An unchecked criterion rejects submission and identifies the criterion.
- The original agent can repair and resubmit in the same session.
- `failed` and `needs_clarification` outcomes may leave criteria unchecked.
- Wrong, missing, closed, or non-developable assigned tasks are rejected.
- Semantic errors are not routed through artifact-only correction.
- Restricted recovery permits only the assigned checkbox and handoff artifacts.
- Forbidden recovery edits are detected.
- Exhausted recovery produces no successful-session commit.

## Milestone 2: Progress Classification and Diagnostics

### Progress facts

Capture a compact pre-session record at route selection:

- selected role, task, and milestone;
- task status;
- acceptance-criteria state;
- requested-changes digest;
- review approval state;
- milestone and workflow phase state;
- Git HEAD and a Git-relevant worktree baseline.

After handoff processing, classify the session:

```python
class SessionProgress(StrEnum):
    PRODUCT_CHANGE = "product_change"
    WORKFLOW_ADVANCE = "workflow_advance"
    LEGITIMATE_STOP = "legitimate_stop"
    NON_ADVANCING = "non_advancing"
```

Product change means a relevant Git-observed change outside `.devlab/`, including
product documentation and tests. Ignored caches and generated files do not count.

Workflow advance includes at least:

- a developer task moving to `in_review`;
- reviewer approval closing a task;
- reviewer rejection adding or changing actionable requested changes and setting
  `changes_requested`;
- planner creation or material update of plans, tasks, or planning state;
- milestone integration or architecture-review state advancing;
- a durable clarification or other legitimate bounded stop being created.

A workflow-only commit is not inherently wasteful. Approval, rejection, planning,
integration, and architecture-review transitions remain valid auditable sessions.

### Diagnostic-only rollout

Initial progress classification does not block or reroute the workflow. Add
diagnostics for:

- product-changing, workflow-advancing, legitimate-stop, and non-advancing counts;
- first-pass reviewer approval rate;
- procedural versus product rework;
- consecutive same-role/same-task sessions;
- recovery attempts and results;
- sessions whose handoff claims do not match Git-observed changes.

### Deterministic acceptance suite

M3 enforcement depends on deterministic tests, not on a stochastic live baseline.
Use a compact synthetic workspace fixture representing the relevant tbot state
rather than copying the target repository.

Required cases:

1. Exact failure shape:
   - task remains `changes_requested`;
   - developer claims completion;
   - an acceptance criterion remains unchecked;
   - only session artifacts change;
   - the next route would select the same developer and task.
2. Legitimate workflow-only progress:
   - reviewer approval;
   - reviewer rejection with new requested changes;
   - planner state/task changes;
   - integration and architecture-review transitions;
   - clarification creation.
3. Ambiguous changes:
   - only an acceptance checkbox changes;
   - only product documentation changes;
   - ignored validation artifacts appear;
   - claimed changed artifacts have no Git-observed change;
   - product changes are made and reverted before submission;
   - the same route remains valid despite some observable progress.
4. Recovery:
   - first non-progress result receives recovery;
   - recovery advances the task;
   - recovery also fails;
   - later meaningful progress resets consecutive-failure state.

### Pause condition

Pause M3 only if deterministic tests show that DevLab cannot conservatively
distinguish non-progress from legitimate progress using durable repository facts.
Examples include legitimate transitions with no observable durable difference,
unstable product-change classification, or recovery state that cannot survive a
crash. Failure to reproduce the fault in a live run is not a pause condition.

## Milestone 3: Bounded Non-Progress Enforcement

### Conservative stalled-session predicate

A developer session is stalled only when all of the following hold:

- the accepted result claims completion;
- no relevant product, test, or documentation artifact changed;
- task status did not advance;
- acceptance-criteria completion did not advance;
- requested changes did not change;
- no clarification or other legitimate stop was produced;
- DevLab would select the same role and task again.

Do not classify a session as stalled merely because it contains no product-code
change.

### First occurrence: one bounded recovery

On the first stalled result for a role/task pair:

- record durable recovery state so a crash cannot reset the allowance;
- invoke one developer recovery session;
- include precise evidence of what did not advance and what remains incomplete;
- require normal semantic submission and validation.

### Recurrence: stop

If the recovery session also satisfies the stalled predicate:

- stop before invoking a third session;
- report `stop_reason = "developer_non_advancing"`;
- retain failed-session diagnostic evidence;
- do not create another normal successful-session commit.

Any meaningful progress resets the consecutive stalled-session state.

### Tests

- First stalled session receives exactly one recovery.
- Successful recovery continues to review.
- Repeated stall stops before a third agent invocation.
- Crash/restart preserves the used recovery allowance.
- Legitimate workflow-only sessions never consume the allowance.
- Progress resets the allowance.

## Milestone 4: Orchestrator-Owned Validation with Graded Outcomes

This milestone extends the validation work already described in
`docs/plans/workflow-contract-hardening.md`; it must reuse that design rather than
introducing a competing validation subsystem.

### Effective validation resolution

Add one read-only helper used by prompt assembly, execution, status, and
diagnostics:

```python
@dataclass(frozen=True)
class EffectiveValidation:
    source: Literal["task", "profile", "none"]
    commands: tuple[str, ...]
```

Resolution rules:

- explicit non-empty task `validation` wins;
- omitted task validation uses resolved profile defaults;
- explicit `validation = []` means no required validation;
- absent profile defaults also means none.

### Durable validation results

Record each command's:

- resolved source and command;
- task, role, session, and repository revision;
- outcome, exit code, and duration;
- bounded output summary;
- retry/recovery relationship where applicable.

Outcomes are distinct:

- `passed`;
- `failed`;
- `missing_tool`;
- `timeout`;
- `infrastructure_error`;
- `not_configured`.

### Task-level unattended policy

- `passed`: move the task to review.
- `failed`: provide the command evidence to one bounded developer correction
  session.
- repeated deterministic failure: stop with `validation_failed`.
- `missing_tool`: record an unverified user/CI prerequisite; do not install it.
- `infrastructure_error`: stop without treating the product as reviewer-rejected.
- `timeout`: retry once only when configuration explicitly permits retry.
- `not_configured`: warn and proceed to review.

Milestone-level configured validation remains strict: known failure prevents
integration and follows the integration-finding policy from the workflow contract
hardening plan.

Commands must run only through trusted target configuration and the existing profile
environment lifecycle. DevLab must not install missing host tools.

### Remove prose-only validation gates

Mechanical validation facts become orchestrator-owned. Developer handoffs need only
explain manual checks or validation that DevLab cannot infer. In particular, an
empty validation configuration must not require an otherwise useless
developer/reviewer cycle merely to add a prose statement.

## Milestone 5: Conservative Task Quality Gates

### Structural hard errors

Prevent developer selection for deterministic contract failures:

- missing or empty goal;
- missing acceptance-criteria section;
- no acceptance checkboxes;
- unknown milestone, profile, dependency, or finding references;
- dependency cycles;
- malformed validation metadata.

Expose these errors through `doctor`, status, and planner context. Implement the
checks over task tracker/workspace abstractions rather than parsing task files in
diagnostic or orchestration paths.

### Semantic warnings

Warn without blocking for:

- vague criteria;
- compound criteria containing independently falsifiable claims;
- acceptance claims without observable verification;
- likely missing isolation, temporal, replay, failure, or schema-upgrade cases.

Show warnings to planner and developer sessions so agents can improve the work
packet autonomously. No semantic warning becomes a hard gate without accumulated
evaluation evidence demonstrating a low false-positive rate.

## Milestone 6: First-Pass Review Completeness

### Reusable scenario guidance

Add concise domain guidance for applicable stateful/persistence tasks. Planner,
developer, and reviewer should deliberately consider:

- identity and scope isolation;
- incremental/replay equivalence;
- historical correctness after later changes;
- atomic rollback and retry/idempotency;
- upgrade from supported prior schema representations;
- unsupported version behavior.

Keep this guidance in the narrowest existing domain prompt that owns the concern.
Do not inflate the general role prompt or create a new domain unless the guidance is
reusable across tasks.

### Consolidated reviewer findings

Update reviewer instructions so discovering one rejection-worthy defect does not end
the review. The reviewer continues through all acceptance criteria, directly
relevant specifications, migrations, tests, and documentation, then returns all
currently discoverable actionable issues in one rejection.

Reviewers should distinguish:

- defects present in the submitted implementation;
- defects introduced by a corrective change;
- contradictions or gaps that require replanning rather than implementation.

Prefer prompt and evaluation changes over a larger handoff schema unless structured
diagnostic needs later justify new fields.

Tests and evaluations should include a task with two independent defects and verify
that the first reviewer reports both.

## Stop Reasons

Add explicit stop reasons where the corresponding behavior is implemented:

- `task_contract_invalid`;
- `developer_non_advancing`;
- `validation_failed`;
- `validation_prerequisite_missing`;
- `validation_infrastructure_error`;
- `recovery_exhausted`.

Status, history, run summaries, and diagnostics should distinguish safe refusal to
advance from provider failure, DevLab failure, and operator-action prerequisites.

## Live Evaluation Policy

Live evaluations run continuously during and after these milestones, but do not
block M3-M6 merely because they did not happen to reproduce a rare fault. They are
used to measure and tune:

- same-session correction success rate;
- bounded recovery frequency and success;
- validation outcome distribution;
- first-pass reviewer approval rate;
- procedural versus product rework;
- defects consolidated per rejection;
- correlation between semantic task warnings and later rework;
- the cost/benefit of stronger developer model or effort settings.

Accumulated live evidence is required before:

- promoting a semantic task warning to a hard error;
- changing default recovery limits;
- changing default role models or effort;
- conditionally skipping lifecycle roles.

## Implementation Order

1. Implement semantic developer completion validation and same-session repair.
2. Add the restricted one-attempt recovery path.
3. Add diagnostic-only progress classification and metrics.
4. Add deterministic regression and ambiguous-case coverage.
5. Enable bounded non-progress recovery and recurrence stopping.
6. Centralize validation resolution and add graded durable outcomes.
7. Add structural task gates and semantic warnings.
8. Improve scenario guidance and reviewer completeness.
9. Run full validation after each behavior slice and live evaluations throughout.
10. Reassess models, effort, recovery limits, and lifecycle frequency from collected
    evidence.

## Likely Code Ownership

- `orchestrator.py`: semantic submission policy, progress/recovery orchestration,
  validation transition policy, stop reasons.
- `workspace.py`: mutation handles and cached read-only facts needed by orchestration.
- `task_tracker.py`: task acceptance-criteria and task-contract parsing facts.
- `handoffs.py`: generic candidate/result syntax and serialization only.
- `profiles.py` or an existing validation-owning module: effective validation
  resolution without workflow mutation.
- `environment.py`: target-owned validation command execution where it shares the
  profile lifecycle contract.
- `workflow_history.py` and `workflow_diagnostics.py`: progress and rework metrics.
- `status.py`, run summaries, and CLI formatting: operator-visible outcomes.
- packaged role/domain prompts: minimal behavioral guidance that cannot be enforced
  mechanically.

Do not create a new module unless the extracted behavior forms a self-contained
domain with minimal coupling. In particular, keep transition policy visible in the
orchestrator and task parsing behind `task_tracker.py`.

## Definition of Done

- A completed developer handoff with unchecked acceptance criteria is repaired within
  the active session or one bounded correction attempt.
- DevLab never creates a normal successful-session commit for an unaccepted or
  repeatedly non-advancing session.
- The same developer/task route is not invoked indefinitely without progress.
- Legitimate workflow-only sessions remain valid and auditable.
- Mechanical validation facts are recorded by DevLab rather than required as prose.
- Deterministic validation failures receive at most one bounded corrective session.
- Missing host tools are reported, never installed by DevLab.
- Structural task defects block expensive sessions; semantic concerns warn until
  proven reliable enough to enforce.
- Reviewers return a comprehensive currently discoverable defect set.
- Diagnostics distinguish procedural rework, product rework, recovery, and safe
  stops.
- Focused tests cover every transition and crash-recovery invariant.
- Complete development validation passes with `make check`.
