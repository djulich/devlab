# Representative Workflow Live Baseline — 2026-09-20

This baseline closes the representative evidence matrix without rerunning every
provider or toolchain combination. It adds live evidence for the static frontend,
React/Vite frontend, existing-project adoption, and specification-reconciliation
families. The existing stateful API, deployable API, and compiled-language
baselines remain the selected evidence for those risks.

All runs used DevLab commit `b8cd73d7e1111d5f8fd7f318f2ec8bd8ca5a0c6c`
on Linux `7.2.5-200.fc44.x86_64`. The provider was Codex CLI `0.155.1`
using its model and effort defaults; no DevLab model or effort override was set.
The ordinary runs used Codex's `workspace-write` sandbox. The successful
React/Vite run used a local, ignored configuration with Codex
`danger-full-access` because its target-owned validation deliberately starts
rootless Podman containers. That broader provider permission was limited to the
trusted disposable evaluation workspace.

Successful raw diagnostics were copied locally to:

```text
.local/live-eval/results/20260920T142100Z_live-static-frontend-todo-app-happy-path_live.json
.local/live-eval/results/20260920T154041Z_live-react-vite-todo-app-happy-path_live.json
```

The adoption and reconciliation tests predate standard evaluation-diagnostics
export for those specialized multi-command flows. Their retained ignored target
workspaces are under `.local/live-eval/workspaces/adopt-20260920/` and
`.local/live-eval/workspaces/reconciliation-retry-20260920/`; the metrics below
come from their session metadata, workflow diagnostics, Git state, verification
records, and pytest assertions.

## Selection and exclusions

| Workflow family | Selected evidence | Decision |
| --- | --- | --- |
| Stateful API | [2026-06-24 stateful API](2026-06-24-stateful-web-api.md), plus the API graders in both new frontend runs | Do not rerun the standalone scenario; the current frontend runs repeat and strengthen its API contract. |
| Static frontend | `live-static-frontend-todo-app-happy-path`, below | Run because exact no-build HTML/CSS/JS artifacts and direct API calls are distinct from backend-only and React workflows. |
| React/Vite frontend | `live-react-vite-todo-app-happy-path`, below | Run because profile-owned container validation, a Vite proxy, an isolated build, and a real browser flow are distinct risks. |
| Deployable API | [2026-06-06 deployment](2026-06-06-deployment.md) | Do not rerun the same local-image artifact contract. The React run adds newer and stronger Podman execution evidence without duplicating deployment planning. |
| Existing-project adoption | `test_live_adopt_existing_current_state_baseline_and_feature_work`, below | Run because current-state discovery and preservation of target-owned validation are absent from greenfield runs. |
| Specification reconciliation | `test_live_spec_reconciliation_archives_and_replans`, below | Run because stale-spec refusal, generation archival, replacement planning, and continuation are distinct workflow-control risks. |
| Compiled-language profiles | [2026-08-20 compiled languages](2026-08-20-compiled-languages.md) | Do not rerun Rust, Go, C, or C++; all four profile/toolchain shapes already passed and another provider permutation would add cost rather than workflow coverage. |

## Static frontend

Command shape:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_STATIC_FRONTEND=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/codex.agents.toml \
DEVLAB_EVAL_RESULTS_DIR=.local/live-eval/results \
uv run pytest \
  tests/evaluations/test_live_workflow_evaluations.py::test_live_static_frontend_todo_app_happy_path_evaluation \
  -s -vv
