# Deployment Verification Remaining Slices

This plan tracks the remaining implementation work for deployment specification and verification support.

## Guiding rule

DevLab may invoke target-owned deployment verification commands, but it must not install missing host deployment tools. Missing tools are user/CI prerequisites and keep the related deployment claim unverified until the environment provides them. See `docs/adr/0008-do-not-install-host-deployment-tools.md`.

## Slice 1: Deployment `doctor` checks

Goal: add non-mutating diagnostics for deployment readiness and tool prerequisites. These checks are most useful after `devlab plan`, when architect/planner sessions have translated prose specs into design, project-plan, and task state.

Likely files:

- `src/devlab/doctor.py`
- `tests/test_doctor.py`

Checks to add:

1. Unknown task domains.
   - Known built-ins are `general` and `deployment`.
   - Report unknown domains because no domain prompt overlay will be used.
2. Empty or malformed deployment spec signals.
   - Placeholder deployment templates should not trigger requirements.
   - Empty active specs should report actionable diagnostics.
3. Production deployment claims without explicit boundary language.
   - Accept wording such as production deployment being out of scope, documentation-only, or requiring future explicit configuration.
4. Deployment tool availability for substantive specs.
   - Detect mentioned tools such as `podman`, `docker`, `docker compose`, `kind`, `kubectl`, `kubeconform`, `rpmbuild`, `rpmlint`, and `systemd-analyze`.
   - Use PATH checks only; do not run tools or target-owned commands from `doctor`.

Constraints:

- `doctor` must not install tools.
- `doctor` must not run deployment tools.
- `doctor` must not execute target-owned commands.
- `doctor` must not mutate workflow state.

Test coverage:

- Unknown task domain reports a problem.
- `general` and `deployment` domains pass.
- Placeholder deployment template does not trigger tool checks.
- Active spec mentioning missing tools reports problems with actionable wording.
- Production claim without boundary language reports a problem.
- Production claim with explicit out-of-scope/documentation-only/future-configuration language passes.

## Slice 2: Safe static/artifact validation in evaluations

Status: **complete**. Scripted deployment evaluations now include an optional `make deployment-check` check behind `DEVLAB_EVAL_DEPLOYMENT_TOOLS=1`. The normal suite remains structural-only; missing `make` is reported as skipped/unverified and DevLab does not install host tools. The exact `make deployment-check` name is an evaluation contract for this scenario, not a universal target-project command name.

Goal: expand evaluation checks beyond file presence where safe host tools are available, without making those tools mandatory for the normal suite.

Likely files:

- `tests/evaluations/scripted_agents.py`
- `tests/evaluations/checks.py` or the existing check owner
- `tests/evaluations/test_scripted_workflow_evaluations.py`
- `docs/evaluations.md`

Implementation notes:

- Keep structural checks as the normal hard gate.
- Add optional tool-backed checks behind an explicit environment variable, for example `DEVLAB_EVAL_DEPLOYMENT_TOOLS=1`.
- Start with `make deployment-check` when `make` is available.
- Consider image builds only when explicitly enabled; they can be slow, pull base images, and depend on host container runtime state.
- Missing tools should be reported as skipped/unverified, never installed.

## Slice 3: Compose deterministic evaluation

Status: **complete**. The scripted evaluation suite now includes `compose-deployment-happy-path`, covering `compose.yaml`, `.env.example`, `compose-check`, `deploy-local`, `undeploy-local`, `scripts/smoke-test.sh`, deployment documentation in `README.md` or `docs/**/*.md`, deployment-domain task attribution, and optional `docker compose config` behind `DEVLAB_EVAL_DEPLOYMENT_TOOLS=1`.

Goal: cover a second deployment family beyond the existing local container artifact scenario.

Scenario idea: `compose-deployment-happy-path`.

Expected artifacts:

- `compose.yaml`
- `.env.example`
- `Makefile` targets such as `compose-check`, `deploy-local`, and `undeploy-local`
- `scripts/smoke-test.sh`
- deployment documentation in `README.md` or `docs/deployment.md`
- a deployment-domain task with `domain = "deployment"`

Checks:

- Required files and snippets exist.
- Documentation names build/run/verify/teardown commands.
- Teardown behavior is documented.
- Optional `docker compose config` may run only when explicitly enabled and available.

Do not require live containers in the normal test suite.

## Slice 4: Live deployment baseline collection

Goal: run the existing opt-in live deployment evaluation and use outcomes to tune prompts, diagnostics, and thresholds.

Recommended preflight shape for manual runs:

```bash
devlab plan --auto
devlab doctor
devlab run --auto
```

Live evaluation command shape:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_DEPLOYMENT=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/<env>.agents.toml \
uv run pytest tests/evaluations/test_live_workflow_evaluations.py::test_live_deployable_web_api_happy_path_evaluation -s
```

Inspect diagnostics for:

- session count
- developer/reviewer rework
- deployment-domain task attribution
- whether verification commands were created and run
- whether missing tools were handled clearly
- quality warnings

Update `docs/todo.md`, `docs/evaluations.md`, or deployment prompt overlays only when live evidence shows wording or workflow gaps.

## Slice 5: Profile validation modeling decision

Goal: decide from evidence whether project-owned commands plus prompt guidance are enough.

Questions:

- Are agents consistently creating discoverable project-owned deployment verification commands?
- Do reviewers and integrators treat missing tools as unverified?
- Are profile validation commands too unstructured for deployment work?

If current behavior is sufficient, defer structured modeling. If not, design first-class validation command metadata in profiles without adding deployment-specific branches to `orchestrator.py`.

## Suggested order

1. Add deployment `doctor` checks.
2. Add optional tool-aware evaluation checks.
3. Add Compose deterministic evaluation.
4. Collect live deployment baselines.
5. Revisit profile validation modeling.
