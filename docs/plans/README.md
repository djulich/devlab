# Plans

Plans capture design decisions and implementation strategies for DevLab features. Each plan is written before implementation and kept as reference afterward.

**Agents: treat implemented plans as historical context, not current instructions.** Only active plans describe work that remains to be done.

## Active

- [resilient-session-handoffs.md](resilient-session-handoffs.md) — structured submission and DevLab-owned publication are implemented; representative live-provider acceptance metrics remain to collect
- [architectural-improvements.md](architectural-improvements.md) — cross-cutting backlog for concurrency policy, typed validation failures, resolver isolation, and artifact bounds; stop semantics, blocker ordering, and atomic durable writes are implemented
- [durable-operator-clarifications.md](durable-operator-clarifications.md) — durable stop/answer/resume and bounded unattended resolution are implemented; scoped routing and external adapters remain optional

## Implemented

- [language-neutral-target-workspaces.md](language-neutral-target-workspaces.md) — added neutral initialization, explicit Python/Rust/Go/C/C++ starters, compiled-language evaluations, and a mixed Rust/Go baseline
- [run-stop-reasons-and-blocker-ordering.md](run-stop-reasons-and-blocker-ordering.md) — added explicit workflow/command/limit/blocker/ineligible/error outcomes and moved clarification blockers before ordinary role selection
- [workflow-state-reporting.md](workflow-state-reporting.md) — added an operator-facing lifecycle state command backed by durable workflow events and inference for older target workspaces
- [react-vite-browser-live-evaluation.md](react-vite-browser-live-evaluation.md) — added a Podman-isolated browser/dev-server/API integration check to the React/Vite live evaluation
- [generational-archive-reconciliation.md](generational-archive-reconciliation.md) — replaced in-place planning-generation filtering with archived generation bundles for spec reconciliation and existing-project adoption
- [spec-change-reconciliation.md](spec-change-reconciliation.md) — detect system/deployment spec changes after planning and require `devlab plan` reconciliation before implementation
- [orchestrator-owned-workflow-state.md](orchestrator-owned-workflow-state.md) — move `.devlab/workflow.toml` writes from planner agents to orchestrator-owned handoff processing
- [agent-invocation-observability-and-error-handling.md](agent-invocation-observability-and-error-handling.md) — AgentResult, per-session logs, SessionContext, structured error handling
- [failed-session-cleanup.md](failed-session-cleanup.md) — explicit cleanup command for untracked failed-session logs and artifacts
- [devlab-project-makefile.md](devlab-project-makefile.md) — source-checkout Makefile for validation and uv tool installation convenience
- [codebase-maintainability-for-agent-work.md](codebase-maintainability-for-agent-work.md) — doctor domain split and evaluation check extraction while keeping orchestrator/prompt policy cohesive
- [deployment-live-baseline-2026-06-06.md](deployment-live-baseline-2026-06-06.md) — initial live deployment evaluation baseline
- [stateful-web-api-live-baseline-2026-06-24.md](stateful-web-api-live-baseline-2026-06-24.md) — initial live stateful web API evaluation baseline
- [compiled-language-live-baseline-2026-08-20.md](compiled-language-live-baseline-2026-08-20.md) — Rust, Go, C, and C++ profile-verification baseline
- [devlab-cli-library-logging-facility.md](devlab-cli-library-logging-facility.md) — `_logging.py`, `configure_logging()`, `--log-file` flag
- [devlab-live-evaluation-quality-metrics.md](devlab-live-evaluation-quality-metrics.md) — role sequence, task cycles, artifact hygiene, quality summary diagnostics
- [devlab-workflow-evaluations.md](devlab-workflow-evaluations.md) — scripted and live evaluation infrastructure
- [devlab-workflow-evaluations-remaining.md](devlab-workflow-evaluations-remaining.md) — evaluation infrastructure refinements, diagnostics export
- [git-based-evaluation-hygiene.md](git-based-evaluation-hygiene.md) — artifact classification via git ls-files and check-ignore
- [incremental-milestone-planning.md](incremental-milestone-planning.md) — workflow.toml planning completeness state for follow-up planner sessions
- [orchestrator-quality-improvements.md](orchestrator-quality-improvements.md) — narrowed exception handling, session context extraction, session logging separation
- [stateful-web-api-evaluation.md](stateful-web-api-evaluation.md) — stateful web API scripted and live evaluation scenarios
- [workflow-contract-hardening.md](workflow-contract-hardening.md) — handoff parsing, validation, and contract enforcement
