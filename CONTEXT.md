# DevLab Context

DevLab is a reusable CLI/package that orchestrates bounded, role-based agent sessions to turn repository-stored specifications, plans, and tasks into reviewed software changes.

## Language

**DevLab**:
A reusable development workflow tool that runs role-based agent sessions against a target workspace.
_Avoid_: app generator, agent script

**Target workspace**:
The repository directory DevLab operates on for a workflow run.
_Avoid_: project root when the distinction from DevLab's own source repository matters

**Workflow state**:
Durable repository files that record DevLab's current progress, decisions, tasks, findings, milestones, handoffs, and configuration.
_Avoid_: memory, runtime state

**Workflow continuation**:
The operator-facing `devlab continue` operation that derives and performs the
next valid lifecycle action from durable workflow state. Planning,
implementation, clarification resume, validation retry, and supported recovery
are internal action kinds rather than choices the operator must diagnose.
_Avoid_: using resume for every continuation or requiring operators to select a role command

**Discard proposal**:
A structurally fingerprinted description of the uncommitted Git scope that
`devlab continue` can restore to the current committed workflow boundary after
operator confirmation. It revalidates the observed HEAD, affected paths, Git
status classifications, clean preview, and session identity immediately before
discard. It intentionally does not hash file contents, preserves ignored files,
and makes no claim about external effects.
_Avoid_: transaction reconstruction, generic repository fix

**Operator guidance**:
Structured, condition-specific inspection, preservation, remediation, warning,
and retry advice emitted whenever DevLab cannot continue or the operator declines
a proposed discard.
_Avoid_: generic “run doctor” advice

**Workspace health finding**:
A read-only diagnostic produced by one domain-owned validator. Every finding
makes the global `devlab doctor` result unhealthy and identifies the workflow
operations it blocks. `devlab continue` consumes the same findings and stops
only when one applies to its next action.
_Avoid_: warning/error severity, duplicated doctor and orchestration checks

**Prerequisite resolution guide**:
A focused repository-owned file or Markdown section that tells an operator how
to establish, configure, and verify one external workflow prerequisite, including
common failures and relevant security or cleanup boundaries.
_Avoid_: prerequisite inventory, whole project documentation, executable setup

**Resolvable prerequisite**:
A command-check prerequisite whose authorized, repeatable preparation can create
declared ignored workspace-local runtime artifacts or initialize an applicable
managed test service. DevLab checks, prepares once when unsatisfied, then checks
again. Missing host executables, credentials, attestations, and tracked product
artifacts are not resolvable prerequisites.
_Avoid_: repair hook, dependency installer, arbitrary setup command

**Role session**:
One bounded agent invocation for exactly one workflow role.
_Avoid_: conversation, chat

**Agent provider**:
The abstraction responsible for invoking a concrete agent implementation.
_Avoid_: agent CLI when referring to the abstraction

**Executable configuration snapshot**:
A canonical, fingerprinted, per-command frozen view of provider invocation and
profile validation, lifecycle, prerequisite/preparation, and managed-test-service
configuration that DevLab may execute.
_Avoid_: sandbox, safe configuration

**Executable configuration trust**:
Operator authorization for one target workspace, agent-config source, and
executable-configuration digest, stored outside the target workspace.
_Avoid_: repository trust, provider safety

**Task**:
A repository-backed unit of implementation work scoped for one developer session and one reviewer session.
_Avoid_: issue, ticket, job

**Milestone**:
A named group of tasks that should produce a coherent repository state for integration and architecture review.
_Avoid_: release, sprint

**Finding**:
A repository-backed record of an integration or architecture-review issue that needs planner follow-up.
_Avoid_: bug report, defect, ticket

**Clarification**:
A repository-backed operator decision request created when a role session cannot safely continue without explicit operator intent.
_Avoid_: chat question, conversation, finding

**Research**:
A repository-backed request for one discoverable fact, resolved by a bounded
researcher session and returned as cited supporting evidence to the exact
requesting route. Research does not supply operator intent or workflow authority.
_Avoid_: clarification, design decision, unverified agent opinion

**Architecture-reviewed milestone**:
An integrated milestone for which the architect performed project-state sync against design/spec/project direction. It is not an approval claim; remaining drift is represented as findings.
_Avoid_: architecture-approved milestone

