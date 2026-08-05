# Workflow Contract Hardening: Remaining Work

## Purpose

Finish the unresolved and partially implemented parts of
`workflow-contract-hardening.md` without reopening or weakening the policy delivered
by `unattended-workflow-progress-and-rework.md`.

This is a continuation plan, not a replacement workflow design. Its scope ends when
the current workflow-contract commitments are implemented, explicitly deferred, or
rejected. Redesigning the `docs/plans/*.md` planning system is later work.

## Governing Policy

`unattended-workflow-progress-and-rework.md` has precedence wherever the two plans
overlap. The following rules are therefore fixed constraints rather than decisions
to revisit:

- task validation runs at completed developer submission, before review;
- explicit task commands may receive one bounded developer correction;
- profile-default failure remains soft at task level because a milestone may be
  intentionally incremental;
- `not_configured` warns and proceeds at task level;
- a missing host tool is an unverified operator/CI prerequisite and DevLab never
  installs it;
- deterministic facts, not agent claims, control transitions;
- recovery is durable and bounded, and recurrence stops rather than looping;
- structural task defects block while semantic task-quality concerns remain warnings
  until evaluation evidence justifies stronger enforcement;
- architecture review records findings but remains a synchronization step, not an
  approval gate.

Older text in `workflow-contract-hardening.md` that suggests task validation after
reviewer approval or a universal configurable task rejection policy is superseded.
The remaining plan may extend the existing validation abstractions to milestone
scope, but must not move the task boundary or make profile defaults strict per task.

## Reconciled Scope

| Original implementation item | Current disposition | Work retained here |
| --- | --- | --- |
| 1. Effective task validation | Implemented | Reuse it to resolve validation across milestone tasks; do not create a parallel resolver. |
| 2. Durable validation outcomes | Partial | Generalize the task-specific runner/record contract and add the governing plan's missing revision, duration, bounded summary, and recovery facts. |
| 3. Task validation execution | Implemented with newer policy | Preserve developer-boundary execution and graded outcomes; close missing stop/retry semantics only. |
| 4. Validation reporting | Partial | Preserve existing diagnostics and add consistent task/milestone status, prerequisite, and safe-stop reporting. |
| 5. Task quality gate | Implemented with intentional warnings | Keep structural gates; calibrate warnings through evaluations, without promotion to hard errors in this plan. |
| 6. Strict milestone validation | Not implemented | Implement as the main integration gate. |
| 7. Milestone verification record | Not implemented | Add the orchestrator-owned TOML audit artifact. |
| 8. Narrow integrator/architect judgment | Not implemented | Add role-specific structured candidate fields and rendered handoff sections. |
| 9. Role prompt contract | Partial | Retain existing developer/reviewer guidance and add only missing milestone-verification guidance. |
| 10. Strict task-validation mode | Rejected for this scope | Do not implement without later live evidence and a new explicit decision. |

The original handoff parsing phases are complete and are not reopened except for the
additive, role-specific judgment fields required by milestone verification.

## Required Behavior

### Task-validation gaps to close

Complete the existing unattended-workflow milestone rather than applying the older
task policy:

- Persist repository revision, duration, bounded output summary, and retry/recovery
  relationship with validation results.
- Distinguish product failure from `missing_tool`, `timeout`, and
  `infrastructure_error` in transition and run-summary behavior.
- Report `validation_prerequisite_missing` for a missing tool and
  `validation_infrastructure_error` for execution infrastructure failure. Neither
  condition is reviewer rejection or permission to install a tool.
- Retry a timeout only if an explicit target-owned configuration contract is added
  for that retry. Without such configuration, stop safely; do not infer permission
  to rerun from the general bounded product-recovery allowance.
- Preserve the existing one-correction limit for deterministic explicit-task
  failure and the soft profile-default policy.

If completing these fields requires changing the existing JSON task record schema,
read old records defensively so restart and diagnostics remain compatible. Do not
rewrite historical records merely to migrate them.

### Milestone validation resolution

For the milestone selected for integration:

1. Read its closed tasks through `WorkspaceSnapshot`.
2. Resolve each task with the existing `effective_validation()` helper and that
   task's resolved profile.
3. Preserve milestone/task order and command order, deduplicating identical command
   strings by first occurrence.
4. Preserve provenance for every retained command: the contributing task IDs and
   whether each contribution came from task metadata or a profile default.
5. Treat explicit `validation = []` as no commands for that task; it must not fall
   back to profile defaults.
6. Classify an empty resolved command set as `not_configured`.

Resolution is read-only and shared by prompt assembly, execution, status, and
diagnostics. It must not parse task files outside `task_tracker.py` or bypass profile
resolution.

### Milestone outcome policy