```

The evaluation passed in `830.01s`; workflow diagnostics measured `829.77s`.
It used six sessions:

```text
architect, planner, developer, reviewer, integrator, architect
```

- Tasks: one closed task using the generated `python-static-web` profile.
- Rework: none; one developer and one reviewer session; zero review rejections.
- Findings: none.
- Validation: the profile's one default command passed, and milestone M1 was
  verified without untested claims or design drift.
- External grading: all five checks passed—stateful API behavior, static
  frontend structure and direct API calls, Make `run` and `test` targets, and
  usage documentation.
- Artifact hygiene: 12 product files (`25,564` bytes), four conventional
  ignored cache files (`25,350` bytes), no other ignored files, no flagged
  paths, and a clean final worktree.
- Git: six session commits and `devlab/milestone/M1` were present.
- Diagnostics: no quality warnings and no unattributed task sessions.

The six-session/one-task result is a labeled good case. The strict
`> 6 sessions per closed task` warning correctly did not fire.

## React/Vite frontend

Command shape:

```bash
DEVLAB_LIVE_EVALS=1 \
DEVLAB_LIVE_REACT_VITE_FRONTEND=1 \
DEVLAB_LIVE_AGENTS_TOML=.local/live-eval/codex-containers.agents.toml \
DEVLAB_EVAL_RESULTS_DIR=.local/live-eval/results \
uv run pytest \
  tests/evaluations/test_live_workflow_evaluations.py::test_live_react_vite_todo_app_happy_path_evaluation \
  -s -vv
