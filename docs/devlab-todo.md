# DevLab TODOs / Features to be Implemented

Items are ordered by priority: workflow reliability first, then observability, then feature expansion.

---

## 1. End-to-End Workflow Test with MockProvider

Status: **implemented**. `tests/test_orchestrator_e2e.py` initializes a target workspace with `init_workspace`, runs `run_loop` with scripted `MockProvider` behavior, and verifies full workflow state transitions. Coverage includes both the happy path (`architect → planner → developer → reviewer → integrator → architect approval`) and an integration-finding corrective loop (`integrator finding → planner corrective task → developer/reviewer → reintegration → architecture approval`).

The scripted deterministic provider also serves as the foundation for future workflow evaluations (see item 8).

## 2. Prompt Context Size Monitoring

Status: **initial monitoring implemented**. DevLab now estimates system, session, and total prompt size per role using the actual prompt builders. `devlab status --verbose` reports approximate token counts and OK/WARNING/CRITICAL threshold status. Thresholds are configurable in `.devlab/config/agents.toml` via `[prompt_context]` and `[prompt_context.roles.<role>]`, and `devlab doctor` validates the threshold configuration.

Follow-up work required to complete the broader feature:

- Add prompt reduction strategies for oversized contexts, especially summarizing profile listings for planner prompts, limiting historical handoffs, and including only role-relevant parts of conventions.
- Consider splitting `conventions.md` into role-relevant sections (core, tasks, findings, reviews, handoffs) and including only what each role needs.
- Consider model-specific tokenizers or provider-specific context windows if approximate sizing proves insufficient.

## 3. Error Recovery and Structured Results

Status: **implemented**. `run_loop` returns a `RunResult` dataclass (sessions run, completed flag, exit code, error tuple). All six `sys.exit()` calls replaced with structured returns. `cli.py` translates the result to an exit code. Tests migrated from `SystemExit`-catching to `RunResult` assertions.

Priority: high. Currently, any agent failure, handoff failure, or environment error calls `sys.exit()`. This blocks partial recovery, retry logic, and programmatic workflow control.

Goal: `run_loop` should return structured results (sessions run, final state, errors encountered) instead of calling `sys.exit`. Callers can then decide whether to retry, skip, or abort. This is also a prerequisite for the workflow evaluation tests in item 1 — a test cannot assert on behavior if the function under test exits the process.

## 4. Prompt Builder Extraction

Status: **implemented**. Prompt builders extracted to `prompts.py`. Shared workspace infrastructure (constants, tracker factories, state queries, `RoleConfig`, `ROLES`) extracted to `workspace.py` to eliminate a circular import between orchestrator and prompts. Module layering is now: `workspace.py` (state reading) → `prompts.py` (text generation) → `orchestrator.py` (workflow control).

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

Status: **workspace snapshot caching implemented**. `Workspace` and `WorkspaceSnapshot` now provide a workspace access boundary in `workspace.py`: `Workspace` owns explicit mutating sync behavior, while `WorkspaceSnapshot` is a cached read-only view over tasks, findings, and milestones. `Workspace.snapshot` is lazily created and automatically invalidated by mutating workspace methods. Prompt builders, prompt context reporting, status, doctor, and the orchestrator loop now use snapshots for read-heavy paths.

First-class workspace handles now exist for mutations: `WorkspaceTask`, `WorkspaceMilestone`, `WorkspaceFinding`, and `WorkspaceFindings`. Orchestration can express atomic domain transitions through handles such as `workspace.task("T0001").close()`, `workspace.milestone("M1").mark_integrated(handoff)`, and `workspace.finding("F0001").mark_resolved()` without importing concrete file trackers.

No open follow-up work remains for this item. Future changes should preserve the current boundary: use `WorkspaceSnapshot` for cached read-only queries, use first-class workspace handles for atomic mutations, and create a new `Workspace` when external file changes need to be observed.

## 7. Durable Project Knowledge: CONTEXT.md and ADRs

Priority: medium. DevLab should preserve project language and architectural rationale as durable repository artifacts and feed relevant knowledge back into future role sessions.

