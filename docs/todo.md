# DevLab TODOs / Features to be Implemented

Only open or partially complete work is listed here. Completed implementation-history items are removed once no follow-up remains.

---

## 1. Workflow Contract Hardening

Status: **initial hardening implemented**. DevLab now validates handoff section order/structure, uses strict `- None` semantics, scopes developer completion to task acceptance criteria, rejects contradictory reviewer artifacts, and has focused tests for malformed/ambiguous handoffs.

Open work:

- Watch live-agent runs for remaining Markdown contract ambiguity.
- Keep planner addressed-findings validation strict until live evaluations show whether malformed mappings are common; see `docs/agent-output-validation-assessment.md`.
- Consider an explicit structured outcome block for reviewer/integrator/architect handoffs only if Markdown parsing remains fragile. This is not merely deferred implementation work: a structured block can create two-source-of-truth conflicts with prose, make agent output more brittle, impose a schema-evolution burden on archived handoffs, and tempt agents/orchestrator contracts toward over-specified workflow control. If added, keep it minimal and authoritative, and reject contradictions with prose.
- Consider post-reviewer structural validation: the orchestrator runs profile-driven validation commands after the reviewer session and treats failure as a rejection regardless of the reviewer's approval. This moves mechanical correctness checking (tests pass, linter clean, types check) from prompt-dependent reviewer behavior to structural enforcement. The reviewer still owns subjective code quality judgment. Tradeoff: the reviewer can no longer deliberately approve with a known failing test, which is sometimes valid during incremental development.

## 2. Agent Invocation Observability and Error Handling

Status: **initial implementation complete**. CLI providers now capture per-session stdout/stderr, convert timeout/missing executable/nonzero exit/provider errors into structured `AgentResult` values, and the orchestrator includes log paths and invocation diagnostics in `SessionError` / `RunResult` failures. Starter config and docs prefer stdin prompt transport where supported.

Open work:

- Exercise diagnostics in live-agent runs and refine message wording if users need faster failure triage.
- Decide whether to persist additional non-prompt invocation metadata such as duration and provider-specific version info.

## 3. DevLab Workflow Evaluations

Status: **evaluation harness implemented; live result collection ongoing**. Deterministic evaluations under `tests/evaluations/` create temporary target repositories, run the normal workflow with scripted fake agents, grade generated systems with black-box checks, and write diagnostics JSON artifacts. The suite includes CLI calculator, corrective workflow, tiny stdlib HTTP API, stateful JSON web API, static frontend, and deployable web API scenarios. Skipped-by-default live-agent evaluations reuse the same harness. Diagnostics now include task-cycle rework, integrator finding rework, profile usage, artifact hygiene, and quality warnings. See `docs/evaluations.md`, `docs/plans/devlab-workflow-evaluations.md`, `docs/plans/devlab-workflow-evaluations-remaining.md`, and `docs/plans/stateful-web-api-evaluation.md`.

Recommended evaluation roadmap:

1. **CLI calculator** — existing tiny baseline for workflow smoke coverage.
2. **Tiny stdlib HTTP API** — existing dependency-light server/runtime baseline.
3. **Stateful JSON web API** — implemented as a scripted scenario; exercises multi-file source, project-owned commands, docs, `.gitignore`, and black-box HTTP state transitions without third-party dependencies.
4. **Web API plus deployment artifacts** — initial local-container scripted/live scenarios are implemented with exact `image` and `deployment-check` command contracts; next expand to Compose/kind/RPM-style project-owned artifacts and verification after collecting live baselines.
5. **Static frontend** — scripted and opt-in live scenarios are implemented for vanilla HTML/CSS/JS without Node/React dependency or browser-tooling volatility; next collect live baselines.
6. **React/Vite or full-stack frontend** — later, once dependency/profile handling and live-agent baselines are stable enough to justify the extra moving parts.

Open work:

- Run the opt-in `live-stateful-web-api-happy-path` evaluation across local provider environments and collect baseline outcomes.
- Run opt-in live-agent evaluations with the expanded quality metrics from `docs/plans/devlab-live-evaluation-quality-metrics.md` and collect additional baseline outcomes, including `live-static-frontend-todo-app-happy-path` and `live-deployable-web-api-happy-path` across local provider environments.
- Calibrate quality-warning thresholds after more live baselines, especially high sessions per closed task, same-task rework warnings, integrator finding warnings, and large ignored artifact footprints.
- Watch whether developer/reviewer task attribution from changed `.devlab/tasks/TXXXX_*.md` artifacts is sufficient in live runs; only add fallback parsing if real handoffs are frequently unattributed.
- Refine diagnostics/message wording if live failures are hard to triage.

## 4. Package and User-Facing Documentation

