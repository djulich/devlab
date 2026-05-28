# Refactoring Opportunities

This document captures refactoring opportunities identified before the next feature-development slice. The goal is to keep DevLab maintainable for humans and coding agents by preserving clear module boundaries, reducing duplicated infrastructure, and keeping large files scoped to one concern.

## Priority order

1. Split `src/devlab/workflow_diagnostics.py`, especially artifact hygiene.
2. Split `tests/evaluations/scripted_agents.py` before adding more scenario families.
3. Extract shared Git command helpers.
4. Before post-reviewer validation, extract a session-execution seam from `src/devlab/orchestrator.py`.
5. Then consider `doctor.py` and test helper cleanup.

## 1. Split workflow diagnostics

Current file:

```text
src/devlab/workflow_diagnostics.py
```

Approximate size at time of writing: 700+ lines.

It currently mixes several concerns:

- diagnostic dataclasses / public data model
- workflow-history derivation from handoff files
- task-cycle and rework metrics
- profile/log metrics
- Git-based artifact hygiene and ignored-artifact contributor bucketing
- quality warning construction
- human-readable formatting

Suggested target shape:

```text
src/devlab/workflow_diagnostics.py      # public facade/build_workflow_diagnostics
src/devlab/diagnostic_models.py         # dataclasses shared by diagnostics/evaluations
src/devlab/workflow_history.py          # sessions, task cycles, review rejection derivation
src/devlab/artifact_hygiene.py          # git ls-files/check-ignore, contributors
src/devlab/diagnostic_formatting.py     # format_workflow_diagnostics
```

Notes:

- Keep `build_workflow_diagnostics(root)` and `format_workflow_diagnostics(root, ...)` as stable public entry points unless there is a good reason to rename them.
- Artifact hygiene is the strongest first extraction because it has independent Git logic and contributor bucketing.
- Workflow-history metrics should remain independent from scenario-specific evaluation checks.
- Production code must not import from `tests.evaluations.*`.

## 2. Split evaluation scripted agents

Current file:

```text
tests/evaluations/scripted_agents.py
```

Approximate size at time of writing: 800+ lines.

It currently contains:

- scripted role-agent classes
- generated product writers
- black-box scenario checks
- HTTP helper functions
- finding helpers

Suggested target shape:

```text
tests/evaluations/scripted_agents.py      # agent classes/factory exports
tests/evaluations/generated_products.py   # write_calculator, write_stateful_todo_api, etc.
tests/evaluations/scenario_checks.py      # stateful_todo_api_check, deployment_artifacts_check, etc.
tests/evaluations/http_helpers.py         # _free_port, _http_json, _wait_for_http
```

Notes:

- This is the biggest test-side maintainability win.
- Do this before adding another scenario family.
- Preserve black-box checks as evaluation-specific test code; do not move scenario correctness checks into production diagnostics.

## 3. Extract shared Git command helpers

Git subprocess wrappers currently exist in multiple places, including:

```text
src/devlab/version_control.py
src/devlab/workflow_diagnostics.py
tests/evaluations/harness.py
tests/test_cli.py
```

`version_control.py` is mutation-oriented, while diagnostics needs read-only Git operations such as `ls-files` and `check-ignore`.

Suggested addition:

```text
src/devlab/git.py
```

Potential helpers:

```python
run_git(...)
git_output(...)
git_ls_files(...)
git_check_ignore(...)
```

Notes:

- `version_control.py` can use the shared helpers for mutations while preserving `VersionControlError` semantics.
- Artifact hygiene can use read-only helpers.
- Evaluation tests can either use production helpers or keep tiny local wrappers where test isolation is clearer.
- Centralizing this should improve error formatting and reduce duplicated subprocess code.

## 4. Extract an orchestrator session-execution seam

Current file:

```text
src/devlab/orchestrator.py
```

`run_loop` is improved, but it still owns many concerns:

- routing to the next role
- session context creation
- prompt construction
- environment setup/teardown
- provider invocation
- handoff validation
- handoff processing
- Git commit/tagging
- finish logging

