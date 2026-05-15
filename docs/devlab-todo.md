# DevLab TODOs / Features to be Implemented

Items are ordered by priority: workflow reliability first, then observability, then feature expansion.

---

## 1. End-to-End Workflow Test with MockProvider

Priority: highest. The `run_loop` function is tested only indirectly through unit tests of its component functions. There is no test that exercises the full orchestration loop.

Goal: create a test that sets up a workspace with a system spec, configures `MockProvider` to write canned handoffs and task files per role, and runs `run_loop` from architect through closed tasks. Verify that state transitions (task status, milestone state, findings) proceed correctly across multiple sessions.

A scripted deterministic provider that writes known outputs for known specs would also serve as the foundation for workflow evaluations (see item 8).

## 2. Prompt Context Size Monitoring

Priority: high. DevLab's core promise is bounded sessions. If prompt size silently grows past model limits, sessions degrade without warning.

Current state: packaged prompt resources are modest. Approximate fixed system prompt sizes are architect ~1.4k tokens, planner ~2.4k, developer ~1.8k, reviewer ~1.8k, integrator ~1.5k. But session prompts grow with plans, task listings, findings, and profile content.

Implementation direction:

- Add a prompt size estimator for system prompt, session prompt, and selected repository context per role.
- Surface the report through `devlab status --verbose` or a future `devlab doctor` command.
- Warn when a role's initial context exceeds configurable thresholds.
- Consider splitting `conventions.md` into role-relevant sections (core, tasks, findings, reviews, handoffs) and including only what each role needs.
- Consider summarizing profile listings for planner prompts instead of embedding full TOML.

## 3. Error Recovery and Structured Results

Status: **implemented**. `run_loop` returns a `RunResult` dataclass (sessions run, completed flag, exit code, error tuple). All six `sys.exit()` calls replaced with structured returns. `cli.py` translates the result to an exit code. Tests migrated from `SystemExit`-catching to `RunResult` assertions.

Priority: high. Currently, any agent failure, handoff failure, or environment error calls `sys.exit()`. This blocks partial recovery, retry logic, and programmatic workflow control.

Goal: `run_loop` should return structured results (sessions run, final state, errors encountered) instead of calling `sys.exit`. Callers can then decide whether to retry, skip, or abort. This is also a prerequisite for the workflow evaluation tests in item 1 — a test cannot assert on behavior if the function under test exits the process.

## 4. Prompt Builder Extraction

Priority: medium. The `_build_*_prompt` functions (~216 lines) in `orchestrator.py` are a second concern growing inside the workflow engine. Extracting them to a `prompts.py` module would:

- Keep the orchestrator focused on workflow control.
- Make prompt size monitoring (item 2) easier — all prompt logic in one place.
- Reduce the size of `orchestrator.py`, which is already the largest module.

## 5. Integration Findings and Corrective Planning

Priority: medium. The findings loop exists but has quality gaps.

Current state: integrator/architect handoffs with Open Issues create findings. Planner handoffs list addressed finding IDs. The orchestrator marks findings as planned, then resolved when the milestone integrates successfully.

Open improvements:

- Improve finding titles and bodies generated from handoff content — current extraction is minimal.
- Add validation that planner-created tasks actually reference addressed findings.
- Add reporting for open/planned/resolved findings via `devlab status --verbose` or `devlab doctor`.
- Consider allowing reviewer/developer roles to create findings, not only the integrator and architect.

## 6. Tracker Caching

Priority: medium. `task_tracker(root)`, `finding_tracker(root)`, and `milestone_tracker(root)` are instantiated fresh on every call, re-parsing all files from disk each time. `assess_state` alone creates 3-4 tracker instances per invocation.

Goal: create tracker instances once per loop iteration in `run_loop` and pass them through, or use a lightweight session-scoped cache. This prevents quadratic file re-parsing as task counts grow beyond ~30.

## 7. Starting Workflow on an Existing Project

Priority: medium. DevLab should support operation on a project developed outside DevLab.

In this case, the system spec acts as a feature spec. DevLab adds the specified features to the existing project using the same workflow it uses to develop from scratch. The architect and planner roles need to account for existing code and infrastructure rather than assuming a greenfield project.

## 8. DevLab Workflow Evaluations

Priority: medium-low. Add opt-in workflow evaluations that run DevLab on small target specifications and check observable behavior.

Direction:

- Build on the end-to-end test infrastructure from item 1.
- Add a deterministic scripted fake-agent provider first: it writes canned role outputs for known specs and tests the full DevLab loop without tokens.
- Keep live-agent evaluations separate from default tests (they consume tokens and are nondeterministic).
- Use small specs with objective acceptance checks (CLI calculator, tiny API, smoke app).
- Grade generated systems with black-box checks: commands, HTTP responses, package builds, test suites.
- Record diagnostics: sessions used, findings created, review rejections, runtime, final artifacts.

## 9. Project Status Drift Detection

Priority: medium-low. DevLab should guard against project progress drifting from the design plan or system spec.

Simpler approach than git rollback: at milestone boundaries (or periodically), the architect evaluates whether the implemented system still aligns with the design plan and system spec. If drift is detected, the architect flags it as a finding. The planner creates corrective tasks. No git rollback needed — the finding/planning loop handles course correction.

The more aggressive approach (git rollback to previous milestone, re-plan) is high-risk: it discards working code and creates complex merge scenarios. Defer this unless the finding-based correction proves insufficient.

## 10. Deployment Specification and Verification

Priority: low. Well-defined in concept but represents a feature expansion. DevLab should be more reliable on its current scope before taking this on.

Goal: support deployment requirements under `.devlab/specs/deployment/` and let the normal workflow plan, implement, review, and integrate deployment artifacts.

Required verification layers:

1. **Static/artifact validation** — build and inspect deployment artifacts without external infrastructure (docker build, image inspection, RPM build, systemd unit validation).
2. **Local ephemeral deployment** — run artifacts locally in disposable resources and smoke-test (docker run, compose tests, health checks, teardown via environment lifecycle).
3. **Disposable test infrastructure** — deploy to explicitly configured, isolated, non-production infrastructure and destroy after verification (temporary VM, disposable K8s namespace, test registry).

Design constraints:

- DevLab should make projects deployable and verify deployment behavior; it should not deploy to production by default.
- Test infrastructure use must be explicit, allowlisted, isolated, and aggressively cleaned up.
- Deployment implementation should remain task-based through the normal role workflow.

## 11. Automatic Version Control

Priority: low. DevLab should eventually commit repository state after completed sessions or workflow gates. Depends on error recovery (item 3) being in place first.

Open questions:

- Commit after every valid session, after every task closure, or after milestone integration?
- Should failed integration findings be committed automatically?
- How should commit messages be generated?
- How should dirty working tree state before a session be handled?
- Should DevLab use per-milestone feature branches? (Current recommendation: defer branching, use tags for milestones, add branches only if rollback becomes a real need.)

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator (currently delegated to worker agents).
- Sandboxing or approval policy for executable environment lifecycle changes.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Multi-agent concurrent sessions.
- External task tracker backends (Jira, GitHub Issues, Linear).
- Full release/deployment automation.
