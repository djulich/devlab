# DevLab Workflow Evaluations Plan

Status: initial scripted evaluations implemented. Deterministic scenarios now live under `tests/evaluations/`; live-agent evaluations and a tiny HTTP/API scenario remain future work.

## Goal

Implement TODO #3 by adding a repeatable evaluation harness that tests whether DevLab can drive realistic target-project work, not just internal orchestration mechanics.

The evaluation system should answer:

- Can scripted realistic agents complete small target specs through the full DevLab workflow?
- What workflow paths fail before useful software is produced?
- How many sessions, rejections, findings, and prompt tokens are required?
- Can optional live-agent runs complete the same scenarios without making default tests slow, costly, or nondeterministic?

## Success criteria

- Default `uv run pytest` remains fast, deterministic, and token-free.
- Deterministic workflow evaluations run against temporary target repositories and verify final software with black-box checks.
- Live-agent evaluations are opt-in and excluded from default tests.
- Each evaluation records diagnostics: scenario id, provider mode, sessions used, final `RunResult`, role sequence, findings created/resolved, reviewer rejections, runtime, prompt sizes, key artifact paths, and black-box check results.
- Evaluation scenarios cover at least:
  - a tiny CLI calculator
  - a tiny HTTP/API app or smoke app
  - a corrective path with reviewer rejection or integration finding
- Evaluation code reuses normal DevLab public/near-public workflow entry points (`init_workspace`, `run_loop`, configured providers) instead of special orchestration shortcuts.

## Non-goals

- Do not make live-agent evaluations part of default CI.
- Do not add token-consuming tests without an explicit opt-in flag/environment variable.
- Do not build a full benchmark suite or leaderboard.
- Do not introduce a new workflow engine for evaluations.
- Do not mutate the dogfood `.devlab/` workspace; all evaluations use temporary target repositories.
- Do not rely on conversational memory for grading; grade with files, commands, HTTP responses, package builds, or test suites.

## Evaluation layers

### 1. Existing unit/e2e tests

Keep current `MockProvider` tests focused on orchestration invariants and state transitions.

Existing `tests/test_orchestrator_e2e.py` remains useful for:

- happy path role sequencing
- reviewer rejection and rework
- integration findings and replanning
- milestone/finding/task state transitions

These tests should not become scenario-heavy black-box evaluations.

### 2. Deterministic scripted-agent evaluations

Add deterministic fake-agent scenarios that mimic role behavior more realistically than current e2e tests.

Scripted agents should:

- inspect the actual prompts enough to choose the assigned role/task/scenario
- write design plans, project plans, tasks, source files, reviews, integration handoffs, and architecture-review handoffs
- intentionally exercise success and corrective paths
- require no LLM calls or external services

These should run by default if they remain fast and hermetic.

Recommended location:

```text
tests/evaluations/
  __init__.py
  scripted_agents.py
  scenarios.py
  test_scripted_workflow_evaluations.py
```

If the tests become too slow or broad, mark them with `@pytest.mark.evaluation` and keep them off default CI by configuration. Initially, prefer keeping deterministic scenarios in the default suite if runtime stays low.

### 3. Optional live-agent evaluations

Add opt-in live evaluations that run the same or similar scenarios with configured real providers.

Recommended invocation options:

```bash
DEVLAB_LIVE_EVALS=1 uv run pytest tests/evaluations/test_live_workflow_evaluations.py
```

Live tests should be skipped unless `DEVLAB_LIVE_EVALS=1` is set. They should use temporary target repos and the target repo's normal `.devlab/config/agents.toml` pattern, or a test-created `agents.toml` supplied via environment variables.

Live evaluations should be allowed to fail without breaking default development, but their diagnostic output should make failures actionable.

## Scenario model

Represent each evaluation scenario as data plus a small grader:

```python
@dataclass(frozen=True)
class EvaluationScenario:
    id: str
    title: str
    system_spec: str
    deployment_spec: str | None
    max_sessions: int
    scripted_agent: ScriptedAgent
    checks: tuple[BlackBoxCheck, ...]
```