```

The host had Podman `5.8.4`; the grader used the pinned `node:22-alpine` and
`mcr.microsoft.com/playwright:v1.53.1-jammy` images. The evaluation passed in
`1,457.99s`; workflow diagnostics measured `1,413.44s`. It used the same compact
six-role sequence as the static run.

- Tasks: one closed task using the generated `todo-app` profile.
- Profile: two default validation commands, `make test` and
  `make browser-test`, managed for developer, reviewer, and integrator roles.
- Rework: none; one developer and one reviewer session; zero review rejections.
- Findings: none.
- Validation: backend tests and the target-owned disposable Podman/Playwright
  browser flow passed; milestone M1 recorded passing profile-sourced commands.
- External grading: all ten checks passed, including independent API behavior,
  React/Vite structure, a container-isolated frontend build, a separate real
  browser add/list/delete flow, profile commands, Make targets, and docs.
- Artifact hygiene: 17 product files (`25,348` bytes), five conventional
  ignored cache files (`19,878` bytes), no other ignored files, no flagged
  paths, and a clean final worktree.
- Git: six session commits and `devlab/milestone/M1` were present.
- Diagnostics: no quality warnings and no unattributed task sessions.

The independent checks ran only after the workflow stopped. Their target copy
and dependency prefixes were evaluator-owned, and the post-check Git metrics
still reported a clean target worktree. No check result created a finding,
task, role session, or workflow resume.

## Existing-project adoption

The adopt-existing evaluation passed in `409.85s`, with `408.39s` of provider
runtime and six sessions:

```text
architect, planner, developer, reviewer, integrator, architect
```

- The architect recorded `calculator.py`, existing `add` behavior, the requested
  `subtract` behavior, and an explicit current-state/existing-project baseline.
- The planner preserved the existing stack and selected the target-owned
  `uv run pytest` validation path rather than bare harness-inherited `pytest`.
- One task closed with no rework, review rejection, finding, attribution gap, or
  diagnostic warning.
- Milestone verification passed the profile command with no untested claim or
  design drift.
- The independent assertions passed the preserved `add` command, new `subtract`
  command, and target-owned pytest suite. They then confirmed a clean worktree.
- Artifact hygiene reported seven product files (`8,263` bytes), 638
  conventional ignored files (`9,013,808` bytes, almost entirely `.venv/`), no
  other ignored files, and no flagged paths.

This is positive evidence that conventional dependency environments remain
measured without producing a large-artifact false positive.

## Specification reconciliation

The successful retry passed in `1,240.52s`, with `1,238.47s` of provider runtime
across 16 role sessions:

```text
architect, planner,
developer, reviewer,
developer, reviewer, developer, reviewer,
integrator, architect,
architect, planner, developer, reviewer, integrator, architect
```

Generation 1 created two tasks: a validation-profile task and the calculator
implementation. The implementation reviewer reproduced an uncaught finite
high-exponent `decimal.Overflow`, requested changes, and approved the corrected
implementation after its regression suite grew from eight to ten tests. This
was one real review rejection and one same-task developer/reviewer rework cycle,
not provider or grader noise. Milestone validation passed
`python -m unittest discover -v`; architecture review recorded the resulting
Decimal-range refinement as design drift.

After a committed specification change, normal implementation stopped before a
provider session with a `spec_reconciliation` error. Planning archived generation
1, activated generation 2, and produced replacement greeter work. Generation 2
then completed one task in the normal six-role sequence. Its four tests and
milestone validation passed with no finding, untested claim, or design drift.
The independent calculator and final greeter command checks passed, and the
worktree ended clean.

The active-generation diagnostics reported five product files (`3,572` bytes),
four conventional ignored cache files (`12,031` bytes), no other ignored files,
no flagged paths, and no quality warnings. Generation 1's reviewer rejection is
archived with generation 1, so active-generation diagnostics intentionally no
longer report its rework warning. Consumers comparing whole-project history
must account for the generation boundary instead of treating the active view as
an all-generations aggregate.

## Labeled negative attempts

Three unsuccessful attempts are retained as conclusions, not successful product
baselines:

1. The first static run failed before session 1 because the outer managed
   filesystem prevented Codex from initializing its user-local app-server state.
   This was provider infrastructure failure. No product existed. The harness
   nevertheless ran the five product checks and recorded them as `failed`; for
   this case those check statuses are false-positive product diagnostics and
   should be read with the structured `agent_invocation` error.
2. The first React run used the ordinary nested `workspace-write` provider
   sandbox. The product and backend tests were created, but rootless Podman
   failed before container startup because `newuidmap` could not create the user
   namespace. The run was interrupted after the developer correctly kept the
   task open. No external grader ran. This was an environment mismatch, resolved
   by the explicitly broader disposable-run provider configuration.
3. The first reconciliation run stopped after one architect session. The agent
   created a `python-cli` profile whose prerequisite table omitted its required
   `id`; DevLab committed the session and then allowed `load_profiles` to raise
   an uncaught `ValueError`. No external grader ran. This is a real workflow
   robustness failure and a diagnostic false negative: invalid generated
   executable configuration should produce a structured refusal rather than an
   uncaught test error. The clean retry demonstrates the reconciliation family,
   but does not erase this failure.

These labels preserve the required distinction: the Podman and app-server cases
were infrastructure failures, the malformed profile was a DevLab/product
failure, the Decimal overflow was ordinary reviewer-detected product rework,
and all post-workflow grader checks in successful runs passed.

## Diagnostic calibration

- **Task rework warning: supported.** The generation-1 Decimal defect is a true
  positive: reviewer-requested rework fixed a reproducible behavior error.
- **High sessions per closed task: lower boundary supported, upper threshold
  provisional.** Three good runs completed at exactly six sessions for one
  closed task and correctly produced no warning. No retained live run establishes
  that seven sessions per task is intrinsically poor, so the strict `> 6`
  threshold remains provisional.
- **Ignored artifact thresholds: provisional.** The adoption `.venv` case
  supports excluding conventional environments from warnings, and the compiled
  baseline supports allowing a roughly 43.6 MB Rust `target/` footprint. There
  is no labeled live case above the current 100 MB or 5,000 “other ignored”
  thresholds.
- **Integrator findings, unattributed task sessions, and flagged paths:
  provisional for live behavior.** All representative live runs had zero of
  each; deterministic evaluation tests still cover the warning mechanics.
- **External-check status classification: one false positive identified.** A
  pre-session provider infrastructure failure currently leaves downstream
  product checks marked `failed` rather than `unverified`. The accompanying
  workflow error makes the cause recoverable, but the status alone is too strong.
- **Invalid generated profile handling: one false negative identified.** The
  malformed prerequisite was not converted into structured workflow diagnostics.

The calibrated warnings remain advisory. None is used as a hidden correctness
gate, and grader or infrastructure failures are not fed back into the evaluated
workflow.

## Conclusion

Every workflow family named in issue #5 now has selected current live evidence
or an explicit non-rerun decision. The new successful runs support frontend,
browser/container, adoption, reconciliation, Git, validation, and artifact
hygiene claims. The negative attempts identify two diagnostic-classification
gaps without conflating them with generated-product correctness. No additional
provider or compiled-toolchain permutations are justified by the current risk
matrix.
