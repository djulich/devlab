# DevLab Evaluation by Pi

This repo is a small Python “agentic development system.” It defines a workflow where separate LLM/Claude sessions act as different software-development roles: architect, planner, and developer.

## What It Contains

### Core Code

Main implementation:

- `src/devlab/orchestrator.py`

This is a CLI orchestrator exposed as:

```toml
[project.scripts]
devlab = "devlab.orchestrator:main"
```

It repeatedly:

1. Checks project state.
2. Chooses a role:
   - `architect` if no design plan exists.
   - `planner` if there are no backlog tasks.
   - `developer` if backlog tasks exist.
   - stops if all milestones are complete.
3. Builds a system prompt from role/convention/tooling docs.
4. Invokes Claude via:

```python
claude -p --dangerously-skip-permissions --system-prompt ...
```

5. Requires the session to write a handoff file.
6. Archives handoffs into `work/history/`.
7. If a developer task is complete, archives and removes it from `work/backlog/`.

### Process and Specification Files

Role definitions live in:

- `specs/development/role-architect.md`
- `specs/development/role-planner.md`
- `specs/development/role-developer.md`
- `specs/development/role-orchestrator.md`

Shared conventions:

- `specs/development/conventions.md`

Tooling assumptions:

- `specs/development/tooling.md`

Work artifacts:

- `work/plans/design-plan.md`
- `work/plans/project-plan.md`
- `work/backlog/`
- `work/history/`

Currently the actual system spec and plans are empty:

- `specs/system/README.md`
- `specs/deployment/README.md`
- `work/plans/design-plan.md`
- `work/plans/project-plan.md`

So this repo is more of a template/skeleton for running an agent-managed software project than a populated app.

### Tests

Tests are in:

- `tests/test_orchestrator.py`

They cover state selection, task completion detection, prompt composition, timestamp format, and closing tasks.

I tried to run tests and linting, but `uv` is not installed in this environment:

```text
/bin/bash: line 1: uv: command not found
```

## What It Does Well

### 1. Clear Role Separation

The architect/planner/developer split is clean. Each role has a focused responsibility and its own prompt material.

That makes the workflow understandable and easy to extend.

### 2. Simple, Deterministic State Machine

The orchestration logic is intentionally small:

```python
if no design plan: architect
elif no tasks: planner
else: developer
```

That simplicity is a strength for a template.

### 3. Artifact-Based Workflow

Using files for plans, tasks, handoffs, backlog, and history is pragmatic. It makes the agent workflow inspectable and versionable.

Good directories:

- `work/backlog/`
- `work/history/`
- `work/plans/`
- `.session-artifacts/<role>/`

### 4. Tests Cover the Important Control Flow

The tests are small but useful. They validate the core orchestration behavior without needing Claude to run.

### 5. Documentation Is Honest About Limitations

`docs/devlab-evaluation.md` is especially good. It identifies realistic limits around dependencies, multi-service projects, integration testing, and lack of reviewer/integrator roles.

## What It Does Not Do So Well

### 1. The Project Is Currently Empty as a DevLab Instance

The template exists, but the actual desired system is unspecified:

- `specs/system/README.md` is empty.
- `design-plan.md` is empty.
- `project-plan.md` is empty.

So running DevLab now would invoke the architect with no real product requirements.

### 2. Hardcoded Claude Dependency

`invoke_session()` assumes the `claude` CLI exists:

```python
cmd = ["claude", "-p", "--dangerously-skip-permissions", ...]
```

There is no abstraction for providers, models, or dry-run/test mode. This makes DevLab tightly coupled to one local tool.

### 3. `PROJECT_ROOT` Is Brittle

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]
```

This works in the source checkout, but if installed as a package it may resolve to the installed package location rather than the repo the user wants to operate on.

A better CLI would accept:

```bash
devlab --root /path/to/project
```

or default to `Path.cwd()`.

### 4. Task Dependencies Are Not Enforced

The planner docs say dependencies can be noted, but the orchestrator ignores them. It simply selects the lowest-numbered task:

```python
tasks = sorted(backlog.glob("T*.md"))
return tasks[0] if tasks else None
```

So dependent tasks can run too early.

### 5. Completion Tracking Is Fragile

Developer task completion is detected by counting markdown checkboxes:

```python
checked = text.count("- [x]")
unchecked = text.count("- [ ]")
return checked > 0 and unchecked == 0
```

Issues:

- Only lowercase `- [x]` counts.
- Any extra unchecked checklist in the file prevents completion.
- It does not validate specific acceptance sections.
- It does not update `work/plans/project-plan.md`.

That last point is important: closing a task removes it from the backlog, but the project plan may still say `- [ ] T0001`. There is no explicit mechanism requiring the developer or orchestrator to mark the project plan task complete.

### 6. No Real Handoff Validation

The orchestrator only checks that this file exists:

```text
.session-artifacts/<role>/handoff.md
```

It does not check whether it is non-empty, follows the template, reports blockers, or contains useful content.

The role-orchestrator doc says unrecoverable blockers should stop the process, but the code does not parse handoffs for blockers.

### 7. Tooling Docs and Package Config Disagree

`specs/development/tooling.md` says:

```md
Build backend: uv
Static type checking: ty
```

But `pyproject.toml` uses:

```toml
build-backend = "hatchling.build"
```

And dev dependencies are:

```toml
dev = ["pytest", "ruff"]
```

`ty` is required by the developer checklist but is not included in dev dependencies.

Also, `uv` is not itself a build backend; it is an environment/package manager.

### 8. Dangerous Permission Mode

The Claude invocation uses:

```bash
--dangerously-skip-permissions
```

That may be intentional for automation, but it is risky. For a template, this should probably be configurable and clearly warned about.

### 9. No Reviewer or Integration Role

The repo’s own evaluation already calls this out. The developer self-validates, but no separate role checks:

- whether the task was correctly implemented,
- whether unintended changes were made,
- whether multiple completed tasks work together.

## Overall Impression

This is a good minimal prototype for orchestrating role-based LLM development sessions in a single-repo Python project. Its strengths are simplicity, clear artifact conventions, and testable orchestration logic.

Its main weaknesses are that it is still very shallow operationally: no dependency handling, no reviewer, no integration pass, weak handoff validation, brittle completion tracking, and tight coupling to the Claude CLI.

If I were improving it, my first changes would be:

1. Add `--root` and use `Path.cwd()` by default.
2. Validate handoff content, not just existence.
3. Add task dependency support.
4. Have the orchestrator update `project-plan.md` when closing a task.
5. Add a reviewer role after developer sessions.
6. Fix tooling metadata: add `ty`, correct build backend docs.
7. Make Claude invocation configurable.
