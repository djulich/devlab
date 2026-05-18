# DevLab TODOs / Features to be Implemented

Only open or partially complete work is listed here. Completed implementation-history items are removed once no follow-up remains.

---

## 1. Workflow Contract Hardening

Priority: high. Current unit and mock workflow tests are strong, but several workflow decisions still depend on loose Markdown/text parsing. Real agents are likely to produce ambiguous handoffs, stale review sections, or malformed task updates.

Open work:

- Make handoff parsing stricter: validate required section order/structure, not only heading presence.
- Tighten `## Open Issues` handling so text containing the word `none` inside a real issue is not treated as clean.
- Scope developer completion detection to task acceptance criteria instead of counting all checked/unchecked boxes in the file.
- Harden reviewer outcome detection against stale `## Review\n- [x] Approved` sections after a later rejection.
- Add tests for stale approvals, ambiguous Open Issues, malformed handoffs, and mixed `- None`/real content.
- Consider an explicit structured outcome block for reviewer/integrator/architect handoffs if Markdown parsing remains fragile.

## 2. Agent Invocation Observability and Error Handling

Priority: high. Provider invocation currently reports mostly exit codes. For real use, DevLab needs durable diagnostics when an agent fails, times out, or produces invalid output.

Open work:

- Capture agent stdout/stderr into `.devlab/logs/agents/` for every session.
- Convert provider subprocess timeouts into structured `SessionError` / `RunResult` failures.
- Include agent command, role, timeout, exit code, and log paths in failure reports.
- Prefer stdin-based prompt transport in starter configuration where supported, to avoid argv length limits and prompt leakage through process lists.
- Add tests for timeout, missing executable, nonzero exit, invalid handoff, and teardown-after-failure behavior.

## 3. DevLab Workflow Evaluations

Priority: high. Mock-provider tests validate orchestration mechanics but do not prove that real or realistic agents can complete useful target work.

Direction:

- Build on the existing end-to-end `MockProvider` tests.
- Add deterministic scripted fake-agent scenarios that write canned role outputs for known specs without tokens.
- Keep live-agent evaluations separate from default tests.
- Use small specs with objective acceptance checks: CLI calculator, tiny API, smoke app.
- Grade generated systems with black-box checks: commands, HTTP responses, package builds, test suites.
- Record diagnostics: sessions used, findings created, review rejections, runtime, final artifacts, and prompt sizes.

## 4. Package and User-Facing Documentation

Priority: high. DevLab is intended to be a reusable CLI/package, but the repository lacks a user-facing quickstart and maturity/trust guidance.

Open work:

- Add a top-level `README.md` with purpose, install instructions, quickstart, and command overview.
- Document `.devlab/` layout, profiles, agent config, findings, milestones, and handoffs at a user level.
- Document current maturity: tested orchestrator prototype, not yet proven by broad live-agent evaluations.
- Add or decide on license and release/versioning expectations.
- Decide whether the dogfood `.devlab/` state should model DevLab's own workflow or remain a starter/example workspace only.

## 5. Trust and Safety Model for Executable Configuration

Priority: high-medium. Target-owned `agents.toml` and profile environment lifecycle commands are trusted executable configuration. This needs to be explicit before broader reuse.

Open work:

- Document the trust boundary prominently in README/config docs and starter files.
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

## 10. Deployment Specification and Verification

Priority: low. DevLab should support deployment requirements under `.devlab/specs/deployment/` and let the normal workflow plan, implement, review, and integrate deployment artifacts.

Required verification layers:

1. **Static/artifact validation** — build and inspect deployment artifacts without external infrastructure (docker build, image inspection, RPM build, systemd unit validation).
2. **Local ephemeral deployment** — run artifacts locally in disposable resources and smoke-test (docker run, compose tests, health checks, teardown via environment lifecycle).
3. **Disposable test infrastructure** — deploy to explicitly configured, isolated, non-production infrastructure and destroy after verification (temporary VM, disposable K8s namespace, test registry).

Constraints:

- DevLab verifies deployability; it does not deploy to production by default.
- Test infrastructure use must be explicit, allowlisted, isolated, and aggressively cleaned up.
- Deployment implementation remains task-based through the normal role workflow.

## 11. Automatic Version Control

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
- Developer/reviewer-created findings; use task-native blockers and requested changes first.
- Multi-agent concurrent sessions.
- External task tracker backends.
- Full release/deployment automation.
