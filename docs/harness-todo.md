# Harness TODOs / Features to be implemented

## Tooling Profiles

Current state: task files can specify concrete `validation` commands. If omitted, worker agents use defaults from `specs/development/tooling.md`; if `validation = []`, no validation commands are required.

Open feature: add reusable tooling profiles so tasks can reference concise profile names instead of repeating command lists.

- Define harness-provided profiles for common stacks, e.g. Python CLI, Python FastAPI backend, Python Django backend, React frontend.
- Let target workspaces define custom profiles at a discoverable location.
- Let tasks reference profiles and optionally add task-specific validation commands.
- Keep profile use agent-facing and declarative; do not make the orchestrator execute arbitrary validation commands yet.

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

## Automatic Version Control

The harness should eventually be able to commit repository state after completed sessions or workflow gates.

Open questions:

- Commit after every valid session, after every task closure, or after milestone integration?
- Should failed integration findings be committed automatically?
- How should commit messages be generated and reviewed?
- How should dirty working tree state before a session be handled?

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Multi-agent concurrent sessions.
- External task tracker backends such as Jira or GitHub Issues.
- Full release/deployment automation.
