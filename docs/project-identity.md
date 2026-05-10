# Project Identity

DevLab is a reusable CLI and Python package for running an auditable, file-backed, role-based agentic software development workflow inside a target repository. Given a target system specification and local execution policy, it plans, implements, reviews, integrates, and verifies software changes, storing workflow artifacts under `.devlab/`.

## Mental Model

DevLab should eventually behave like a deployable application installed and run in a target repository, similar to how `git` is installed globally but operates on a specific repository.

In a target repository, DevLab maintains its own project-local workflow artifacts under `.devlab/`:

```text
target-repo/
  .git/
  .devlab/
  src/
  tests/
  deploy/
  ...
```

Unlike `.git/`, `.devlab/` is intentionally human- and agent-readable and should generally be committed by default. This supports auditability, resumability, collaboration, and reproducibility.

## DevLab Repo vs Target Repo

This repository currently serves two roles:

1. DevLab implementation repository, containing source code, tests, docs, and default role instructions.
2. A dogfooding target repository, where `.devlab/` contains the workflow state for developing DevLab itself.

These roles should remain conceptually separate.

Long-term model:

```text
devlab-package/
  src/devlab/
    resources/prompts/role-*.md
  docs/
  tests/

some-target-project/
  .devlab/
    specs/system/
    specs/deployment/
    config/
    plans/
    tasks/
    findings/
    history/
    logs/
  product code...
```

DevLab package provides reusable orchestration logic and default role/prompt sources. The target repository contains product-specific specifications, configuration, workflow state, generated plans, tasks, findings, logs, and product code.

## Primary Input

The core product input is the target system specification:

```text
.devlab/specs/system/
```

Deployment expectations should live alongside it:

```text
.devlab/specs/deployment/
```

The system specification represents product intent. It should be sufficient to drive architecture, planning, implementation, review, integration, and deployment verification work.

The system specification is not necessarily the only input. DevLab also needs target-local execution policy and operational configuration, such as:

- allowed tooling,
- provider/model choices,
- environment lifecycle commands,
- validation profiles,
- deployment constraints,
- secrets and credential policy,
- human approval gates.

These belong under `.devlab/config/`.

A useful distinction is:

```text
User/product intent:
  .devlab/specs/system/
  .devlab/specs/deployment/

Execution policy:
  .devlab/config/

DevLab-generated workflow state:
  .devlab/plans/
  .devlab/tasks/
  .devlab/findings/
  .devlab/history/
  .devlab/logs/

Product output:
  source code, tests, docs, deployment artifacts, etc.
```

## What DevLab Does

DevLab is not merely a code generator. It is an autonomous, file-backed software delivery loop.

Its workflow should increasingly approximate:

1. read the target specification,
2. design the architecture,
3. plan milestones and tasks,
4. implement a task,
5. review the task,
6. integrate the milestone,
7. create findings when coherence, quality, validation, or deployment readiness is missing,
8. re-plan corrective work,
9. repeat,
10. eventually verify that the system can be deployed.

The desired end state is an auditable, multi-agent development workflow that incrementally turns a specification into working, reviewed, integrated, and deployable software.

## Supported Target Complexity

DevLab should support target systems of varying complexity, including:

- simple scripts,
- command-line applications,
- libraries/packages,
- web applications,
- services,
- multi-service systems,
- multi-component software platforms,
- systems with deployment artifacts and operational requirements.

This means DevLab should avoid hard-coding assumptions such as:

- Python-only projects,
- single-service systems,
- one fixed test command,
- one fixed deployment model,
- one provider/model for all roles,
- local-only validation,
- no infrastructure concerns.

The `.devlab/` layout, tooling/environment configuration, future profiles, future agent configuration, and deployment specification model all support this broader goal.

## Package and Application

DevLab should be both:

- a Python package/library exposing reusable orchestration, providers, trackers, config loading, and workflow primitives;
- a CLI application installed and run in target repositories.

The user-facing model should be CLI-first, for example:

```bash
cd some-target-project
devlab init
devlab run
devlab status
devlab doctor
```

`devlab init`, `devlab run`, and `devlab status` are implemented; `devlab doctor` remains future validation tooling.

## Design Implications

The project should continue moving toward these principles:

- DevLab runs in a target repository rather than assuming the target is DevLab implementation repo.
- `.devlab/` is the target-project-local workflow root.
- DevLab-owned role/prompt sources remain package resources under `src/devlab/resources/prompts/`.
- Target-specific specs, config, plans, tasks, findings, history, logs, and session artifacts belong under `.devlab/`.
- Workflow rules should live in code where practical, not only in prompts.
- The repository remains the system of record.
- Generated workflow artifacts should be auditable and restartable.
- Deployment should be planned and verified, but production deployment should require explicit policy and safeguards rather than being the default.
