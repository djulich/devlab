# DevLab TODOs / Features to be Implemented

Only open or partially complete work is listed here. Completed implementation-history items are removed once no follow-up remains.

---

## 1. Workflow Contract Hardening

Status: **initial hardening implemented**. DevLab now validates handoff section order/structure, uses strict `- None` semantics, scopes developer completion to task acceptance criteria, rejects contradictory reviewer artifacts, and has focused tests for malformed/ambiguous handoffs.

Open work:

- Add orchestrator-owned validation enforcement with different task and milestone semantics. At task level, DevLab should infer validation requirements from task `validation` metadata and resolved profile defaults, run known commands when configured, record outcomes, and warn on missing mechanical validation without immediately making every approved task a hard gate. At milestone level, validation should be much stricter: before marking a milestone integrated, the orchestrator should require configured validation to pass or create integration findings for explicit gaps. This keeps task iteration flexible while making milestone acceptance a real repository-state gate.
- Add a pre-execution task quality gate before developer sessions. Inspired by GSD's plan-checking loop, DevLab could structurally validate that planned tasks have concrete acceptance criteria, valid dependencies, coherent milestone/profile metadata, and no vague "align/improve/handle properly" work statements before they become actionable. This should start as code-level validation over `.devlab/tasks/`, not as a new role. Reference: GSD [Plan a phase](https://github.com/open-gsd/gsd-core/blob/next/docs/how-to/plan-a-phase.md).
- Add an orchestrator-owned structured milestone verification record generated from DevLab facts plus narrow integrator/architecture-review judgment sections. The record should distinguish validation commands run, acceptance criteria or behavior checked, requirements/decisions covered, behavior that is claimed but untested, and findings opened for gaps without asking agents to duplicate task lists, command results, or other facts DevLab already owns. This is the DevLab-shaped version of GSD's post-execution verification idea, without adding a separate verifier role. References: GSD [The phase loop](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/the-phase-loop.md) and [Planning artifacts](https://github.com/open-gsd/gsd-core/blob/next/docs/reference/planning-artifacts.md).

## 2. DevLab Workflow Evaluations

Status: **evaluation harness implemented; live result collection ongoing**. Deterministic evaluations under `tests/evaluations/` create temporary target repositories, run the normal workflow with scripted fake agents, grade generated systems with black-box checks, and write diagnostics JSON artifacts. The suite includes CLI calculator, corrective workflow, tiny stdlib HTTP API, stateful JSON web API, static frontend, and deployable web API scenarios. Skipped-by-default live-agent evaluations reuse the same harness. Diagnostics now include task-cycle rework, integrator finding rework, profile usage, artifact hygiene, and quality warnings. See `docs/evaluations.md`, `docs/plans/devlab-workflow-evaluations.md`, `docs/plans/devlab-workflow-evaluations-remaining.md`, and `docs/plans/stateful-web-api-evaluation.md`.

Recommended evaluation roadmap:

1. **CLI calculator** — existing tiny baseline for workflow smoke coverage.
2. **Tiny stdlib HTTP API** — existing dependency-light server/runtime baseline.
3. **Stateful JSON web API** — implemented as a scripted scenario; exercises multi-file source, project-owned commands, docs, `.gitignore`, and black-box HTTP state transitions without third-party dependencies.
4. **Web API plus deployment artifacts** — local-container scripted/live scenarios and a scripted Compose scenario are implemented; add kind/RPM/systemd-style scenarios only when those deployment families become active priorities.
5. **Static frontend** — scripted and opt-in live scenarios are implemented for vanilla HTML/CSS/JS without Node/React dependency or browser-tooling volatility; next collect live baselines.
6. **React/Vite frontend** — opt-in live scenario is implemented for a framework-based frontend with Podman-isolated npm install/build and browser/API/Vite integration checks; collect live baselines before expanding into visual quality or production deployment checks.

Open work:

