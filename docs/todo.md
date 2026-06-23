# DevLab TODOs / Features to be Implemented

Only open or partially complete work is listed here. Completed implementation-history items are removed once no follow-up remains.

---

## 1. Workflow Contract Hardening

Status: **initial hardening implemented**. DevLab now validates handoff section order/structure, uses strict `- None` semantics, scopes developer completion to task acceptance criteria, rejects contradictory reviewer artifacts, and has focused tests for malformed/ambiguous handoffs.

Open work:

- Consider post-reviewer structural validation: the orchestrator runs profile-driven validation commands after the reviewer session and treats failure as a rejection regardless of the reviewer's approval. This moves mechanical correctness checking (tests pass, linter clean, types check) from prompt-dependent reviewer behavior to structural enforcement. The reviewer still owns subjective code quality judgment. Tradeoff: the reviewer can no longer deliberately approve with a known failing test, which is sometimes valid during incremental development.

## 2. DevLab Workflow Evaluations

Status: **evaluation harness implemented; live result collection ongoing**. Deterministic evaluations under `tests/evaluations/` create temporary target repositories, run the normal workflow with scripted fake agents, grade generated systems with black-box checks, and write diagnostics JSON artifacts. The suite includes CLI calculator, corrective workflow, tiny stdlib HTTP API, stateful JSON web API, static frontend, and deployable web API scenarios. Skipped-by-default live-agent evaluations reuse the same harness. Diagnostics now include task-cycle rework, integrator finding rework, profile usage, artifact hygiene, and quality warnings. See `docs/evaluations.md`, `docs/plans/devlab-workflow-evaluations.md`, `docs/plans/devlab-workflow-evaluations-remaining.md`, and `docs/plans/stateful-web-api-evaluation.md`.

Recommended evaluation roadmap:

1. **CLI calculator** — existing tiny baseline for workflow smoke coverage.
2. **Tiny stdlib HTTP API** — existing dependency-light server/runtime baseline.
3. **Stateful JSON web API** — implemented as a scripted scenario; exercises multi-file source, project-owned commands, docs, `.gitignore`, and black-box HTTP state transitions without third-party dependencies.
4. **Web API plus deployment artifacts** — local-container scripted/live scenarios and a scripted Compose scenario are implemented; add kind/RPM/systemd-style scenarios only when those deployment families become active priorities.
5. **Static frontend** — scripted and opt-in live scenarios are implemented for vanilla HTML/CSS/JS without Node/React dependency or browser-tooling volatility; next collect live baselines.
6. **React/Vite or full-stack frontend** — later, once dependency/profile handling and live-agent baselines are stable enough to justify the extra moving parts.

Open work:

- Run the opt-in `live-stateful-web-api-happy-path` evaluation across local provider environments and collect baseline outcomes.
- Run opt-in live-agent evaluations with the expanded quality metrics from `docs/plans/devlab-live-evaluation-quality-metrics.md` and collect additional baseline outcomes, especially `live-static-frontend-todo-app-happy-path` and additional `live-deployable-web-api-happy-path` runs across provider environments. Initial deployment baseline: `docs/plans/deployment-live-baseline-2026-06-06.md`.
- Calibrate quality-warning thresholds after more live baselines, especially high sessions per closed task, same-task rework warnings, integrator finding warnings, and large ignored artifact footprints.
- Decide from live baselines whether developer/reviewer task attribution from changed `.devlab/tasks/TXXXX_*.md` artifacts is sufficient, or whether fallback handoff parsing is needed.

## 3. Trust and Safety Model for Executable Configuration

Priority: high-medium. Target-owned `agents.toml` and profile environment lifecycle commands are trusted executable configuration. This needs to be explicit before broader reuse.

Status: **trust guidance documented**. README and operator docs now warn that DevLab runs target-owned agent/profile commands without sandboxing, describe ownership of generated workflow files, and call out `.gitignore`, logs, retained prompts, and automatic commits.

