# Environment

This document explains the shared development environment lifecycle for this workspace.

Executable lifecycle commands live in `specs/development/environment.toml`.

## Lifecycle

For managed roles, the orchestrator enforces this sequence around each session:

1. `pre_session` — remove leftover state from a crashed or interrupted prior session.
2. `setup` — establish the development environment for the current session.
3. Agent session.
4. `post_session` — tear down session-local environment state. This is attempted even if the agent session fails.

Managed roles are defined in `environment.toml`. Planner reads the environment definition but does not run inside the managed environment by default.

## Ownership

- The planner identifies when future milestones or tasks require environment changes.
- The planner must create an explicit task for executable environment lifecycle changes instead of silently editing them during planning.
- Developer/reviewer sessions implement and validate those environment changes through the normal task workflow.

## Notes

- Lifecycle commands are run from the workspace root.
- Keep lifecycle commands deterministic and safe for repeated harness runs.
- Avoid relying on globally installed project packages; use workspace-local tooling.