Motivation: agent coding quality degrades as repositories grow because important terms, boundaries, constraints, and trade-offs are no longer all visible in the immediate task context. DevLab already persists workflow state in repository files; it should also make domain language and architectural decisions durable rather than relying on conversational memory.

Recommended artifact locations:

- `CONTEXT.md` at the repository root for single-context projects.
- `CONTEXT-MAP.md` plus context-specific `CONTEXT.md` files for multi-context projects.
- `docs/adr/NNNN-slug.md` for Architecture Decision Records.

Design direction:

- Add a `knowledge.py` module that discovers project knowledge files without mutating the workspace.
- Include discovered knowledge in prompt assembly through `WorkspaceSnapshot` or a small read-only knowledge snapshot.
- Keep `CONTEXT.md` scoped to project-specific language: glossary terms, relationships, example dialogue, and flagged ambiguities. It must not become a spec, implementation guide, or scratchpad.
- Keep ADRs sparse. Create one only when a decision is hard to reverse, surprising without context, and the result of a real trade-off.
- Treat these files as target-owned project docs, not hidden `.devlab/` state.
- Add prompt context accounting for included context and ADR content from the beginning.

Role responsibilities:

- Architect: primary owner of ADR creation/update when architectural decisions meet the ADR criteria; co-owner of `CONTEXT.md` for initial domain framing, context boundaries, and architecture-significant terminology.
- Planner: co-owner of `CONTEXT.md` updates when domain language is clarified while planning tasks or corrective work.
- Developer, reviewer, and integrator: read these artifacts and flag contradictions; avoid broad rewrites unless explicitly required by the task or finding.
- Orchestrator: never authors knowledge files directly; it only discovers, reports, and supplies them to role prompts.

Incremental implementation plan:

1. Implement read-only discovery for `CONTEXT.md`, `CONTEXT-MAP.md`, context-specific `CONTEXT.md` files, and `docs/adr/*.md`.
2. Include root `CONTEXT.md` and ADR summaries/full text in role prompts while repositories are small.
3. Extend prompt context reporting and `doctor` prompt-size checks to account for knowledge files.
4. Add minimal prompt guidance to packaged role prompts: architects may create sparse ADRs; planners may update `CONTEXT.md`; all roles should honor existing terminology and decisions.
5. Add optional `doctor` checks for duplicate ADR numbers, malformed ADR filenames, and `CONTEXT-MAP.md` links that point to missing files.
6. Later, if prompt size becomes an issue, switch from including all ADR text to including an ADR index plus role/task-relevant ADRs.

## 8. Starting Workflow on an Existing Project

Priority: medium. DevLab should support operation on a project developed outside DevLab.

In this case, the system spec acts as a feature spec. DevLab adds the specified features to the existing project using the same workflow it uses to develop from scratch. The architect and planner roles need to account for existing code and infrastructure rather than assuming a greenfield project.

## 9. DevLab Workflow Evaluations

Priority: medium-low. Add opt-in workflow evaluations that run DevLab on small target specifications and check observable behavior.

Direction:

- Build on the end-to-end test infrastructure from item 1.
- Add a deterministic scripted fake-agent provider first: it writes canned role outputs for known specs and tests the full DevLab loop without tokens.
- Keep live-agent evaluations separate from default tests (they consume tokens and are nondeterministic).
- Use small specs with objective acceptance checks (CLI calculator, tiny API, smoke app).
- Grade generated systems with black-box checks: commands, HTTP responses, package builds, test suites.
- Record diagnostics: sessions used, findings created, review rejections, runtime, final artifacts.

## 10. Project Status Drift Detection

Priority: medium-low. DevLab should guard against project progress drifting from the design plan or system spec.

Simpler approach than git rollback: at milestone boundaries (or periodically), the architect evaluates whether the implemented system still aligns with the design plan and system spec. If drift is detected, the architect flags it as a finding. The planner creates corrective tasks. No git rollback needed — the finding/planning loop handles course correction.

The more aggressive approach (git rollback to previous milestone, re-plan) is high-risk: it discards working code and creates complex merge scenarios. Defer this unless the finding-based correction proves insufficient.

## 11. Deployment Specification and Verification

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

## 12. Automatic Version Control

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
