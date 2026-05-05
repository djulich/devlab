# Harness Design Overview

This document explains the design of the harness for human readers. It is intentionally broader than the role-specific agent instructions in `specs/development/`: those files tell agents what to do in a session, while this document explains why the system is shaped this way.

## Purpose

The harness is a small orchestration system for agentic software development. Its long-term goal is to take a system specification as input and drive a software development lifecycle toward a usable product or release.

The harness does not try to make one large agent session do all work. Instead, it turns development into a sequence of small, bounded sessions. Each session has a role, a narrow objective, explicit inputs, and explicit outputs.

At a high level, the harness should be able to:

1. create a design plan from the system specification,
2. create a project plan and milestones from the design plan,
3. create implementation tasks,
4. invoke agents to implement tasks,
5. invoke agents to review completed work,
6. preserve enough state in repository files to resume or audit the workflow.

## Core design principles

### Repository state is authoritative

The repository is the system of record. Agents should not depend on conversational memory or hidden process state.

Important workflow state is stored in files, for example:

- `specs/` — role definitions, conventions, tooling choices, and system specifications.
- `work/plans/` — design and project plans.
- `work/tasks/` — task files, including each task's status.
- `work/history/` — archived session handoffs.
- `.session-artifacts/<role>/` — temporary output from the current session.

This makes the workflow restartable. If an agent session fails or the process stops, the next run can reconstruct the state from the repository.

### Sessions are small and bounded

Development is performed as a sequence of independent sessions. In each session, one role performs one bounded piece of work.

This is deliberate. Long-running agent conversations tend to accumulate implicit assumptions, context drift, and unrelated changes. Short sessions force the workflow to repeatedly re-ground itself in repository artifacts.

The most important example is the developer role: a developer session implements exactly one task.

### Context should be minimal

Agent input files should be concise. The harness should not pre-fill the context window with every design decision, every historical handoff, or every possible instruction.

Instead:

- global conventions stay in `specs/development/conventions.md`,
- tooling decisions stay in `specs/development/tooling.md`,
- role-specific procedures stay in the matching `role-*.md` file,
- current work is supplied through the selected task and recent relevant handoff.

This keeps agents focused and reduces duplicated instructions across Markdown files.

### State transitions should be explicit

The workflow is designed around explicit state transitions rather than implicit progress.

For example, task files have statuses such as:

- `open`
- `in_review`
- `changes_requested`
- `closed`

The orchestrator changes these statuses after validating the relevant session output. Task files are not moved between folders to represent state.

### Human review remains possible

Even though the harness aims at autonomous development, it is designed to remain inspectable by humans. A human should be able to read the repo and understand:

- what the system is supposed to become,
- what tasks exist,
- which tasks are open, in review, or closed,
- what each agent session did,
- why a task was rejected or approved.

This is why the design favors Markdown files and simple metadata over opaque databases.

## Main workflow

The orchestrator repeatedly assesses the repository and selects the next role.

Typical flow:

1. If no design plan exists, invoke the architect.
2. If tasks are waiting for review, invoke the reviewer.
3. If an eligible development task exists, invoke the developer.
4. If no active tasks exist but planning is incomplete, invoke the planner.
5. If all tasks are closed, stop.
6. If remaining tasks are blocked by dependencies, stop and report the blockage.

The active roles are:

| Role | Responsibility |
|---|---|
| Architect | Convert system-level intent into a design plan. |
| Planner | Convert design/project plans into concrete tasks. |
| Developer | Implement one eligible task. |
| Reviewer | Validate one task that is in review. |
| Orchestrator | Select roles, invoke sessions, validate handoffs, and update task status. |

## Task tracking design

Tasks are file-backed issues. They live in:

```text
work/tasks/
```

Each task is a Markdown file with TOML front matter:

```md
+++
id = "T0001"
title = "Example task"
status = "open"
milestone = "M1"
depends_on = []
+++

# T0001: Example task

## Goal
...

## Acceptance Criteria
- [ ] ...
```

This gives the project a lightweight issue-tracking model without requiring Jira or another external system.