**Addressing task**:
A task whose `addresses_findings` metadata names a finding as corrective work. A finding is planned when the planner asserts the complete addressing task set; it is resolved when all addressing tasks are closed. An addressing task may be in a later milestone than the finding.
_Avoid_: storing duplicate task lists on the finding

**Profile**:
A reusable task-type configuration that defines tooling summary, default validation, optional environment lifecycle commands, and operation-scoped prerequisites.
_Avoid_: environment when referring to the full reusable task configuration

**Managed test service**:
A target-declared local test resource with workspace lifetime, supplied by
profile references for session, setup, or validation operations. DevLab owns its
durable instance identity, authorization, lock, and private export transport;
target commands ensure, check, and destroy only matching owned resources.
Cleanup is explicit. Session teardown and planning-generation replacement do
not end this lifetime. See ADR 0013.
_Avoid_: host-tool installer, implicit prerequisite repair, session environment

**Prerequisite**:
A profile-owned condition that DevLab checks or an operator attests before a
profile-backed session, environment setup, or validation operation. Automatic
checks are re-evaluated; attestations are operator-local and bound to the
prerequisite's semantic fingerprint.
_Avoid_: finding or task when the condition is external to product work

**Prerequisite blocker**:
The durable target-workspace record of the latest unsatisfied, unverified, or
errored prerequisite that stopped workflow execution before an applicable
operation.
_Avoid_: validation failure when validation did not run

**Handoff**:
The per-session artifact that records what a role did, changed, could not finish, and recommends next steps.
_Avoid_: summary when the artifact contract matters

**Workspace**:
The mutation boundary object for a target workspace and its first-class domain handles.
_Avoid_: repository when referring to the DevLab API object

**WorkspaceSnapshot**:
A cached read-only view of the target workspace's domain and workflow state,
including tasks, milestones, findings, clarifications, research, verification,
and managed-test-service records.
_Avoid_: workspace when the read-only/cache semantics matter

**Tracker**:
A storage-specific component that owns parsing and mutation for one kind of file-backed workflow state.
_Avoid_: manager unless naming an existing API

**Prompt resource**:
A packaged prompt file used by DevLab-spawned worker agents.
_Avoid_: project documentation

## Relationships

- A **Target workspace** contains **Workflow state**.
- A **Role session** produces a **Handoff**.
- A **Handoff** may request one **Clarification**, which records the interrupted
  route for answer and resume. Pending clarifications with a blocking `blocks`
  value conservatively stop the relevant workflow command; `blocks = "none"`
  remains visible without blocking later progress.
- A **Handoff** from architect, planner, or developer may request one
  **Research** investigation of a discoverable fact. Requested research awaits
  its bounded researcher; completed research stores evidence, sources,
  recommendation, confidence, unresolved questions, and provenance while the
  exact route awaits consumption. It is evidence, not workflow authority.
- **Research versus clarification**: research discovers facts; clarification
  obtains operator intent, secrets, preferences, risk acceptance, or authority.
- A **Task** may belong to one **Milestone** and use one **Profile**.
- A **Prerequisite** follows the profile operation that consumes it rather than
  a manually maintained list of roles.
- A **Finding** may belong to one **Milestone** and is converted into **Addressing tasks** by the planner.
- A **Workspace** creates **WorkspaceSnapshots** for read-only decisions and exposes handles for workflow mutations.
- A **Tracker** owns one storage format; the orchestrator coordinates trackers through workspace boundaries.
- An **Agent provider** invokes concrete agents without leaking provider details into orchestration logic.
- An **Executable configuration snapshot** must be authorized before DevLab
  starts its configured processes. Authorization does not imply containment or
  interpret provider-native permission policy.

## Example dialogue

> **Dev:** "Should the orchestrator parse task files directly to find the next job?"
> **Maintainer:** "No. A **Task** is stored through the task tracker, and cross-tracker read decisions should use a **WorkspaceSnapshot**. Also call it a task, not a job."

## Flagged ambiguities

- "workspace" can mean the target repository on disk or the `Workspace` API object. Use **Target workspace** for the repository directory and **Workspace** for the mutation boundary object when precision matters.
- "environment" can mean process environment variables, profile lifecycle commands, or the broader task execution setup. Use **Profile** when referring to DevLab's reusable task-type configuration.
