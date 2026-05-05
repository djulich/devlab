# Harness TODOs / Features to be implemented

## Tooling Profiles

- Make tooling.md configurable per task (tooling profiles?), i.e. React tooling for front-end dev tasks, and Python tooling for backend tasks.
- The harness project defines some core tooling profiles for common tasks, e.g. Python CLI, Python Django backend, Python FastAPI application, React frontend.
- The target project shall be able to define custom tooling profiles for project-specific tasks which are not covered by the tooling profiles in the harness. These custome tooling profiles live at defined locations inside the target repo, so that the harness can discover and use them for its agentic development workflow

## Integrator Role

The harness needs integration testing across services. The developer validates a single task in isolation. Nobody verifies that the gateway talks to the backend, or that the frontend renders data from the API.

Once multiple tasks are complete, someone needs to verify they work together. An integrator session at milestone boundaries would run the full test suite (especially the integration tests) and check for coherence.

## Architect Re-invocation

Currently, the orchestrator calls the architect when the design plan is empty, then never again. Design plans evolve — after implementing a few tasks, interfaces may need revision or new components may emerge. There is no trigger to re-invoke the architect mid-project.

A milestone boundary (all tasks for M1 complete) would be a natural point to re-invoke the architect for design review, or run an integrator check, before the planner creates M2 tasks.
