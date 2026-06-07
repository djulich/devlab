# Plans

Plans capture design decisions and implementation strategies for DevLab features. Each plan is written before implementation and kept as reference afterward.

**Agents: treat implemented plans as historical context, not current instructions.** Only active plans describe work that remains to be done.

## Active

None.

## Implemented

- [agent-invocation-observability-and-error-handling.md](agent-invocation-observability-and-error-handling.md) — AgentResult, per-session logs, SessionContext, structured error handling
- [devlab-project-makefile.md](devlab-project-makefile.md) — source-checkout Makefile for validation and uv tool installation convenience
- [codebase-maintainability-for-agent-work.md](codebase-maintainability-for-agent-work.md) — doctor domain split and evaluation check extraction while keeping orchestrator/prompt policy cohesive
- [deployment-live-baseline-2026-06-06.md](deployment-live-baseline-2026-06-06.md) — initial live deployment evaluation baseline
- [devlab-cli-library-logging-facility.md](devlab-cli-library-logging-facility.md) — `_logging.py`, `configure_logging()`, `--log-file` flag
- [devlab-live-evaluation-quality-metrics.md](devlab-live-evaluation-quality-metrics.md) — role sequence, task cycles, artifact hygiene, quality summary diagnostics
- [devlab-workflow-evaluations.md](devlab-workflow-evaluations.md) — scripted and live evaluation infrastructure
- [devlab-workflow-evaluations-remaining.md](devlab-workflow-evaluations-remaining.md) — evaluation infrastructure refinements, diagnostics export
- [git-based-evaluation-hygiene.md](git-based-evaluation-hygiene.md) — artifact classification via git ls-files and check-ignore
- [orchestrator-quality-improvements.md](orchestrator-quality-improvements.md) — narrowed exception handling, session context extraction, session logging separation
- [stateful-web-api-evaluation.md](stateful-web-api-evaluation.md) — stateful web API scripted and live evaluation scenarios
- [workflow-contract-hardening.md](workflow-contract-hardening.md) — handoff parsing, validation, and contract enforcement
