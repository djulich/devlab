# DevLab Design Overview

This document explains the design of DevLab for human readers. It is intentionally broader than the role-specific packaged prompt resources in `src/devlab/resources/prompts/`: those files tell agents what to do in a session, while this document explains why the system is shaped this way.

## Purpose

DevLab is a small orchestration system for agentic software development. Its long-term goal is to take a system specification as input and drive a software development lifecycle toward a usable product or release.

DevLab does not try to make one large agent session do all work. Instead, it turns development into a sequence of small, bounded sessions. Each session has a role, a narrow objective, explicit inputs, and explicit outputs.

At a high level, DevLab should be able to:

1. create a design plan from the system specification,
2. create a project plan and milestones from the design plan,
3. create implementation tasks,
4. invoke agents to implement tasks,
5. invoke agents to review completed work,
6. preserve enough state in repository files to resume or audit the workflow.

## DevLab and target workspace

DevLab should be understood as a reusable development tool, not as the product being developed. It operates on a target workspace: a repository that contains the system specification, plans, tasks, history, source code, and tests for the product under development.

During early development, this repository can also be used as a target workspace for dogfooding. That is a convenience, not a design requirement. DevLab should continue to work when invoked against another repository, for example:

```bash
cd /path/to/target-project
devlab init
devlab status
devlab run --auto
```

### Why separate the responsibilities?

Keeping DevLab conceptually separate from the target product has several benefits:

- DevLab can be reused across multiple projects,
- generated or target-product code does not become mixed with DevLab implementation code,
- a target workspace can use any appropriate technology stack,
- DevLab releases can evolve independently from the products they help create,
- `.devlab/specs/system/` can describe the target product instead of DevLab itself.

### Recommended model

A DevLab repository contains the reusable tool and default worker instructions:

```text
devlab-repo/
├── src/devlab/
├── tests/
├── docs/
├── src/devlab/resources/prompts/
└── examples/
```

A target workspace contains product-specific DevLab workflow artifacts under `.devlab/`:

```text
target-project/
├── .devlab/
│   ├── config/
│   ├── specs/
│   │   ├── system/
│   │   └── deployment/
│   ├── plans/
│   ├── tasks/
│   ├── findings/
│   ├── history/
│   ├── logs/
│   └── session-artifacts/
└── <product source, tests, and deployment files>
```

The packaged prompt files under `src/devlab/resources/prompts/` are DevLab-owned role and convention sources. They are installed with DevLab and should not become target-project workflow state.

### Design implications

DevLab code should avoid assuming that the target workspace is DevLab repository. In particular, avoid hard-coded assumptions that:

- the target project is Python-only,
- target source code lives under `src/devlab/`,
- target validation is always `uv run pytest`,
- `.devlab/specs/system/` describes DevLab itself,
- `AGENTS.md` and packaged DevLab prompt resources serve the same audience.

The guiding principle is: DevLab is a reusable tool that operates on a target workspace. Dogfooding in this repository is allowed, but must not leak target-specific assumptions into DevLab design.

## Core design principles

### Repository state is authoritative

The repository is the system of record. Agents should not depend on conversational memory or hidden process state.

Important workflow state is stored in files, for example:

- `.devlab/specs/` — target-workspace system and deployment specifications.
- `.devlab/config/` — target-workspace tooling, environment, profile, and future agent configuration.
- `.devlab/plans/` — design and project plans.
- `.devlab/tasks/` — task files, including each task's status.
- `.devlab/findings/` — file-backed integration and workflow findings.
- `.devlab/history/` — archived session handoffs and workflow markers.
- `.devlab/logs/` — committed workflow logs.
- `.devlab/session-artifacts/<role>/` — output from the current session before it is archived.

This makes the workflow restartable. If an agent session fails or the process stops, the next run can reconstruct the state from the repository.

### Sessions are small and bounded

Development is performed as a sequence of independent sessions. In each session, one role performs one bounded piece of work.

This is deliberate. Long-running agent conversations tend to accumulate implicit assumptions, context drift, and unrelated changes. Short sessions force the workflow to repeatedly re-ground itself in repository artifacts.

The most important example is the developer role: a developer session implements exactly one task.

### Context should be minimal

Agent input files should be concise. DevLab should not pre-fill the context window with every design decision, every historical handoff, or every possible instruction.

Instead:

- worker-agent conventions stay in packaged DevLab prompt resources,
- target-workspace tooling decisions stay in `.devlab/config/tooling.md`,
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

Even though DevLab aims at autonomous development, it is designed to remain inspectable by humans. A human should be able to read the repo and understand:

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
3. If a completed milestone needs integration, invoke the integrator.
4. If an eligible development task exists, invoke the developer.
5. If no active tasks exist but planning is incomplete, invoke the planner.
6. If all tasks are closed and completed milestones are integrated, stop.
7. If remaining tasks are blocked by dependencies, stop and report the blockage.

The active roles are:

| Role | Responsibility |
|---|---|
| Architect | Convert system-level intent into a design plan. |
| Planner | Convert design/project plans into concrete tasks. |
| Developer | Implement one eligible task. |
| Reviewer | Validate one task that is in review. |
| Integrator | Validate the whole repository state at a completed milestone boundary. |
| Orchestrator | Select roles, invoke sessions, validate handoffs, and update task status. |

## Task tracking design

Tasks are file-backed issues. They live in:

```text
.devlab/tasks/
```

Each task is a Markdown file with TOML front matter:

