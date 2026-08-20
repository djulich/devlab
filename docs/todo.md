# DevLab TODOs / Features to be Implemented

Only open or partially complete work is listed here. Completed implementation-history items are removed once no follow-up remains.

---

## 1. Workflow Contract Hardening

Status: **contract hardening implemented; live calibration remains**. DevLab validates handoff contracts and task work packets, preserves bounded task recovery with graded task outcomes, strictly gates configured milestone validation, records milestone verification facts separately from role judgment, and reports safe validation stops without installing host prerequisites.

Implementation continuation: [`plans/workflow-contract-hardening-remaining.md`](plans/workflow-contract-hardening-remaining.md). That plan treats `plans/unattended-workflow-progress-and-rework.md` as the governing policy wherever the older workflow-contract plan overlaps or conflicts.

Open work:

- Continue calibrating semantic task-quality checks from live evidence. Structural work-packet checks are enforced before developer invocation; the conjunction-based compound-criterion warning was retired after live use showed poor precision. Do not add another prose heuristic without labeled evidence. Reference: GSD [Plan a phase](https://github.com/open-gsd/gsd-core/blob/next/docs/how-to/plan-a-phase.md).

## 2. DevLab Workflow Evaluations

Status: **evaluation harness implemented; live result collection ongoing**. Deterministic evaluations under `tests/evaluations/` create temporary target repositories, run the normal workflow with scripted fake agents, grade generated systems with black-box checks, and write diagnostics JSON artifacts. The suite includes CLI calculator, corrective workflow, tiny stdlib HTTP API, stateful JSON web API, static frontend, and deployable web API scenarios. Skipped-by-default live-agent evaluations reuse the same harness. Diagnostics now include task-cycle rework, integrator finding rework, profile usage, artifact hygiene, and quality warnings. See `docs/evaluations.md`, `docs/plans/devlab-workflow-evaluations.md`, `docs/plans/devlab-workflow-evaluations-remaining.md`, and `docs/plans/stateful-web-api-evaluation.md`.

Recommended evaluation roadmap:

1. **CLI calculator** — existing tiny baseline for workflow smoke coverage.
2. **Tiny stdlib HTTP API** — existing dependency-light server/runtime baseline.
3. **Stateful JSON web API** — implemented as a scripted scenario; exercises multi-file source, project-owned commands, docs, `.gitignore`, and black-box HTTP state transitions without third-party dependencies.
4. **Web API plus deployment artifacts** — local-container scripted/live scenarios and a scripted Compose scenario are implemented; add kind/RPM/systemd-style scenarios only when those deployment families become active priorities.
5. **Static frontend** — scripted and opt-in live scenarios are implemented for vanilla HTML/CSS/JS without Node/React dependency or browser-tooling volatility; next collect live baselines.
6. **React/Vite frontend** — opt-in live scenario is implemented for a framework-based frontend with Podman-isolated npm install/build and browser/API/Vite integration checks; collect live baselines before expanding into visual quality or production deployment checks.
7. **Compiled-language profiles** — opt-in Rust, Go, C, and C++/CMake live scenarios exercise operator-provided toolchains, dedicated task profiles, inherited validation, and target-owned black-box behavior. The completed four-language baseline is recorded in `docs/plans/compiled-language-live-baseline-2026-08-20.md`; add broader toolchain variants only when they exercise distinct uncovered behavior.

Open work:

- Run the opt-in `live-stateful-web-api-happy-path` evaluation across any remaining local provider environments. Passing Claude and Codex baselines: `docs/plans/stateful-web-api-live-baseline-2026-06-24.md`.
- Run opt-in live-agent evaluations with the expanded quality metrics from `docs/plans/devlab-live-evaluation-quality-metrics.md` and collect additional baseline outcomes, especially `live-static-frontend-todo-app-happy-path` and additional `live-deployable-web-api-happy-path` runs across provider environments. Initial deployment baseline: `docs/plans/deployment-live-baseline-2026-06-06.md`.
- Collect initial outcomes for `live-react-vite-todo-app-happy-path` once at least one local provider environment is ready for a Node-project generation run.
- Calibrate remaining quality-warning thresholds after more live baselines, especially high sessions per closed task, same-task rework warnings, and integrator finding warnings. Ignored-artifact warnings now exclude conventional dependency environments and tool caches while retaining their totals as information.

## 3. Trust and Safety Model for Executable Configuration

Priority: high-medium. Target-owned `agents.toml` and profile environment lifecycle commands are trusted executable configuration. This needs to be explicit before broader reuse.

Status: **initial trust model implemented**. README and operator docs warn that
DevLab runs target-owned agent/profile commands without sandboxing. DevLab
treats provider-native permission policy as opaque and operator-owned. Executing
CLI commands fingerprint and freeze canonical provider/profile executable
configuration. Operators can approve a workspace/config/digest in user-local
state, require an independently approved digest in CI, or explicitly accept the
current snapshot for one externally contained invocation. Session and smoke-test
metadata record the digest and authorization source.

DevLab also records direct dependencies introduced by normal role sessions for
supported Python, Node, Rust, and Go manifests. Diagnostics and structured run
summaries report these as advisory operator-review warnings with session/task
provenance; they do not query registries, install tools, or block workflow
progress. See `plans/dependency-introduction-diagnostics.md`.

Open work:

- Calibrate dependency-introduction warning precision from live use before adding
  more manifests, constraint-change reporting, registry verification, or any
  blocking policy. Reference: GSD [Security model](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/security-model.md).
- Consider administrator-managed organization policy or optional OS sandboxing only when concrete deployment requirements justify their cross-platform complexity.

## 4. Prompt Context Size Monitoring and Reduction

Status: **initial monitoring implemented**. DevLab estimates system, session, and total prompt size per role using the actual prompt builders. `devlab status --verbose` reports approximate token counts and threshold status. Thresholds are configurable in `.devlab/config/agents.toml`; `devlab doctor` validates the configuration.

Open work:

- Add prompt reduction strategies for oversized contexts: summarize profile listings, limit historical handoffs, include only relevant tasks/findings, and include only role-relevant convention sections.
- Include an ADR index plus role/task-relevant ADRs instead of all ADR text when knowledge grows.
- Consider splitting `conventions.md` into role-relevant sections.
- Consider model-specific tokenizers or provider-specific context windows if approximate sizing proves insufficient.

## 5. Multi-session Architecture Planning for Large Specs

Priority: medium-low. Useful for substantial target systems where one architect session cannot produce a reliable design plan, but lower priority until workflow evaluations show concrete context or quality failures on large specs.

Open work:

- Define a durable partial-design state so the architect can stop safely before a complete design plan exists.
- Let architect sessions explicitly report whether the design plan is complete or needs another architecture-planning session.
- Avoid overloading implementation tasks for pre-planning work; if design slices are needed, store them as architecture-planning artifacts rather than normal developer tasks.
- Add tests/evaluations with an intentionally large spec that requires multiple architecture passes.

## 6. Durable Operator Clarifications

Priority: medium. DevLab supports bounded user clarification when a role session
encounters an ambiguity, contradiction, missing prerequisite, or scope decision
that cannot be resolved safely from repository state.

Status: **durable clarification workflow and unattended resolver implemented**.
DevLab has `.devlab/clarifications/` records, structured candidates for one
bounded clarification request, `[resume]` workflow state, CLI
list/show/answer/supersede/resume commands, same-route resume validation, prompt
inclusion, read-only status/doctor/workflow-state reporting, diagnostics metrics,
and an opt-in bounded resolver through `--unattended`.

Usefulness: high, but only if tightly constrained. Clarification prevents agents from inventing requirements, but unconstrained back-and-forth would weaken bounded sessions and durable workflow state.

GSD's `Discuss` step is a useful nearby pattern: capture implementation decisions before planning so the planner does not guess about libraries, error handling, UI behavior, or edge cases. DevLab should integrate that idea as bounded durable clarifications and planning decisions, not as an open-ended conversational phase. Reference: GSD [The phase loop](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/the-phase-loop.md).

Implemented behavior:

- A role session may request operator clarification instead of making an unsafe assumption.
- DevLab stops the workflow in a durable "needs clarification" state.
- The clarification request is stored in repository state with the asking role, session id, question, relevant context, and expected answer shape.
- The operator can answer through a CLI command or by editing a documented file.
- Once answered and resumed, DevLab includes the answer in the next relevant
  role prompt.
- Clarifications become durable project knowledge when they affect requirements, scope, architecture, task definitions, or deployment expectations.
- Unattended mode uses a separate bounded resolver session, records its answer
  with agent provenance, and resumes through the same durable route.

Open follow-up work:

- Add narrower task/milestone-scoped blocking after more real usage; the initial behavior conservatively blocks top-level workflow continuation for pending blocking clarifications.
- Add optional editor-mode clarification answering.
- Decide whether stable task/finding `decision_refs` metadata is needed so tasks,
  findings, and milestone verification can reference clarification decisions
  without duplicating prose.
- Consider Git-aware resolver edit isolation or temporary worktrees only if live
  usage shows whole-workspace snapshots are too expensive or insufficiently
  contained.

## 7. Add Workflow Attention Notifications

Priority: medium-low. DevLab should optionally notify operators about workflow events that require attention or indicate completion, especially for long-running unattended `devlab plan` / `devlab implement` workflows.

Usefulness: medium. Notifications are valuable once workflows run unattended for multiple sessions, but they should remain optional plumbing and not become part of workflow correctness.

Important events:

- Workflow stopped successfully.
- Workflow stopped with an error.
- Workflow stopped because no eligible task can proceed.
- Workflow stopped because operator clarification is required.
- Optional later events: session started, session completed, task closed, finding opened, milestone integrated.

Expected behavior:

- Notification configuration lives in target-owned DevLab config.
- Notification sending happens outside role prompts and agent providers.
- Failed notification delivery does not change workflow state or make a successful run fail by default.
- Messages include target workspace, command, final status, session count, next required action, and relevant log/artifact paths.
- Initial implementation should support a simple local notification mechanism or webhook before provider-specific email/Slack integrations.

Open design questions:

- Which channels should be first-class: stdout summary only, local command hook, webhook, email SMTP, Slack webhook?
- Should notification secrets live outside the target workspace while non-secret routing config lives inside it?
- Should notifications be sent synchronously at the end of the command or queued/best-effort?
- How should notification failures be reported without obscuring the primary workflow result?

## 8. Server/API Operator Interface

Priority: low. DevLab may eventually run as a long-lived service exposing APIs for starting workflows, inspecting state, answering clarifications, receiving notifications, and resuming blocked workflows.

Do not implement this until the CLI workflow surface is stable. Near-term work should only preserve the architectural boundary: core workflow operations must remain callable without assuming an interactive terminal, and operator interfaces such as CLI, editor, REST API, webhooks, email, or a web UI should be adapters over durable repository-backed workflow state.

Design pressure:

- Keep the repository-backed workflow model authoritative.
- Keep workflow mutations behind trackers, `Workspace` handles, and orchestrator-owned state transitions.
- Return structured operation results from reusable workflow functions instead of relying only on terminal output.
- Keep CLI commands thin enough that future server/API handlers can call the same operations.
- Do not let external adapters bypass clarification validation, resume semantics, spec reconciliation guards, or planning/implementation command boundaries.

## 9. Durable Research Sessions

Priority: medium-high. Status: **implemented**. Architect, planner, and developer
can request one bounded researcher session, persist a validated evidence-backed
result with provenance, and resume the exact requesting route.

Research resolves discoverable facts; clarification obtains operator intent.
The researcher must not directly mutate specifications, plans, tasks, ADRs,
dependencies, product files, or workflow transitions. The resumed software role
decides how the result affects its work.

Implementation plan: [`plans/durable-research-sessions.md`](plans/durable-research-sessions.md).

Implemented evidence includes strict request/result schemas, requesting-role
provider fallback, mutation isolation, retryable failures, route validation,
read-only reporting/doctor/diagnostics/prompt sizing, lifecycle events, and a
deterministic request-to-ordinary-completion evaluation. Follow-ups require live
evidence: cancellation/abandonment, reviewer/integrator eligibility, historical
indexes, or a second workflow justifying shared kernel extraction.

The first implementation must remain a concrete DevLab software-workflow
capability. It should distinguish potentially reusable subordinate-session
mechanics from research result semantics and software-specific policy, but must
not extract a generic kernel until a second workflow demonstrates shared
semantics.

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator beyond post-reviewer structural validation (see item 1).
- Sandboxing or approval policy for executable environment lifecycle changes.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Developer/reviewer-created findings; use task-native blockers and requested changes first.
- Multi-agent concurrent sessions.
- External task tracker backends.
- Full release/deployment automation.