Open work:

- Add `doctor` warnings for obviously dangerous profile commands or permission-skip flags where practical.
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

## 6. Reconcile Spec Changes with Workflow State

Priority: medium-high. DevLab should support target workspaces where the system spec or deployment spec changes after architecture, planning, or implementation work already exists.

Status: **implemented with generation archives**. DevLab records committed spec baselines in `.devlab/workflow.toml`, archives the active workflow bundle under `.devlab/generations/NNNN/` during spec reconciliation, starts a fresh active planning graph, and blocks `devlab implement` when committed specs are unreconciled. See `docs/plans/generational-archive-reconciliation.md`.

Usefulness: high. This is a normal real-world workflow: requirements drift after plans and code exist. Without explicit support, DevLab may either keep executing stale tasks or require users to manually reset workflow state.

Open work:

- Consider a future explicit bypass command such as `devlab plan --mark-specs-planned` for operator-confirmed format-only, typo-only, or otherwise plan-neutral spec commits. The command would require a clean worktree, refuse uncommitted spec changes, update `[specs].last_planned_spec_commit` to the current latest committed spec commit without running architect/planner, and clearly warn that it bypasses the reconciliation guardrail. Do not add this to the first implementation unless real usage shows false-positive reconciliation is painful.
- Decide whether reconciliation should produce a separate durable summary artifact, or whether architect/planner handoffs plus edited plans/tasks are sufficient.

## 7. Add Durable Operator Clarifications

Priority: medium. DevLab should support bounded user clarification when a role session encounters an ambiguity, contradiction, missing prerequisite, or scope decision that cannot be resolved safely from repository state.

Usefulness: high, but only if tightly constrained. Clarification prevents agents from inventing requirements, but unconstrained back-and-forth would weaken bounded sessions and durable workflow state.

Expected behavior:

- A role session may request operator clarification instead of making an unsafe assumption.
- DevLab stops the workflow in a durable "needs clarification" state.
- The clarification request is stored in repository state with the asking role, session id, question, relevant context, and expected answer shape.
- The operator can answer through a CLI command or by editing a documented file.
- Once answered, DevLab resumes with the answer included in the next relevant role prompt.
- Clarifications become durable project knowledge when they affect requirements, scope, architecture, task definitions, or deployment expectations.

Open design questions:

- Should only architect/planner sessions be allowed to ask scope questions, while developer/reviewer/integrator surface blockers through task or finding state?
- What is the storage model: `.devlab/questions/`, findings, workflow state, or a new tracker?
- How should DevLab prevent vague or excessive questions: max question count per session, required answer options, severity, or validation rules?
- Should unanswered questions block all workflow progress or only the affected task/milestone?

## 8. Add Workflow Attention Notifications

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

## 9. Add Workflow State Reporting

Status: **initial implementation complete**. DevLab now writes a small
orchestrator-owned `.devlab/workflow-events.jsonl` lifecycle log, exposes
`devlab workflow-state [--json]`, reports lifecycle phase, planning/project
mode, generations, spec reconciliation, planning-history counters, and current
work counts, and falls back to generation manifests/session history for older
workspaces without events.

Priority: medium-high. Operators should be able to inspect a target project's
workflow lifecycle state without manually reading `.devlab/` artifacts, project
files, generation archives, or Git history.

Usefulness: high. This answers whether a target is greenfield or adopted,
whether design and planning have happened, whether specs are reconciled, how many
planning generations exist, and how often plan revision/reconciliation happened.

Plan: `docs/plans/workflow-state-reporting.md`.

Open work:

- Consider failed-attempt lifecycle events if successful-transition provenance
  proves insufficient.

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator beyond post-reviewer structural validation (see item 1).
- Sandboxing or approval policy for executable environment lifecycle changes.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Developer/reviewer-created findings; use task-native blockers and requested changes first.
- Multi-agent concurrent sessions.
- External task tracker backends.
- Full release/deployment automation.