```md
+++
id = "T0001"
title = "Example task"
status = "open"
milestone = "M1"
depends_on = []
validation = []
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

## Task-specific validation

Task files may specify concrete validation commands in the `validation` metadata array. These commands are instructions for the developer/reviewer agents and are run from the target workspace root after the orchestrator-managed environment lifecycle has established the development environment.

If `validation` is omitted, agents use the workspace defaults from `.devlab/config/tooling.md`. If `validation = []`, no validation commands are required; the developer states in the handoff whether any validation was run and why. The orchestrator does not execute arbitrary task validation commands itself.

This supports mixed-toolchain workspaces without making every worker-agent role file list every possible stack.

## Environment lifecycle

For roles that need the development environment, the orchestrator enforces an environment lifecycle around each session:

1. `pre_session` cleanup/reset,
2. `setup`,
3. agent invocation,
4. `post_session` teardown.

Post-session teardown is attempted even when the agent session fails. Pre-session cleanup exists because a prior devlab run may have crashed before teardown completed.

Executable lifecycle commands live in task profiles under `.devlab/config/profiles/`. Each task resolves to exactly one profile; if task metadata omits `profile`, DevLab uses `default`. Planner and architect sessions do not run inside a task profile environment by default.

The planner owns recognizing when upcoming work requires tooling or environment changes, but executable profile changes should be planned as explicit tasks and reviewed through the normal developer/reviewer workflow rather than silently edited during planning.

Target-specific DevLab workflow artifacts live in the committed, project-local `.devlab/` directory. Role and convention prompt files remain DevLab-owned package resources under `src/devlab/resources/prompts/`.

## Milestone integration

When all tasks for a milestone are closed, the integrator validates the current repository state at that milestone boundary. The goal is to confirm that the milestone's changes work correctly with the previously implemented system, not merely that tasks from the milestone work with each other.

If integration passes, the orchestrator marks the milestone integrated in `.devlab/milestones/` and records the archived integration handoff. The architect then reviews the integrated milestone to check whether the design plan still matches the implemented system and future direction. If integration or architecture review reports Open Issues, the orchestrator creates a file-backed finding, records relevant milestone state, and routes the workflow back to the planner for follow-up task creation.

Findings are active workflow issues stored in `.devlab/findings/`. The planner converts open findings into corrective task files and lists addressed finding IDs in its handoff. The orchestrator then marks those findings as planned. When the milestone later integrates successfully, related planned findings are marked resolved.

## Agent providers

The orchestrator invokes agents through an agent-provider abstraction. The workflow decides which role to run; the provider owns how a concrete agent is called.

This keeps the orchestrator independent from a specific CLI shape. For example, Claude- and Pi-style CLIs can be represented with system-prompt arguments, while Codex CLI can be represented with stdin-based `codex exec -` invocation. Future configurations can map different roles to different providers or models.

A useful future pattern is to run the developer and reviewer with different providers to reduce shared blind spots, while keeping the default single-provider setup simple.

## Target-project DevLab directory

Target-project DevLab workflow artifacts are collected under `.devlab/` in the target repository:

```text
.devlab/
  config/
    README.md
    tooling.md
    profiles/
      default.toml

  specs/
    system/
    deployment/

  plans/
  tasks/
  findings/
  history/
  logs/
  session-artifacts/
```

This directory should be committed by default, including history and logs, so the workflow is auditable and reproducible. Sensitive projects may need redaction, size limits, or opt-out policies for logs.

Reusable DevLab role definitions and conventions should not live in target `.devlab/`; they belong to the DevLab package alongside the orchestrator code.

## Handoffs and continuity

Each session must write a handoff to:

```text
.devlab/session-artifacts/<role>/handoff.md
```

The orchestrator validates that the handoff exists, is non-empty, follows the expected structure, and does not report an unrecoverable issue. It then archives the handoff to:

```text
.devlab/history/
```

Handoffs are intentionally structured. They allow the next session to recover context without relying on chat history.

## Why Markdown and simple files?

DevLab is intentionally file-based because files are:

- visible to humans,
- easy for agents to read and edit,
- versioned by Git,
- easy to diff and review,
- portable across tools,
- robust after crashes or interrupted runs.

This design trades some database convenience for transparency and restartability, which are more important for the current project.

## Tooling philosophy

The project prefers fewer tools and simple defaults.

Current Python tooling policy is documented in `.devlab/config/tooling.md`. Default validation commands and executable environment lifecycle commands are defined in `.devlab/config/profiles/default.toml`.

In short:

- `uv` manages dependencies, lockfiles, environments, and command execution,
- `uv_build` builds the package,
- `ruff` handles linting and formatting,
- `ty` handles static type checking,
- `pytest` handles tests.

Operational details such as exact validation commands belong in task metadata or target-specific profiles, not in reusable role files. Stable environment lifecycle commands belong in target-specific profiles so developer, reviewer, and integrator sessions start from a controlled baseline.

## Design tradeoffs

### Strict workflow vs. flexibility

DevLab is intentionally strict: one role, one task, one handoff, explicit status transitions. This can feel slower than asking an agent to do many things at once, but it improves control, auditability, and recovery.

### File-backed issues vs. external issue tracker

A real issue tracker could provide search, dashboards, permissions, comments, and integrations. The file-backed tracker provides the features needed now with much less operational overhead.

The `FileTaskTracker` abstraction keeps the door open for a future external backend without forcing that complexity into the current design.

### Minimal context vs. full context

Agents may sometimes need to search the repository to find missing detail. That is acceptable. The alternative—loading too much context by default—risks distracting the agent and consuming the context window with irrelevant information.

## Current non-goals

DevLab is not currently trying to be:

- a full replacement for Jira,
- a general CI/CD system,
- a multi-agent runtime with concurrent sessions,
- a database-backed project management platform,
- a fully self-modifying autonomous product factory without human inspectability.

Those capabilities may become relevant later, but the current design focuses on a small, reliable, inspectable development loop.

## Summary

DevLab is designed to make long-running agentic development practical by reducing reliance on fragile conversational context.

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
