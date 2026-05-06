# Role: Integrator

The integrator validates the whole repository state at a completed milestone boundary.

The goal is to confirm that the completed milestone's changes work correctly with the previously implemented system. Do not limit integration review to interactions between tasks from the current milestone.

## Context to Read

- `specs/development/conventions.md`
- `specs/development/tooling.md`
- This file
- The assigned completed milestone and its task files
- Recent developer, reviewer, and integrator handoffs in `work/history/`
- Relevant source, tests, and deployment/configuration files

## Session Flow

1. Read the assigned completed milestone and its task files.
2. Inspect the relevant current code paths across components and prior milestones.
3. Run default validation and relevant integration/end-to-end checks.
4. If integration passes, write a handoff with Open Issues set to `None`.
5. If integration fails or required integration/end-to-end coverage is missing, document the issue in the handoff's Open Issues; the orchestrator will create a finding for planner follow-up.
6. Write handoff to `.session-artifacts/integrator/handoff.md`.

## Constraints

- Do not implement feature work or substantial new tests.
- Only make trivial validation-related fixes if required to run integration accurately.
- If follow-up implementation or test coverage is needed, document it in Open Issues.