Run resolved commands once at the integration boundary using the existing
target-owned validation executor and profile/environment timeout contracts. Stop at
the first non-passing command, while retaining the result for every command that was
actually attempted.

Apply these transitions:

- `passed` plus no integrator Open Issues: mark the milestone integrated.
- `failed`: do not integrate; create or reuse an actionable integration finding,
  mark integration failed, and let planner/developer corrective work use the
  existing finding workflow.
- `not_configured`: record an unverified warning and allow integration when the
  integrator reports no Open Issues. The unattended plan makes only *configured*
  milestone validation strict; this plan does not invent a new strictness setting.
- `missing_tool`: do not integrate, do not install anything, record an operator/CI
  prerequisite, and stop with `validation_prerequisite_missing`. Do not turn an
  absent host executable into a product task merely to keep an unattended run
  moving.
- `timeout` or `infrastructure_error`: do not integrate and stop with
  `validation_infrastructure_error`; do not classify the repository as behaviorally
  failing or create speculative product rework.
- integrator Open Issues: retain the existing integration-finding transition. If
  mechanical validation also failed, create one consolidated actionable finding or
  explicitly relate the records so the planner is not given duplicate work.

A retry after a corrective task reruns validation from the new repository state. An
unresolved finding prevents repeated integrator invocation through existing role
selection. Repeated identical failure must never create an unbounded integrator
loop or duplicate unresolved findings.

### Milestone verification record

Store one compact current record at:

```text
.devlab/verification/milestones/<milestone-id>.toml
```

The record is orchestrator-owned and atomically replaced as the milestone advances.
Historical handoffs, validation logs, session metadata, and Git revisions preserve
attempt history; the milestone record summarizes the current boundary state rather
than duplicating full logs.

The record contract should contain:

- schema version, milestone ID, verification state, repository revision, and update
  time;
- closed task IDs inferred by DevLab;
- resolved commands with stable provenance;
- attempted command outcomes, exit codes, durations, bounded summaries, and log
  paths;
- integration session and archived handoff references;
- finding IDs and their observed status at the boundary;
- integrator semantic concerns and untested claims;
- architecture-review session/handoff reference and reported design drift;
- whether the boundary is verified, unverified because no commands exist, blocked
  by product failure, or blocked by an execution prerequisite.

Do not ask agents to repeat milestone IDs, task IDs, commands, exit codes, revisions,
or finding state. Keep full command output in existing logs, outside this compact
record.

The record exists after every integration attempt, including failure and
`not_configured`. Architecture review enriches the same record after integration;
it does not retroactively change the integration gate. Reads used by status,
doctor, prompts, and diagnostics are non-mutating.

### Judgment-only handoff contract

Extend the structured result candidate additively and by role:

- integrator: `Semantic Integration Concerns` and `Untested Claims`;
- architect during milestone review: `Design Drift`.

Each field uses the existing strict list/`None` semantics. These are judgment, not
transition facts:

- an actionable integration gap must still appear in `Open Issues`, which controls
  the integration-finding transition;
- an untested claim is recorded without automatically inventing a finding, unless
  the integrator also identifies it as required missing coverage in `Open Issues`;
- actionable architecture drift must still appear in `Open Issues`, preserving the
  existing finding behavior while architecture review completes.

Templates and validation should require these fields only for the relevant role and
context. Existing archived handoffs without them remain readable. Keep generic
candidate parsing in `handoffs.py`; keep the meaning of these fields and transition
policy in `orchestrator.py`.

### Reporting and diagnostics

Expose, without mutation:

- latest milestone verification state and revision in verbose status;
- failed, missing-tool, infrastructure, timeout, and not-configured outcomes;
- milestones integrated without mechanical validation;
- untested claims and design drift counts;
- findings associated with milestone verification;
- safe-stop category distinct from provider failure, DevLab failure, and product
  validation failure.

`doctor` should validate malformed verification records and dangling references but
must not create, repair, or refresh them.

## Implementation Slices

### Slice 1: Lock policy and characterize current behavior

- Add the precedence/status notes to the plans and align `docs/design.md` with the
  governing developer-boundary policy.
- Add characterization tests for explicit task failure, soft profile failure,
  `not_configured`, missing tool, timeout, infrastructure error, and restart after a
  used correction.
- Correct only mismatches with the unattended plan; do not introduce milestone
  behavior in this slice.

Acceptance: the task transition matrix above is executable documentation, and all
existing bounded-recovery tests remain unchanged and passing.

### Slice 2: Generalize validation facts and resolution

- Extend `environment.py`'s validation result types/executor so task and milestone
  callers share command execution without hard-coded task record paths.
- Keep effective task resolution in `profiles.py`; add milestone aggregation over
  snapshot tasks without a second command-precedence implementation.