- Run the opt-in `live-stateful-web-api-happy-path` evaluation across any remaining local provider environments. Passing Claude and Codex baselines: `docs/plans/stateful-web-api-live-baseline-2026-06-24.md`.
- Run opt-in live-agent evaluations with the expanded quality metrics from `docs/plans/devlab-live-evaluation-quality-metrics.md` and collect additional baseline outcomes, especially `live-static-frontend-todo-app-happy-path` and additional `live-deployable-web-api-happy-path` runs across provider environments. Initial deployment baseline: `docs/plans/deployment-live-baseline-2026-06-06.md`.
- Collect initial outcomes for `live-react-vite-todo-app-happy-path` once at least one local provider environment is ready for a Node-project generation run.
- Calibrate quality-warning thresholds after more live baselines, especially high sessions per closed task, same-task rework warnings, integrator finding warnings, and large ignored artifact footprints.
- Decide from live baselines whether developer/reviewer task attribution from changed `.devlab/tasks/TXXXX_*.md` artifacts is sufficient, or whether fallback handoff parsing is needed.

## 3. Trust and Safety Model for Executable Configuration

Priority: high-medium. Target-owned `agents.toml` and profile environment lifecycle commands are trusted executable configuration. This needs to be explicit before broader reuse.

Status: **trust guidance documented**. README and operator docs now warn that DevLab runs target-owned agent/profile commands without sandboxing, describe ownership of generated workflow files, and call out `.gitignore`, logs, retained prompts, and automatic commits.

Open work:

- Add `doctor` warnings for obviously dangerous profile commands or permission-skip flags where practical.
- Consider dependency-introduction warnings for tasks or plans that add new package-manager dependencies, especially when the package name comes from agent output rather than an existing target convention. This should be lighter than GSD's full package-legitimacy gate at first: report unverified dependency additions and point operators at registry/source review rather than trying to install new host security tooling. Reference: GSD [Security model](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/security-model.md).
- Consider a future workspace trust marker or explicit `--allow-exec-config` mode before running target-owned executable config.

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

## 6. Add Durable Operator Clarifications

Priority: medium. DevLab should support bounded user clarification when a role session encounters an ambiguity, contradiction, missing prerequisite, or scope decision that cannot be resolved safely from repository state.

Usefulness: high, but only if tightly constrained. Clarification prevents agents from inventing requirements, but unconstrained back-and-forth would weaken bounded sessions and durable workflow state.

GSD's `Discuss` step is a useful nearby pattern: capture implementation decisions before planning so the planner does not guess about libraries, error handling, UI behavior, or edge cases. DevLab should integrate that idea as bounded durable clarifications and planning decisions, not as an open-ended conversational phase. Reference: GSD [The phase loop](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/the-phase-loop.md).

Expected behavior:

- A role session may request operator clarification instead of making an unsafe assumption.
- DevLab stops the workflow in a durable "needs clarification" state.
- The clarification request is stored in repository state with the asking role, session id, question, relevant context, and expected answer shape.
- The operator can answer through a CLI command or by editing a documented file.
- Once answered, DevLab resumes with the answer included in the next relevant role prompt.
- Clarifications become durable project knowledge when they affect requirements, scope, architecture, task definitions, or deployment expectations.
- Answered clarifications that constrain future implementation should get stable references so tasks, findings, and milestone verification can point at them without duplicating prose.

Open design questions:

- Should only architect/planner sessions be allowed to ask scope questions, while developer/reviewer/integrator surface blockers through task or finding state?
- What is the storage model: `.devlab/questions/`, findings, workflow state, or a new tracker?
- How should DevLab prevent vague or excessive questions: max question count per session, required answer options, severity, or validation rules?
- Should unanswered questions block all workflow progress or only the affected task/milestone?
- Should DevLab add optional requirement/decision traceability metadata to tasks, such as `addresses_requirements` and `decision_refs`, so milestone verification can check coverage structurally?

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

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator beyond post-reviewer structural validation (see item 1).
- Sandboxing or approval policy for executable environment lifecycle changes.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Developer/reviewer-created findings; use task-native blockers and requested changes first.
- Multi-agent concurrent sessions.
- External task tracker backends.
- Full release/deployment automation.
