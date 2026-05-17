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

**Role session**:
One bounded agent invocation for exactly one workflow role.
_Avoid_: conversation, chat

**Agent provider**:
The abstraction responsible for invoking a concrete agent implementation.
_Avoid_: agent CLI when referring to the abstraction

**Task**:
A repository-backed unit of implementation work scoped for one developer session and one reviewer session.
_Avoid_: issue, ticket, job

**Milestone**:
A named group of tasks that should produce a coherent repository state for integration and architecture review.
_Avoid_: release, sprint

**Finding**:
A repository-backed record of an integration or architecture-review issue that needs planner follow-up.
_Avoid_: bug report, defect, ticket

**Profile**:
A reusable task-type configuration that defines tooling summary, default validation, and optional environment lifecycle commands.
_Avoid_: environment when referring to the full reusable task configuration

**Handoff**:
The per-session artifact that records what a role did, changed, could not finish, and recommends next steps.
_Avoid_: summary when the artifact contract matters

**Workspace**:
The mutation boundary object for a target workspace and its first-class domain handles.
_Avoid_: repository when referring to the DevLab API object

**WorkspaceSnapshot**:
A cached read-only view of task, milestone, and finding state for a target workspace.
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
- A **Task** may belong to one **Milestone** and use one **Profile**.
- A **Finding** may belong to one **Milestone** and is converted into follow-up **Tasks** by the planner.
- A **Workspace** creates **WorkspaceSnapshots** for read-only decisions and exposes handles for workflow mutations.
- A **Tracker** owns one storage format; the orchestrator coordinates trackers through workspace boundaries.
- An **Agent provider** invokes concrete agents without leaking provider details into orchestration logic.

## Example dialogue

> **Dev:** "Should the orchestrator parse task files directly to find the next job?"
> **Maintainer:** "No. A **Task** is stored through the task tracker, and cross-tracker read decisions should use a **WorkspaceSnapshot**. Also call it a task, not a job."

## Flagged ambiguities

- "workspace" can mean the target repository on disk or the `Workspace` API object. Use **Target workspace** for the repository directory and **Workspace** for the mutation boundary object when precision matters.
- "environment" can mean process environment variables, profile lifecycle commands, or the broader task execution setup. Use **Profile** when referring to DevLab's reusable task-type configuration.