- Add duration, revision, bounded summary, context identity, and recovery linkage.
- Keep storage mutations behind `Workspace` handles. Prefer milestone verification
  types and persistence in `milestones.py`, where lifecycle and boundary audit state
  are tightly coupled, rather than adding a parallel tracker unless implementation
  proves that domain independently reusable.

Acceptance: unit tests cover mixed task/profile sources, explicit empty validation,
stable deduplication, provenance, no commands, and backward-compatible task-record
reads.

### Slice 3: Define and persist the verification record

- Implement strict TOML serialization/parsing and atomic replacement.
- Write a record for pass, failure, no configuration, and execution-prerequisite
  outcomes.
- Add read-only snapshot access and explicit workspace mutation handles.
- Validate restart behavior when a record exists before the milestone transition is
  complete.

Acceptance: focused tracker/workspace tests prove deterministic serialization,
malformed-record errors, no reporting mutations, and safe reconstruction after
restart.

### Slice 4: Add narrow role judgment

- Extend role-aware candidate templates, serialization, parsing, and validation.
- Update only integrator and architecture-review prompts with the new judgment
  contract and explain the continued role of `Open Issues`.
- Persist judgment into the verification record without trusting agents for facts
  DevLab owns.

Acceptance: handoff tests cover required order, strict `None`, context-sensitive
requirements, old archived handoffs, and prevention of duplicated fact fields.

### Slice 5: Enforce the milestone gate

- In `orchestrator.py`, run validation after accepting the integrator result but
  before `mark_integrated()` and tag creation.
- Apply the outcome matrix, create/consolidate findings for product failures, and
  emit the appropriate durable workflow events and stop reasons.
- Preserve the existing architecture-review ordering and finding semantics.
- Ensure commits/tags cannot describe a milestone as integrated when the gate did
  not pass or explicitly allow `not_configured`.

Acceptance: integration tests cover pass, one failing command, deduplication,
integrator-only issue, combined mechanical/semantic failure, no validation, missing
tool, timeout/infrastructure error, and successful retry after a corrective task.
No case can repeatedly select the integrator without durable progress.

### Slice 6: Complete architecture enrichment and reporting

- Update the record after architecture review with design drift and resulting
  findings while still marking the review complete.
- Add verbose status, diagnostics, doctor, history/run-summary coverage, and stable
  output tests.
- Ensure deleted logs, stale revisions, and dangling handoff/finding references are
  reported rather than repaired by read-only paths.

Acceptance: restart between integration and architecture review preserves the
record, architecture findings do not revoke integration, and all reports agree on
the same stored facts.

### Slice 7: Deterministic evaluation and documentation closure

- Add scripted evaluation cases for shared commands across closed tasks, mixed
  profiles, failure and planned corrective retry, no configured validation, and a
  missing host tool.
- Confirm semantic task warnings remain non-blocking and record calibration work as
  ongoing rather than silently promoting them.
- Update `docs/todo.md`, `docs/design.md`, and both source plans with exact final
  dispositions: implemented, deliberately deferred, rejected, or superseded.
- Run `make check` after each behavior slice and at completion.

Acceptance: all deterministic scenarios pass, complete validation passes, and no
open item in the source plan lacks an explicit disposition.

## Expected Code Ownership

- `orchestrator.py`: transition matrix, bounded recovery, finding coordination,
  workflow events, and stop reasons.
- `environment.py`: shared execution of trusted target-owned commands and observed
  command results, not workflow policy.
- `profiles.py`: effective task validation precedence.
- `milestones.py`: milestone verification record and milestone-domain persistence.
- `workspace.py`: cached read-only access and explicit mutation handles.
- `handoffs.py`: additive generic candidate/result syntax and serialization.
- `status.py`, `doctor.py`, `workflow_diagnostics.py`, run/history reporting:
  read-only presentation and validation.
- `prompts.py` and packaged role prompts: minimal judgment guidance that cannot be
  inferred or enforced mechanically.

Do not put provider invocation in orchestration, parse task files outside
`task_tracker.py`, mutate from reporting paths, install target prerequisites, or add
a new verifier role.

## Definition of Done

- Every original workflow-contract item is marked implemented, superseded,
  deliberately deferred, or rejected.
- All unattended-workflow invariants and existing recovery tests remain intact.
- Task validation still occurs before review with explicit/profile graded behavior.
- Configured milestone failure cannot mark or tag a milestone integrated.
- Missing tools and infrastructure failures stop safely without product blame or
  host-tool installation.
- Milestone verification cleanly separates observed facts from role judgment.
- Corrective findings can be planned, implemented, resolved, and successfully
  revalidated without an integrator loop.
- Architecture review enriches audit state without becoming an approval gate.
- Status, doctor, diagnostics, history, and run summaries are read-only and agree on
  durable state.
- Focused transition/restart/evaluation tests and complete `make check` pass.
