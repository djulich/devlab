# DevLab TODOs / Features to be Implemented

Only open or partially complete work is listed here. Completed implementation-history items are removed once no follow-up remains.

---

## 1. Prompt Context Size Monitoring

Status: **initial monitoring implemented**. DevLab estimates system, session, and total prompt size per role using the actual prompt builders. `devlab status --verbose` reports approximate token counts and threshold status. Thresholds are configurable in `.devlab/config/agents.toml`; `devlab doctor` validates the configuration.

Open work:

- Add prompt reduction strategies for oversized contexts: summarize profile listings, limit historical handoffs, and include only role-relevant convention sections.
- Consider splitting `conventions.md` into role-relevant sections.
- Consider model-specific tokenizers or provider-specific context windows if approximate sizing proves insufficient.

## 2. Integration Findings and Corrective Planning

Priority: medium. The findings loop exists but has quality gaps.

Current state: integrator/architect handoffs with Open Issues create findings. Planner handoffs list addressed finding IDs. The orchestrator marks findings as planned, then resolved when the milestone integrates successfully.

Open work:

- Improve finding titles and bodies generated from handoff content.
- Validate that planner-created tasks actually reference addressed findings.
- Add reporting for open/planned/resolved findings via `devlab status --verbose` or `devlab doctor`.
- Consider allowing reviewer/developer roles to create findings, not only integrator and architect.

## 3. Durable Project Knowledge: CONTEXT.md and ADRs

Status: **initial implementation complete**. DevLab discovers target-owned `CONTEXT.md`, `CONTEXT-MAP.md`, linked context files, and `docs/adr/*.md` without mutating the workspace. Discovered knowledge is included in role prompts, prompt size reporting accounts for it, role prompts define ownership guidance, and `doctor` reports missing context-map targets plus malformed or duplicate ADR filenames.

Open work:

- If prompt size becomes an issue, include an ADR index plus role/task-relevant ADRs instead of all ADR text.
- Consider richer `doctor` checks for `CONTEXT.md` structure if agents start producing glossary/spec hybrids.

## 4. Starting Workflow on an Existing Project

Priority: medium. DevLab should support operation on a project developed outside DevLab.

In this case, the system spec acts as a feature spec. DevLab adds the specified features to the existing project using the same workflow it uses to develop from scratch. The architect and planner roles need to account for existing code and infrastructure rather than assuming a greenfield project.

## 5. DevLab Workflow Evaluations

Priority: medium-low. Add opt-in workflow evaluations that run DevLab on small target specifications and check observable behavior.

Direction:

- Build on the existing end-to-end `MockProvider` tests.
- Add deterministic scripted fake-agent scenarios that write canned role outputs for known specs without tokens.
- Keep live-agent evaluations separate from default tests.
- Use small specs with objective acceptance checks: CLI calculator, tiny API, smoke app.
- Grade generated systems with black-box checks: commands, HTTP responses, package builds, test suites.
- Record diagnostics: sessions used, findings created, review rejections, runtime, final artifacts.

## 6. Project Status Drift Detection

Priority: medium-low. DevLab should guard against project progress drifting from the design plan or system spec.

Simpler approach than git rollback: at milestone boundaries, the architect evaluates whether the implemented system still aligns with the design plan and system spec. If drift is detected, the architect flags it as a finding and the planner creates corrective tasks.

Defer rollback/re-plan unless the finding-based correction loop proves insufficient.

## 7. Deployment Specification and Verification

Priority: low. DevLab should support deployment requirements under `.devlab/specs/deployment/` and let the normal workflow plan, implement, review, and integrate deployment artifacts.

Required verification layers:

1. **Static/artifact validation** — build and inspect deployment artifacts without external infrastructure (docker build, image inspection, RPM build, systemd unit validation).
2. **Local ephemeral deployment** — run artifacts locally in disposable resources and smoke-test (docker run, compose tests, health checks, teardown via environment lifecycle).
3. **Disposable test infrastructure** — deploy to explicitly configured, isolated, non-production infrastructure and destroy after verification (temporary VM, disposable K8s namespace, test registry).

Constraints:

- DevLab verifies deployability; it does not deploy to production by default.
- Test infrastructure use must be explicit, allowlisted, isolated, and aggressively cleaned up.
- Deployment implementation remains task-based through the normal role workflow.

## 8. Automatic Version Control

Priority: low. DevLab should eventually commit repository state after completed sessions or workflow gates.

Open questions:

- Commit after every valid session, every task closure, or milestone integration?
- Should failed integration findings be committed automatically?
- How should commit messages be generated?
- How should dirty working tree state before a session be handled?
- Should DevLab use per-milestone feature branches? Current recommendation: defer branching; use tags first.

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator.
- Sandboxing or approval policy for executable environment lifecycle changes.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Multi-agent concurrent sessions.
- External task tracker backends.
- Full release/deployment automation.
