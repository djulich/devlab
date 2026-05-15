# DevLab Evaluation

Assessment of DevLab capabilities, limitations, and improvement opportunities. This evaluation reflects the current system with five active roles (architect, planner, developer, reviewer, integrator), file-backed task/milestone/finding tracking, profile-based environment lifecycle, and an agent-provider abstraction.

## Codebase Health

- 13 Python modules, 2,903 lines of production code.
- 157 tests, 2,656 lines of test code. All pass in ~0.4s.
- Zero external dependencies (stdlib only).
- Clean linting (ruff) and type checking (ty).

## Strengths

### Clean abstractions that earn their existence

`AgentProvider`, `FileTaskTracker`, `FileMilestoneTracker`, and `FileFindingTracker` decouple concrete concerns (CLI shape, file format, storage backend) from workflow logic. These are not speculative: the design doc identifies future backends (Jira, GitHub Issues, different agent CLIs) as plausible, and the abstractions are already exercised by `MockProvider` in tests.

### Orchestrator is the right size

At ~780 lines, `orchestrator.py` is the largest module, but it owns the workflow engine — that is where complexity belongs. The state machine in `assess_state()` is readable and testable. Role selection priority is clear: review > open findings > architecture review > integration > development > blocked check > planner.

### Disciplined prompt resources

`conventions.md` at 108 lines defines vocabulary, templates, and artifact locations without redundancy. Role files stay focused on procedures. This directly serves the core design constraint that context is scarce.

### Honest self-evaluation cycle

The original evaluation (written when DevLab had three roles) correctly identified its own gaps: reviewer, integrator, task dependencies, and milestone boundaries. All of those have since been implemented.

## Complexity Ceiling

DevLab can handle projects where all components live in one repo. A moderately complex CLI tool, a single web service with a database, or a library with multiple modules are within reach.

A multi-service platform with separate frontend and backend stacks would stress several limits:

- **Task dependency ordering.** Dependencies are supported, but the planner must get the ordering right — there is no automatic topological sort or cycle detection.
- **Multi-toolchain.** Profiles support per-task tooling, but the planner and developer must correctly match tasks to profiles. A project with Python, TypeScript, and Docker needs careful profile setup.
- **Cross-service integration.** The integrator validates at milestone boundaries, but verifying that service A talks to service B requires environment lifecycle commands that spin up both services.
- **Context scaling.** Design plans, project plans, and task listings are inlined into session prompts. A 50-task project would produce planner prompts that consume a meaningful fraction of the context window.

**Realistic ceiling:** A project with 1-3 packages, ~30-40 tasks total, 1-2 toolchains, profile-based environment setup. Roughly what a single developer could build in 1-2 weeks.

## Concerns

### Prompt-building weight in orchestrator.py

Lines 248-464 are prompt builders — ~216 lines of string assembly. These are well-tested but represent a second concern growing inside the orchestrator. As prompt complexity grows (context size monitoring, spec summaries, profile listings), this will become the maintenance bottleneck.

### Role-dispatch in process_handoff

`process_handoff` is a 50-line if/elif chain where each branch has different side effects (create finding, mark task, mark milestone). The current five roles are manageable; a sixth or seventh would make this unwieldy.

### Repeated tracker instantiation

`task_tracker(root)`, `finding_tracker(root)`, and `milestone_tracker(root)` are called fresh on every use. `assess_state` alone calls `task_tracker(root)` 3-4 times per invocation, each time re-parsing all task files from disk. This is fine for small projects but will matter with 50+ tasks.

### No end-to-end workflow test

The 62 orchestrator tests are unit tests against individual functions. There is no test that simulates a multi-session run with `MockProvider` from architect through developer to reviewer. The `run_loop` function — the actual heart of DevLab — is tested only indirectly.

### Error recovery

Any agent failure, handoff failure, or environment error calls `sys.exit()`. The orchestrator cannot return structured results to callers, which blocks features like partial recovery, retry, and programmatic workflow control.

## Role Partitioning Assessment

The five-role split is well-suited for the current scope.

### What works well

- Architect → Planner → Developer → Reviewer → Integrator is a clean pipeline with clear artifact boundaries.
- Each role has a single responsibility and a single output artifact (the handoff).
- The reviewer/developer feedback loop (in_review → changes_requested → open) catches implementation issues before integration.
- Milestone-boundary integration and architecture review provide natural quality gates.
- Findings route integration/architecture issues back to the planner for corrective task creation.

### Current limitations

- The planner is the most context-heavy role (~5.1 KB prompt resource + design plan + project plan + task listing + profile listing + findings). As projects grow, the planner session is the first to hit context pressure.
- There is no role for deployment verification beyond what the integrator checks. The deployment spec support in the TODO would likely need either a dedicated role or an integrator sub-mode.
- Architect re-invocation is triggered only at milestone boundaries. Mid-milestone design drift (e.g., a developer discovers the planned interface is infeasible) has no feedback path to the architect except through the handoff's Open Issues section, which routes to the planner, not the architect.

## Summary

DevLab is solid engineering: clean abstractions, good test coverage, disciplined prompts, and an honest self-evaluation cycle. The highest-leverage improvements are in workflow reliability (end-to-end testing, prompt size monitoring, error recovery) rather than feature expansion.
