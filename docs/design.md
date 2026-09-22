# DevLab Design Overview

DevLab coordinates bounded agent sessions to turn repository-stored software
requirements into reviewed changes. This overview explains the workflow and its
implementation boundaries. For motivation and possible future directions, see
[Project vision](vision.md); for commands and file formats, see the
[operator guide](operator-guide.md). [CONTEXT.md](../CONTEXT.md) defines the
project's terminology, and [AGENTS.md](../AGENTS.md) maps behavior to its owning
modules.

## DevLab and target workspace

DevLab is installed separately from the repository it operates on. The target
workspace owns its specifications, configuration, source code, tests, and
workflow records. Its stack can differ from DevLab's Python implementation.

DevLab's repository contains the reusable package, tests, documentation, and
repository-only demonstrations. It does not keep root `.devlab/` workflow state
for its own development. Initialization copies starter files from
`src/devlab/resources/init/` into a target; standing role instructions remain
packaged under `src/devlab/resources/prompts/`.

Language templates provide initial tooling policy and profiles. They do not
create a persistent language mode in orchestration. Mixed-language work uses
ordinary task profiles and a target-owned integration command.

## Core design principles

- **Repository state is authoritative.** Durable progress, decisions, and
  recovery pointers live in files that can be inspected and versioned.
- **Sessions are bounded.** Each invocation has one role; developer and reviewer
  sessions each handle one task. Task scope should be independently implementable
  and reviewable without splitting tightly coupled work into unnecessary sessions.
- **Workflow policy is enforced in code.** Prompts explain the role, while
  validated results and explicit task/milestone transitions control progress.
- **Inspection does not mutate state.** Status, doctor, diagnostics, prompt
  assembly, and prompt-size reporting neither repair nor advance the workflow.
- **Target commands remain target-owned.** Providers define agent invocation;
  profiles define tooling, validation, and environment commands. DevLab does not
  install missing host tools or supply an operating-system sandbox.

These tradeoffs favor auditability and restartability over the convenience of a
long conversation or an external workflow database. The original decisions are
recorded in [ADR 0001](adr/0001-store-workflow-state-in-repository-files.md),
[ADR 0003](adr/0003-keep-reporting-commands-non-mutating.md), and
[ADR 0005](adr/0005-enforce-workflow-rules-in-code.md).

## Main workflow

`devlab continue` is the normal mutation entry point. It derives planning,
implementation, clarification/research resume, validation retry, or supported
recovery from durable state. `plan` and `implement` expose phase boundaries for
operators and automation that deliberately need them.

The workflow uses these agent roles:

| Role | Responsibility |
| --- | --- |
| Architect | Create the design and review integrated milestones for drift. |
| Planner | Create tasks/milestones and plan corrective work for findings. |
| Developer | Implement one eligible task. |
| Reviewer | Review one task and request changes or approve it. |
| Integrator | Assess the repository at a completed milestone boundary. |
| Researcher | Resolve a requested fact with cited evidence. |

The orchestrator is program logic, not another worker-agent session. It selects
roles, assembles context, invokes providers, validates results, applies domain
transitions, and commits accepted work.

Within an implementation run, selection gives priority to missing design,
pending task reviews, open findings, architecture review, milestone integration,
and eligible development work, in that order. A task is eligible when its status
is `open` or `changes_requested` and every dependency is `closed`. Dependency
blocking is computed from tasks rather than stored as another status.

An exhausted backlog is complete only when planning is complete and the required
milestone work is finished. Otherwise the planner supplies more work. Blocked
dependencies and external prerequisites stop the run with operator guidance.

`devlab doctor` aggregates all workspace health findings and returns nonzero
when any exist. Each finding identifies which operations it blocks. Continuation
uses the same validators but stops only for findings applicable to its next
operation; this avoids duplicating invariant checks or treating every global
health issue as a blocker for every role.

## Durable state and ownership

The target's `.devlab/` directory separates operator inputs from generated
workflow state:

| Records | Owner and purpose |
| --- | --- |
| `specs/`, `config/` | Operator-owned requirements and executable/tooling configuration. |
| `plans/`, `tasks/`, `milestones/` | Plans and the active implementation graph. |
| `findings/` | Corrective work raised by integration or architecture review. |
| `clarifications/`, `research/` | Decision requests and discoverable-fact requests. |
| `workflow.toml` | Orchestrator-owned planning completeness and typed resume pointer. |
| `workflow-events.jsonl` | Append-only lifecycle evidence for reporting. |
| `session-artifacts/`, `history/`, `logs/` | Current session artifacts and archived results/logs. |
| `verification/` | Orchestrator-owned task and milestone validation evidence. |
| `generations/` | Archived planning generations. |
| `test-services/` | Non-secret ownership records for workspace services. |
| `local/` | Ignored private runtime artifacts, exports, and smoke-test logs. |