Priority: high. DevLab is intended to be a reusable CLI/package, but the repository lacks a user-facing quickstart and maturity/trust guidance.

Open work:

- Expand user-level documentation for profiles, findings, milestones, and handoffs beyond the top-level README.
- Keep maturity guidance current as live-agent evaluation baselines accumulate.
- Add or decide on license and release/versioning expectations.
- Decide whether the dogfood `.devlab/` state should model DevLab's own workflow or remain a starter/example workspace only.

## 5. Trust and Safety Model for Executable Configuration

Priority: high-medium. Target-owned `agents.toml` and profile environment lifecycle commands are trusted executable configuration. This needs to be explicit before broader reuse.

Open work:

- Add `doctor` warnings for obviously dangerous profile commands or permission-skip flags where practical.
- Clarify that DevLab does not sandbox agent commands or environment lifecycle commands.
- Consider a future workspace trust marker or explicit `--allow-exec-config` mode before running target-owned executable config.
- Keep sandboxing/approval policy as a deferred feature unless real use shows it is necessary sooner.

## 6. Prompt Context Size Monitoring and Reduction

Status: **initial monitoring implemented**. DevLab estimates system, session, and total prompt size per role using the actual prompt builders. `devlab status --verbose` reports approximate token counts and threshold status. Thresholds are configurable in `.devlab/config/agents.toml`; `devlab doctor` validates the configuration.

Open work:

- Add prompt reduction strategies for oversized contexts: summarize profile listings, limit historical handoffs, include only relevant tasks/findings, and include only role-relevant convention sections.
- Include an ADR index plus role/task-relevant ADRs instead of all ADR text when knowledge grows.
- Consider splitting `conventions.md` into role-relevant sections.
- Consider model-specific tokenizers or provider-specific context windows if approximate sizing proves insufficient.

## 7. Durable Project Knowledge: CONTEXT.md and ADRs

Status: **initial implementation complete**. DevLab discovers target-owned `CONTEXT.md`, `CONTEXT-MAP.md`, linked context files, and `docs/adr/*.md` without mutating the workspace. Discovered knowledge is included in role prompts, prompt size reporting accounts for it, role prompts define ownership guidance, and `doctor` reports missing context-map targets plus malformed or duplicate ADR filenames.

Open work:

- Consider richer `doctor` checks for `CONTEXT.md` structure if agents start producing glossary/spec hybrids.
- Evaluate whether multi-context `CONTEXT-MAP.md` discovery needs role/task relevance filtering as projects grow.

## 8. Starting Workflow on an Existing Project

Priority: medium. DevLab should support operation on a project developed outside DevLab.

In this case, the system spec acts as a feature spec. DevLab adds the specified features to the existing project using the same workflow it uses to develop from scratch. The architect and planner roles need to account for existing code and infrastructure rather than assuming a greenfield project.

Open work:

- Add an explicit adopt-existing-project prompt path or workflow mode.
- Have the architect create a current-state design baseline before planning new work.
- Include repository inspection guidance for existing source, tests, packaging, deployment, and tooling.
- Add evaluations using a pre-existing tiny repo plus a feature spec.

## 9. Workspace API Consistency

Priority: medium. The workspace boundary is useful, but some APIs still expose raw trackers or broad convenience methods that could drift from the intended handle-based mutation model.

Open work:

- Prefer first-class domain handles for mutations, e.g. `workspace.findings().create_from_handoff(...)` rather than broad `Workspace.create_finding_from_handoff(...)`.
- Consider making raw tracker access internal or clearly documented as lower-level infrastructure.
- Keep multi-step workflow policy visible in `orchestrator.py`; handles should expose atomic domain transitions only.
- Add tests that discourage direct parsing/mutation outside tracker/workspace boundaries.

## 10. Codebase Maintainability for Agent Work

Priority: medium. Keep modules scoped so an agent can work on one topic without loading unrelated workflow, prompt, evaluation, and CLI details into context. The evaluation harness has been split so black-box checks live in `tests/evaluations/checks.py`, while reusable workflow metrics live in production code under `src/devlab/workflow_diagnostics.py`.

Open work:

- Consider extracting orchestrator session execution, handoff processing, and Git commit/tag policy into smaller internal modules if `src/devlab/orchestrator.py` grows further. Keep the public workflow loop in `orchestrator.py`.
- Consider splitting `src/devlab/doctor.py` by validation domain if more checks are added for deployment, trust/safety, or prompt context.
- Consider splitting large scripted evaluation agents by scenario family if future scenarios make `tests/evaluations/scripted_agents.py` harder to scan.
- Keep prompt assembly helpers grouped by role/domain; if `src/devlab/prompts.py` grows, extract profile/domain formatting without moving workflow decisions into prompt construction.

