# Harness TODOs / Features to be implemented

## Tooling and Environment Profiles

Current state: task files can specify concrete `validation` commands. If omitted, worker agents use defaults from `specs/development/tooling.md`; if `validation = []`, no validation commands are required. Shared environment lifecycle commands live in `specs/development/environment.toml` and are enforced by the orchestrator for developer/reviewer/integrator sessions.

Open feature: add reusable tooling and environment profiles so tasks and target projects can reference concise profile names instead of repeating command lists and lifecycle commands.

- Define harness-provided profiles for common stacks, e.g. Python CLI, Python FastAPI backend, Python Django backend, React frontend, Postgres service, Redis service, Docker Compose app.
- Let target workspaces define custom profiles at a discoverable location.
- Let tasks reference validation profiles and optionally add task-specific validation commands.
- Let environment configuration compose setup/teardown/service profiles for the target project's components.
- Keep profile use declarative; do not make the orchestrator execute arbitrary task validation commands yet.

## Target-specific Harness Workflow Directory

Current state: target-project workflow artifacts are split across `specs/system/`, `specs/development/tooling.md`, `specs/development/environment.toml`, `work/`, and `.session-artifacts/`.

Open feature: collect target-project harness workflow artifacts under a committed, project-local `.harness/` directory.

Possible future target-project layout:

```text
.harness/
  config/
    tooling.toml
    environment.toml
    profiles/
      python-cli.toml
      fastapi-postgres.toml

  specs/
    system/
    deployment/

  plans/
    design-plan.md
    project-plan.md

  tasks/
    T0001_...

  findings/
    F0001_...

  history/
    20260507T235700_developer_handoff.md
    integrated_M1.md

  logs/
    environment/
      20260507T235700_developer_pre_session_1.log
```

Rationale:

- Different target projects need different specs, tooling, validation, services, and environment lifecycles.
- `.harness/` should be target-project-local and committed by default, including workflow history and logs, to preserve auditability and reproducibility.
- `specs/development/` should remain harness-owned role/prompt source, analogous to harness `src/`, not target-project workflow state.
- Generated runtime logs/history are still workflow artifacts; keeping them under `.harness/` makes cleanup, review, and migration easier.

Implementation concerns:

- Add redaction/size controls before committing logs by default in sensitive projects.
- Plan a migration path from current `work/`, `.session-artifacts/`, and `specs/system/` paths.
- Keep reusable built-in profiles in the harness package; let `.harness/config/profiles/` define target-specific profiles.

## Integration Findings and Corrective Planning

Current state: the integrator runs at completed milestone boundaries. If integration passes, the orchestrator writes an integration marker. If integration reports Open Issues, the orchestrator creates a file-backed finding in `work/findings/` and routes the workflow back to the planner.

Current state: planner handoffs include `## Addressed Findings`; the orchestrator marks listed findings as `planned`. When the milestone later integrates successfully, related planned findings are marked `resolved`.

Open features:

- Improve finding titles/bodies generated from integrator handoffs.
- Add stronger validation that planner-created tasks actually reference addressed findings.
- Add reporting for open/planned/resolved findings.
- Consider allowing reviewer/developer/architect roles to create findings, not only the integrator.

## Architect Re-invocation

Current state: the orchestrator calls the architect when the design plan is empty, then never again. Design plans evolve — after implementing milestones, interfaces may need revision or new components may emerge.

Planned feature: after a milestone integrates successfully, invoke the architect once to review whether the design plan still matches the implemented system and future project direction.

Likely implementation:

- Add architecture-review markers per milestone, e.g. in `work/history/`.
- Select architect when a milestone is integrated but not architecture-reviewed.
- Build an architect prompt focused on milestone-boundary design review, not greenfield design.
- After architecture review, route to planner if the design/project plan may need adjustment.

## Milestone State

Current state: milestone completion is computed from task metadata and integration completion is tracked by marker files.

Open feature: introduce explicit milestone metadata/state if marker files and project-plan text become insufficient.

Possible state to track:

- milestone id/title
- integration required or skipped
- integrated status
- architecture-reviewed status
- current/planned/complete status

## Harness Workflow Evaluations

Current state: normal tests use deterministic providers such as `MockProvider` and do not call live agents.

Open feature: add opt-in workflow evaluations that run the harness on small target specifications and check observable behavior, not exact generated files.

- Keep live-agent evaluations separate from default tests because they consume tokens and are nondeterministic.
- Use small specs with objective acceptance checks, e.g. CLI calculator, tiny API, or frontend/backend smoke app.
- Grade generated systems with black-box checks such as commands, HTTP responses, package builds, and test suites.
- Record diagnostics such as sessions used, findings created, review rejections, runtime, and final artifacts.
- Add a deterministic scripted fake-agent provider/evaluation mode first or alongside live evals; it writes canned role outputs/files for known specs and tests the full harness loop without tokens.

## Automatic Version Control

The harness should eventually be able to commit repository state after completed sessions or workflow gates.

Open questions:

- Commit after every valid session, after every task closure, or after milestone integration?
- Should failed integration findings be committed automatically?
- How should commit messages be generated and reviewed?
- How should dirty working tree state before a session be handled?

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator, instead of just by the worker agent.
- Sandboxing or approval policy for executable environment lifecycle changes.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Multi-agent concurrent sessions.
- External task tracker backends such as Jira or GitHub Issues.
- Full release/deployment automation.