Suggested seam before adding post-reviewer structural validation:

```python
run_one_session(...) -> SessionRunOutcome
```

or smaller internal helpers:

```python
prepare_session(...)
execute_agent_session(...)
process_valid_session(...)
```

Notes:

- Do not over-abstract prematurely.
- Post-reviewer structural validation is a good trigger because it will add another branch after reviewer approval.
- Keep provider-specific invocation in `agents.py` and orchestration/routing in `orchestrator.py`.
- Keep reporting/diagnostic commands non-mutating.

## 5. Move test workspace builders into shared helpers

`tests/test_orchestrator.py` is large and has many local helpers, including variants of:

```text
_setup_tree
_write_task
_write_profile
_approve_task
_complete_developer_task
```

Some shared helpers already exist in:

```text
tests/helpers.py
```

Potential target:

```text
tests/helpers.py
tests/workspace_builders.py
```

Notes:

- This would make `tests/test_orchestrator.py` easier to scan.
- Prefer focused builders over one overly flexible fixture object.
- Avoid hiding important test setup details behind too much abstraction.

## 6. Split doctor checks by validation domain

Current file:

```text
src/devlab/doctor.py
```

Approximate size at time of writing: 500+ lines.

It validates unrelated domains:

- agent config
- prompt context thresholds
- project knowledge / ADRs
- milestones
- placeholder validation

Suggested target shape:

```text
src/devlab/doctor.py                  # public check_workspace/report
src/devlab/doctor_agent_config.py
src/devlab/doctor_knowledge.py
src/devlab/doctor_milestones.py
src/devlab/doctor_prompt_context.py
```

Notes:

- Not urgent, but likely useful as deployment/profile diagnostics grow.
- Preserve `check_workspace(root)` and `format_doctor_report(...)` as the CLI-facing API.

## 7. Reduce duplicated summary logic cautiously

Similar read-only summaries exist across:

```text
src/devlab/status.py
src/devlab/workflow_diagnostics.py
src/devlab/session_logging.py
src/devlab/prompts.py
```

Potential home for some reusable domain summaries:

```text
src/devlab/task_tracker.py
src/devlab/milestones.py
src/devlab/findings.py
```

Notes:

- Do not merge prompt/status/diagnostics formatting too aggressively; they serve different user moments.
- Avoid turning `WorkspaceSnapshot` into a god object.
- Prefer small domain-owned helpers for counts/status grouping where duplication is clear.

## 8. Add a plan index / stale-docs guide

There are many documents under:

```text
docs/plans/
```

Some are active plans, some are implemented reference plans, and some may be superseded. Add:

```text
docs/plans/README.md
```

Suggested sections:

- Active plans
- Implemented/reference plans
- Superseded or historical plans

Notes:

- This reduces the risk of agents treating old planning text as current instructions.
- `docs/todo.md` should remain the canonical open-work list unless intentionally replaced.

## 9. Decide artifact policy for `sessions/*.html`

Current concern:

```text
sessions/*.html
```

Large tracked HTML exports may be useful durable evidence, or they may be local artifacts that should live outside Git.

Possible outcomes:

- Document them as durable evaluation evidence.
- Move/archive them elsewhere.
- Add an ignore rule if they are not meant to be tracked.

Related future diagnostic:

- Warn about large tracked/product artifacts, not only large ignored artifact footprints.

## Things not to refactor yet

- Do not split `Workspace` merely because it is moderately large; its current boundary is coherent: mutation handles plus cached read-only snapshot.
- Do not create new workflow roles for deployment or validation; domain overlays remain the preferred design.
- Do not merge prompt/status/diagnostics formatting broadly; each serves a different audience and timing.
- Do not generalize evaluation scenarios before splitting `scripted_agents.py`; premature abstraction there would make the file harder to understand.

## Validation expectation for each slice

After each refactoring slice, run:

```bash
uv run ruff check
uv run ty check
uv run pytest -q
uv run devlab doctor
```
