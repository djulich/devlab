# DevLab Evaluation

Assessment of DevLab capabilities, limitations, and improvement opportunities.

## Complexity Ceiling

DevLab can handle projects where **all components live in one repo and one language**. A moderately complex CLI tool, a single web service with a database, or a library with multiple modules are within reach.

A multi-service platform with a REST gateway and web GUI would **break DevLab** in several ways:

- **Task dependencies become blocking.** The planner creates independent tasks, but a gateway service can't be tested until the backend services it proxies exist. The orchestrator picks the lowest-numbered task — it has no concept of dependency ordering.
- **Multi-language/multi-toolchain.** A React frontend and a Python backend need different tooling. The developer role has one validation checklist (ruff, ty, pytest). A frontend task needs eslint, tsc, vitest.
- **Integration testing across services.** The developer validates a single task in isolation. Nobody verifies that the gateway talks to the backend, or that the frontend renders data from the API.
- **Context scaling.** As the codebase grows, the design plan and project plan get inlined into session prompts. A 20-service platform would produce a design plan that alone exhausts a meaningful chunk of context.

**Realistic ceiling:** A project with 1-2 packages, ~20-30 tasks total, one language, one build toolchain. Roughly what a single developer could build in a week.

## Role Partitioning Assessment

The three-role split (architect, planner, developer) is sound for the current scope but has gaps.

### What Works Well

- Architect → Planner → Developer is a clean pipeline with clear artifact boundaries.
- Each role has a single responsibility and a single output artifact.
- The orchestrator's state machine is trivially simple (4 rules).

### What's Missing

1. **Reviewer role.** The developer self-validates, but nobody checks whether the implementation matches the task's intent or introduced regressions. A reviewer that reads the task + the diff and either approves or sends it back would catch subtle errors.
2. **Integrator role.** Once multiple tasks are complete, someone needs to verify they work together. An integrator session at milestone boundaries would run the full test suite and check for coherence.
3. **Architect re-invocation.** The orchestrator calls the architect when the design plan is empty, then never again. Design plans evolve — after implementing a few tasks, interfaces may need revision or new components may emerge. There is no trigger to re-invoke the architect mid-project.

## Improvement Opportunities

### Task Dependencies

Add a `## Depends On` section to the task template. The orchestrator reads it before selecting a task — if listed task IDs are still in the backlog, skip and pick the next eligible one. This alone would unlock moderately complex projects where task ordering matters.

### Milestone-Scoped Loops

A milestone boundary (all tasks for M1 complete) would be a natural point to re-invoke the architect for design review, or run an integrator check, before the planner creates M2 tasks.

### Per-Task Tooling Overrides

Instead of one global tooling.md, allow tasks to specify which validation commands to run. This would let frontend and backend tasks coexist without the developer role needing to know about both toolchains upfront.

### Handoff Quality Check

The orchestrator currently only checks that a handoff file *exists*. A minimal content check (not empty, contains expected sections) would catch sessions that produce a stub handoff without doing real work.

## Summary

DevLab is well-suited for single-language, single-repo projects of moderate size. The role split is right for that scope. To handle anything larger, the highest-leverage additions would be:

1. Task dependencies (cheap to add)
2. A reviewer role (medium effort)
3. Milestone-boundary hooks for architect re-invocation and integration checks

The multi-service platform is out of reach without those, plus multi-toolchain support.