### Why not use folders for status?

Earlier designs represented state by moving task files between folders such as `work/backlog/` and `work/review/`. That is simple, but it does not scale well as the workflow becomes more issue-tracker-like.

A status field has advantages:

- all tasks are visible in one place,
- state changes are small diffs,
- more statuses can be added later,
- filtering can be implemented in code,
- the file remains the stable identity of the task.

### FileTaskTracker

The code encapsulates file-based task handling in `FileTaskTracker`.

This name is intentional: it makes the backend explicit. The orchestrator should depend on task-tracker behavior, not on the details of how tasks are stored. Today the backend is files; later another implementation could use Jira, GitHub Issues, Linear, or another system.

`FileTaskTracker` is responsible for operations such as:

- listing tasks,
- selecting the next development task,
- selecting the next review task,
- checking dependency blocking,
- changing task status.

The orchestrator should not manually scan task folders or edit task metadata outside this abstraction.

## Dependency handling

Task dependencies are stored in the `depends_on` metadata array.

A task is eligible for development when:

- its status is `open` or `changes_requested`, and
- all tasks listed in `depends_on` are `closed`.

Dependency blocking is computed rather than stored as a separate persistent status. This avoids stale state: if a dependency closes, dependent tasks automatically become eligible.

## Handoffs and continuity

Each session must write a handoff to:

```text
.session-artifacts/<role>/handoff.md
```

The orchestrator validates that the handoff exists, is non-empty, follows the expected structure, and does not report an unrecoverable issue. It then archives the handoff to:

```text
work/history/
```

Handoffs are intentionally structured. They allow the next session to recover context without relying on chat history.

## Why Markdown and simple files?

The harness is intentionally file-based because files are:

- visible to humans,
- easy for agents to read and edit,
- versioned by Git,
- easy to diff and review,
- portable across tools,
- robust after crashes or interrupted runs.

This design trades some database convenience for transparency and restartability, which are more important for the current project.

## Tooling philosophy

The project prefers fewer tools and simple defaults.

Current Python tooling choices are documented in `specs/development/tooling.md`. In short:

- `uv` manages dependencies, lockfiles, environments, and command execution,
- `uv_build` builds the package,
- `ruff` handles linting and formatting,
- `ty` handles static type checking,
- `pytest` handles tests.

Operational details such as exact validation commands belong in the role files that need them, not in the global tooling decision file. This keeps agent input concise and avoids duplicated instructions.

## Design tradeoffs

### Strict workflow vs. flexibility

The harness is intentionally strict: one role, one task, one handoff, explicit status transitions. This can feel slower than asking an agent to do many things at once, but it improves control, auditability, and recovery.

### File-backed issues vs. external issue tracker

A real issue tracker could provide search, dashboards, permissions, comments, and integrations. The file-backed tracker provides the features needed now with much less operational overhead.

The `FileTaskTracker` abstraction keeps the door open for a future external backend without forcing that complexity into the current design.

### Minimal context vs. full context

Agents may sometimes need to search the repository to find missing detail. That is acceptable. The alternative—loading too much context by default—risks distracting the agent and consuming the context window with irrelevant information.

## Current non-goals

The harness is not currently trying to be:

- a full replacement for Jira,
- a general CI/CD system,
- a multi-agent runtime with concurrent sessions,
- a database-backed project management platform,
- a fully self-modifying autonomous product factory without human inspectability.

Those capabilities may become relevant later, but the current design focuses on a small, reliable, inspectable development loop.

## Summary

The harness is designed to make long-running agentic development practical by reducing reliance on fragile conversational context.

It does this by combining:

- small role-based sessions,
- repository-backed state,
- explicit task statuses,
- structured handoffs,
- minimal agent context,
- simple Python tooling,
- a backend abstraction for task tracking.

The result should be a workflow that can run incrementally, recover from failures, remain understandable to humans, and evolve toward more capable development automation over time.

## References

- <https://www.anthropic.com/engineering/harness-design-long-running-apps>
- <https://openai.com/index/harness-engineering>
- <https://ghuntley.com/ralph>