## 11. Deployment Specification and Verification

Status: **foundation implemented; verification/evaluation work remains**. DevLab now initializes a richer deployment spec template, supports primary task domains (`general` by default, `deployment` for deployment work), and adds role-specific deployment prompt overlays from `src/devlab/resources/prompts/domains/deployment/<role>.md` without changing the core workflow roles. Developer/reviewer prompts use the assigned task domain; architect/planner prompts use deployment overlays when deployment specs contain substantive requirements; integrator prompts use deployment overlays for deployment-domain milestone work. See `docs/deployment-feature-overview.md` and `docs/plans/deployment-specification-and-verification.md`.

Required verification layers remain:

1. **Static/artifact validation** — build and inspect deployment artifacts without external infrastructure (docker build, image inspection, RPM build, systemd unit validation).
2. **Local ephemeral deployment** — run artifacts locally in disposable resources and smoke-test (docker run, compose tests, health checks, teardown via environment lifecycle).
3. **Disposable test infrastructure** — deploy to explicitly configured, isolated, non-production infrastructure and destroy after verification (temporary VM, disposable K8s namespace, test registry).

Constraints:

- DevLab verifies deployability; it does not deploy to production by default.
- `devlab run` does not need to leave the target system running, but claimed deployment artifacts must be generatable and testable during the workflow.
- Finished projects should expose project-owned deployment commands, such as Make targets or scripts, for local and disposable/staging environments.
- Test infrastructure use must be explicit, allowlisted, isolated, and aggressively cleaned up.
- Deployment implementation remains task-based through the normal role workflow.

Open work:

- Add deterministic workflow evaluations proving deployment-domain tasks produce project-owned deployment artifacts, commands, docs, and verification evidence.
- Add at least one opt-in live-agent deployment evaluation, likely starting with container runtime or Compose before Kubernetes/kind or RPM/systemd.
- Decide whether profile validation commands need structured first-class modeling, or whether prompt-guided project-owned commands are sufficient initially.
- Add non-mutating `doctor`/diagnostic checks for deployment specs, unknown task domains, and optionally deployment tool availability.
- Expand verification from structural checks toward safe static/artifact validation where host tools are available.

## 12. Automatic Version Control

Status: **initial implementation complete**. `devlab init` initializes Git when needed, configures a usable identity from CLI flags, existing Git config, or DevLab defaults, and creates an initial commit. Existing Git repositories must be clean before init so DevLab does not mix user changes with bootstrap state. `devlab run` requires a Git repository with a clean working tree, commits all non-ignored changes after every valid session, and creates `devlab/milestone/<milestone-id>` tags when milestones are integrated. Failed integration findings are committed like any other valid session. Agents may provide an optional `## Commit Message` handoff section with a one-line description; the orchestrator adds the task/role prefix and falls back to task/role-derived messages when the section is absent.

Open work:

- Decide how to handle sensitive logs/prompts and other non-ignored data before broader use; the current implementation commits everything Git considers relevant.
- Consider commit message bodies if one-line summaries prove insufficient.
- Defer per-milestone feature branches; use milestone tags first.

## 13. Multi-session Architecture Planning for Large Specs

Priority: medium-low. Useful for substantial target systems where one architect session cannot produce a reliable design plan, but lower priority until workflow evaluations show concrete context or quality failures on large specs.

Open work:

- Define a durable partial-design state so the architect can stop safely before a complete design plan exists.
- Let architect sessions explicitly report whether the design plan is complete or needs another architecture-planning session.
- Avoid overloading implementation tasks for pre-planning work; if design slices are needed, store them as architecture-planning artifacts rather than normal developer tasks.
- Add tests/evaluations with an intentionally large spec that requires multiple architecture passes.

## 14. DevLab CLI and Library Logging Facility

Status: **initial implementation complete**. DevLab now uses Python's standard `logging` module with a single `devlab` logger for workflow progress/errors, while `init`, `status`, `doctor`, and interactive handoff previews remain direct user output. `devlab run` supports `--quiet`, `--verbose`, and `--log-file`; file logs capture DEBUG diagnostics. This complements, but does not replace, agent stdout/stderr capture in Agent Invocation Observability.

Open work:

- Exercise logging output during live-agent runs and refine message levels/wording if users need clearer diagnostics.
- Consider a future `--log-level LEVEL` or structured/JSON log format only if shorthand verbosity and plain text prove insufficient.

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator beyond post-reviewer structural validation (see item 1).
- Sandboxing or approval policy for executable environment lifecycle changes.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Developer/reviewer-created findings; use task-native blockers and requested changes first.
- Multi-agent concurrent sessions.
- External task tracker backends.
- Full release/deployment automation.