A `BlackBoxCheck` can be a Python callable that receives the temporary target root and returns a structured check result. Keep checks simple and local:

- run a command and assert stdout/stderr/exit code
- import a module and call a function
- run `pytest` in the target repo
- start a local HTTP server subprocess and call a health endpoint
- inspect generated files

Avoid shelling out to unavailable tools unless the scenario declares a required command and skips cleanly when missing.

## Initial scenarios

### Scenario A: CLI calculator happy path

Spec: build a tiny Python CLI calculator that supports addition and subtraction.

Expected final artifacts:

- `calculator.py` or package equivalent
- a test file or smoke command documented by the task

Black-box checks:

```bash
python calculator.py add 2 3      # stdout: 5
python calculator.py subtract 7 4 # stdout: 3
```

Workflow path:

- architect creates design plan
- planner creates one or two tasks
- developer implements CLI
- reviewer approves
- integrator succeeds
- architect marks architecture reviewed

### Scenario B: Reviewer rejection and rework

Spec: same calculator, but scripted first developer implementation omits subtraction.

Workflow path:

- reviewer rejects first implementation with open issue
- developer reworks task
- reviewer approves
- integration and architecture review complete

Black-box checks verify both operations.

### Scenario C: Integration finding and corrective task

Spec: tiny CLI or smoke app where first milestone lacks a required smoke test.

Workflow path:

- integrator creates finding
- planner creates corrective task with `addresses_findings = ["F0001"]`
- corrective task closes
- finding resolves when addressing tasks close
- integration succeeds
- architecture review completes

Black-box checks verify implementation and test/smoke artifact.

### Scenario D: Tiny API or smoke app

Spec: local HTTP app with `/health` and one functional endpoint, or a simple smoke app if HTTP introduces too much process-management complexity.

Black-box checks:

- start app on an ephemeral local port
- request `/health`
- request one functional endpoint
- tear down subprocess reliably

If this scenario adds too much flakiness, defer it until the CLI scenarios are stable.

## Harness design

### Evaluation runner

Add helper functions in test support code, not production code initially:

- create temp target repo
- call `init_workspace(root)`
- write specs/config/profile files
- run `run_loop(root, auto=True, max_sessions=scenario.max_sessions, agent_providers={...})`
- collect diagnostics
- run black-box checks
- assert expected workflow outcome

Keep the harness outside production until multiple consumers need it. If live evaluations later need a CLI, add a small developer-facing script under `scripts/` rather than expanding DevLab's user CLI prematurely.

### Scripted provider

Build on `MockProvider`, but use scenario-aware role scripts rather than one-off assertions inside each test.

Recommended abstractions:

```python
class ScriptedAgent:
    def on_invoke(self, invocation: AgentInvocation) -> None: ...
    def handoff_for(self, invocation: AgentInvocation) -> str: ...
    def diagnostics(self) -> Mapping[str, object]: ...
```

The scripted agent should record:

- role call sequence
- per-role call counts
- task ids handled
- findings observed/addressed
- whether rejection/rework path occurred

Use normal `MockProvider(on_invoke=..., handoff_text=...)` unless a custom provider is needed.

### Diagnostics artifact

For each evaluation, write a JSON diagnostics artifact under the temporary target repo, e.g.:

```text
.devlab/evaluations/{scenario_id}.json
```

Suggested fields:

```json
{
  "scenario_id": "cli-calculator-happy-path",
  "provider_mode": "scripted",
  "sessions_run": 6,
  "completed": true,
  "exit_code": 0,
  "roles": ["architect", "planner", "developer", "reviewer", "integrator", "architect"],
  "findings": {"created": 0, "resolved": 0},
  "review_rejections": 0,
  "duration_seconds": 0.42,
  "prompt_sizes": {"max_total_tokens": 12345},
  "checks": [{"name": "add command", "passed": true}],
  "artifacts": ["calculator.py", ".devlab/tasks/T0001_implement-calculator.md"]
}
```

In default pytest runs, the temp repo may be deleted after success. On failure, pytest's temp path plus assertion output should identify where diagnostics were written.