Git records accepted session work, including non-ignored logs. Ignored runtime
files and external resources have separate lifetimes; a clean worktree does not
mean that every external effect has been undone. Operators must configure ignore
rules before initialization and treat logs and retained prompts as sensitive.
The [operator guide](operator-guide.md#what-operators-own) lists the concrete
paths and edit boundaries.

## Workspace access and cached snapshots

`Workspace` and its task, milestone, finding, clarification, and research handles
are the mutation boundary. Handles expose domain transitions; multi-step policy
remains in the orchestrator. File-backed trackers own parsing and storage.
Orchestration must not scan task files or rewrite tracker formats directly.

`WorkspaceSnapshot` is a disposable, cached, read-only view of repository state.
It supports cross-domain selection and reporting without repeatedly parsing
files. `Workspace.snapshot` is created lazily and invalidated by workspace
mutations. A new `Workspace` observes external changes; there is no process-wide
state cache. See [ADR 0004](adr/0004-split-workspace-mutations-from-snapshots.md).

Task status lives in TOML front matter in one stable Markdown file. Status
changes are small diffs, not file moves. The current backend is `FileTaskTracker`;
a future backend must preserve the workspace and tracker contracts rather than
expose different storage behavior to orchestration.

## Handoffs and continuity

Before an ordinary role session, DevLab creates a trusted `session.toml` envelope
and a role-aware `handoff-candidate.toml` under
`.devlab/session-artifacts/<role>/`. The role submits its candidate during that
session. Submission checks the schema and workflow meaning, records all
independently detectable errors, and allows bounded correction attempts.

After acceptance DevLab publishes `result.toml` and renders `handoff.md`. The
orchestrator verifies the session, role, task, and milestone identity before
applying transitions, then archives the result and submission evidence. The
structured result controls the workflow; rendered Markdown supplies readable
history and prompt context. Invalid structured output does not become accepted
merely because the accompanying prose looks plausible.

Within a valid reviewer result, the task closes only when the task's approval
checkbox is checked and the structured `open_issues` list is empty. A disagreement
requests changes and emits a diagnostic. This conservative handling of reviewer
signals is distinct from rejecting a malformed handoff. See
[ADR 0007](adr/0007-reviewer-mismatch-defaults-to-changes-requested.md).

A clarification records required operator intent and the interrupted route.
The default mode stops for an answer. Unattended mode invokes a separate bounded
resolver and records its answer with agent provenance before resuming that same
route. Research similarly preserves the exact requesting route, but supplies
cited evidence rather than authority to decide. Only architect, planner, and
developer roles can request research; the requesting role owns the subsequent
design or code decision. The researcher can write only its staged result.

## Task-specific validation

After completed developer work, DevLab runs configured validation before the
reviewer session. A task's non-empty `validation` list replaces profile defaults;
omitting it inherits them, and an explicit empty list disables mechanical task
validation with a diagnostic when defaults exist.

Explicit task-command failures return work for one bounded correction attempt;
repeated failure stops. Profile-default command failures are recorded as soft
task-level warnings because a repository-wide check may depend on later tasks.
Missing tools, timeouts, and execution infrastructure failures remain unverified
or errored checks and stop before review. Agents may run additional checks, but
configured validation is the durable workflow gate.

The [profile and validation reference](operator-guide.md#profiles) explains the
configuration and operator consequences. Target-owned acceptance tests remain
inside the workflow. Independent evaluation graders run afterward and cannot
feed repairs back into the scored run; see
[ADR 0011](adr/0011-keep-workflow-evaluation-grading-outside-the-workflow.md).

## Milestone integration

When a milestone's tasks close, the integrator assesses their interaction with
the existing system. DevLab resolves validation from the closed milestone tasks,
deduplicates command/service bindings in stable order, and executes the checks
before marking integration complete. Command failure creates corrective findings;
unavailable tools or infrastructure block without being mislabeled as product
defects. An absence of configured commands is explicitly unverified.

`.devlab/verification/milestones/<id>.toml` separates command observations from
the integrator's semantic concerns and untested claims. After integration, the
architect compares the result with the design and specifications. This is an
architecture review, not an approval gate: the milestone is marked reviewed even
when remaining drift creates findings. See
[ADR 0006](adr/0006-use-architecture-review-rather-than-approval-gate.md).

The planner maps findings to tasks using `addresses_findings` metadata and a
complete mapping in its submitted result. DevLab validates that relation before
marking a finding planned. It resolves the finding when all addressing tasks
close; corrective tasks can belong to later milestones.

## Planning and specification changes

The planner reports a typed `planning_complete` value. The orchestrator writes
`[planning].complete` in `.devlab/workflow.toml`; agents do not edit that file or
the workflow event log directly. A planner can produce only the next milestone,
but must eventually represent all in-scope work or explicitly finish planning.
Prose about possible future milestones is not hidden control state.

Planning records the committed specification revision. A later specification
change requires reconciliation before implementation. Reconciliation archives
the active plans, tasks, milestones, findings, handoffs, agent logs, and workflow
control state under `.devlab/generations/NNNN/`, then creates a fresh planning
graph. Operator inputs, project knowledge, cross-generation events, and service
ownership remain active. Directory scope identifies the generation; tasks do not
carry a redundant generation field.

Explicit adoption planning records the existing system and preserves its stack
and validation approach. Operators can also request plan revision or replacement.
The narrow plan-neutral-spec bypass requires an explicit operator decision; see
[Specs and planning](operator-guide.md#specs-and-planning).

## Agent providers and prompt context

The orchestrator decides what to do; providers decide how to invoke an agent.
Target `agents.toml` owns command templates, role mappings, models, timeouts, and
prompt transport. Provider-specific invocation stays in `agents.py`.

Providers capture stdout/stderr separately and enforce independent elapsed-time
and output-inactivity limits. Cleanup is bounded and cannot undo detached,
container, or remote effects. Configuration and platform details belong in
[Agent configuration](agent-configuration.md).

Prompt assembly combines packaged conventions and role instructions with the
target's tooling policy, selected work, and relevant recent handoffs. Project
knowledge can include `CONTEXT.md`, a `CONTEXT-MAP.md` with linked contexts, and
`docs/adr/*.md`. Discovery is read-only and respects workspace boundaries.

The same prompt builders provide size estimates for status and doctor. Thresholds
warn about excessive context without printing prompt contents. Agents can search
for additional detail instead of receiving every historical document by default.

## Executable configuration and environments

Commands that start configured processes authorize a canonical executable-
configuration snapshot and freeze it for the invocation. Authorization comes
from workspace-scoped operator-local trust, an independently supplied digest,
or explicit acceptance for one invocation. A target cannot authorize itself.

A task may change executable configuration and complete its review under the
original snapshot. DevLab then stops before preparing work outside that task
cycle; a fresh invocation must authorize the current configuration. Trust covers
entry points, not script contents, transitive commands, or sandboxing. See
[ADR 0010](adr/0010-authorize-frozen-executable-configuration.md).

Profiles select validation and an optional environment lifecycle around managed
roles: pre-session cleanup, setup, agent work, and post-session teardown.
Teardown is attempted after failure as well. Planner and architect sessions do
not use task environments by default. Profile changes that affect planned work
should be explicit implementation tasks with review.

Operation-scoped prerequisites observe required conditions. Declared preparation
may create ignored workspace-local runtime files or initialize an owned test
service, then recheck readiness. It cannot install host tools, obtain credentials,
or generate tracked product artifacts. Reporting and explicit prerequisite
checks never prepare resources.

Managed test services belong to the workspace and survive session and generation
boundaries. DevLab owns identity, locking, private exports, and explicit cleanup;
target commands own ensure/check/destroy behavior. See the
[runtime reference](runtime-prerequisites.md),
[ADR 0013](adr/0013-use-workspace-owned-test-services.md), and
[ADR 0014](adr/0014-prepare-only-declared-runtime-prerequisites.md).

Deployment uses these same mechanics and an optional specification overlay.
The [deployment contract](deployment-feature-overview.md) defines the boundary
between producing and verifying deployment artifacts and executing a production
release.

## Interruption and recovery

Continuation reconstructs the next action from durable state. If uncommitted
changes prevent progress, it may offer an operator-confirmed discard to the
observed committed boundary. The proposal is tied to HEAD, affected paths, Git
status classifications, and session identity. Conflicts, in-progress Git
operations, and nested repository dirt require explicit remediation.

Discard restores only the described Git scope. Ignored runtime files and
external effects remain the operator's responsibility. If discard is declined
or refused, DevLab provides inspection and preservation guidance. It does not
infer how to finish arbitrary partially applied changes. See
[ADR 0012](adr/0012-use-one-workflow-continuation-entry-point.md) and the
[interruption guide](how-to/resume-interrupted-workflow.md).

## Scope and evolution

DevLab currently runs sequential software-workflow sessions. It is not a general
CI/CD service, a concurrent agent runtime, or an external issue-tracker system.

Bounded invocation, durable state, provenance, and validated handoffs may support
a future domain-neutral kernel. Task transitions, eligible requesting roles,
planning effects, and deployment policy are software-specific contracts. A
concrete second workflow must demonstrate shared semantics before an interface
is extracted; see the [vision](vision.md) and [roadmap](roadmap.md).