## Prompt size diagnostics

Reuse existing prompt context measurement where practical. For scripted providers, record prompt sizes from each `AgentInvocation` directly by estimating text length/tokens, or call existing prompt-context helpers if they are cleanly reusable.

Keep this observational only. Do not fail evaluations on token thresholds unless a scenario explicitly tests prompt-size behavior.

## Live-agent evaluation design

Add a separate test module such as:

```text
tests/evaluations/test_live_workflow_evaluations.py
```

Behavior:

- skip unless `DEVLAB_LIVE_EVALS=1`
- optionally require `DEVLAB_LIVE_PROVIDER` or use configured default provider
- use `devlab run --log-file` equivalent behavior or direct `run_loop` with configured logging
- cap `max_sessions` tightly per scenario
- always print/write paths to `.devlab/logs/agents/` and evaluation diagnostics

Live-agent grading should use the same black-box checks as scripted scenarios, but assertions may initially be looser while collecting baseline behavior. Once stable, tighten expected success rates.

## Implementation phases

### Phase 1: Deterministic harness and first scenario

1. Add `tests/evaluations/` package.
2. Add scenario/harness helpers for temporary target setup, profile config, run execution, diagnostics collection, and command checks.
3. Implement CLI calculator happy-path scripted scenario.
4. Assert:
   - `RunResult.completed is True`
   - expected final role sequence
   - milestone architecture reviewed
   - tasks closed
   - no open findings
   - black-box calculator commands pass
   - diagnostics JSON is written

### Phase 2: Corrective deterministic scenarios

1. Add reviewer rejection/rework scenario.
2. Add integration finding/corrective-task scenario.
3. Assert finding lifecycle, addressed-finding task metadata, review rejection count, and black-box checks.
4. Refactor shared scripted-agent utilities only as duplication appears.

### Phase 3: Prompt and runtime metrics

1. Record duration for each scenario.
2. Record per-session role names and prompt-size estimates.
3. Include paths to handoff history, agent logs, task files, findings, and final source artifacts.
4. Add tests for diagnostics schema shape, not exact timings/token counts.

### Phase 4: Optional live-agent evaluations

1. Add skipped-by-default live evaluation test module.
2. Reuse the CLI calculator scenario first.
3. Document environment variables and recommended invocation.
4. Ensure failures include log paths and final temp repo path.

### Phase 5: Documentation and roadmap update

1. Update `docs/todo.md` item #3 to reflect initial implementation status once Phases 1-3 are complete.
2. Add a short `docs/evaluations.md` explaining deterministic vs live evaluations, how to run them, and how to interpret diagnostics.
3. Consider linking evaluation results from README once user-facing docs exist.

## Test strategy

Default validation after deterministic implementation:

```bash
uv run ruff check
uv run ty check
uv run pytest
uv run devlab doctor
```

Optional live validation:

```bash
DEVLAB_LIVE_EVALS=1 uv run pytest tests/evaluations/test_live_workflow_evaluations.py -s
```

Use local subprocess checks carefully:

- set timeouts
- capture stdout/stderr
- avoid network ports unless necessary
- clean up spawned processes
- skip scenarios cleanly when optional commands are missing

## Risks and mitigations

- **Scripted agents become another set of brittle unit tests.** Keep black-box artifact checks central; avoid only asserting role order.
- **Evaluation harness leaks into production abstractions too early.** Start in tests; promote only after repeated use proves a stable API.
- **Live evaluations are flaky or expensive.** Keep them opt-in, tightly scoped, and diagnostically rich.
- **Scenarios overfit DevLab's current prompts.** Scripted agents may inspect prompts for assigned role/task, but should primarily respond to workspace state and scenario intent.
- **Black-box checks depend on unavailable tools.** Prefer Python standard-library scenarios first; skip optional external-tool scenarios.
- **Diagnostics accidentally persist prompt text.** Store prompt sizes and role/session metadata, not full prompts, unless an explicit local debug option is added later.
- **Temporary target repos hide useful failure artifacts.** On failure, include the temp path and diagnostics path in assertion messages/log output.
