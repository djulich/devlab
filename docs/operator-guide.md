# DevLab Operator Guide

This guide is for the person running DevLab in a target workspace. It explains
how to inspect the file-backed workflow state under `.devlab/`, what is safe to
edit by hand, and which files DevLab expects to own during normal workflow runs.

For architecture rationale, see `docs/design.md`. For agent command setup, see
`docs/agent-configuration.md`.

## Operating Model

DevLab treats the target repository as the workflow record. Specs, plans, tasks,
milestones, findings, handoffs, logs, and configuration are ordinary files so
they can be reviewed, committed, diffed, and recovered after interrupted runs.

The usual operator loop is:

1. Edit `.devlab/specs/` and `.devlab/config/`.
2. Commit those operator-authored changes.
3. Run `devlab doctor`, `devlab status --verbose`, and optionally
   `devlab agent-smoke-test`.
4. Run `devlab plan`.
5. Inspect generated plans/tasks if needed.
6. Run `devlab run --max-sessions N`.
7. Use `devlab status`, `devlab diagnostics`, and Git history to inspect results.

`devlab plan` and `devlab run` require a clean working tree before agent
sessions. This keeps operator-authored changes separate from DevLab-authored
session commits.

## What Operators Own

Operators normally edit:

- `.devlab/specs/system/*.md`: system requirements and feature intent.
- `.devlab/specs/deployment/*.md`: deployment, packaging, runtime, and
  operations requirements.
- `.devlab/config/agents.toml`: provider commands, role mappings, models,
  efforts, timeouts, and prompt transport.
- `.devlab/config/tooling.md`: target-local tooling policy.
- `.devlab/config/profiles/*.toml`: reusable task profiles, when intentionally
  changing validation or environment lifecycle behavior.
- `.gitignore`: secrets, local caches, generated files, and other files DevLab
  should not commit.

DevLab and worker agents normally write:

- `.devlab/plans/`
- `.devlab/tasks/`
- `.devlab/milestones/`
- `.devlab/findings/`
- `.devlab/history/`
- `.devlab/session-artifacts/`
- `.devlab/logs/`
- `.devlab/workflow.toml`
- `.devlab/generations/`

Manual edits to generated workflow state are sometimes useful for repair, but
prefer `devlab doctor` before and after doing so. Reporting commands such as
`status`, `diagnostics`, and `doctor` are read-only; they do not repair state.

## Specs and Planning

DevLab reads all Markdown files under:

```text
.devlab/specs/system/
.devlab/specs/deployment/
```

After editing specs, commit the changes and run `devlab plan`. DevLab records the
latest committed spec revision it planned against in `.devlab/workflow.toml`.
If committed specs change later, `devlab run` stops and asks you to run
`devlab plan` again.

During spec reconciliation or `devlab plan --replace-plan`, DevLab archives the
active generation bundle under `.devlab/generations/NNNN/` and starts a fresh
active planning graph. Archived generations are evidence, not active work.

Use:

- `devlab plan`: reconcile committed specs and create missing planning state.
- `devlab plan --revise`: ask architect and planner to review active plans even
  when specs have not changed.
- `devlab plan --adopt-existing`: first planning run for an already-started
  repository.
- `devlab plan --replace-plan`: archive the active plan and create a fresh one.

## Profiles

Profiles live under:

```text
.devlab/config/profiles/
```

Each task resolves to exactly one profile:

- if task front matter contains `profile = "<id>"`, DevLab uses
  `.devlab/config/profiles/<id>.toml`;
- otherwise it uses `profile = "default"`.

A profile contains:

- `version`, `id`, and `title`;
- `[tooling].summary`: human/agent-readable task environment summary;
- `[tooling].default_validation`: validation commands used when a task does not
  define task-specific validation;
- `[environment].managed_roles`: roles that run inside this profile lifecycle;
- `[environment].pre_session`, `setup`, and `post_session`: executable lifecycle
  commands;
- `[timeouts]`: command timeouts.

Profile commands are trusted executable configuration. DevLab does not sandbox
them or install missing tools. Review profile changes before running workflow
commands, especially in cloned or agent-modified workspaces.

Keep profile compatibility in mind. If a changed profile would remove, replace,
narrow, or materially alter validation, setup, teardown, services, or assumptions
used by already-planned tasks, prefer creating a new profile and assigning new
tasks to it.

## Tasks

Tasks live under:

```text
.devlab/tasks/
```

Each task is a Markdown file with TOML front matter. Important fields include:

- `id`: stable task id such as `T0001`.
- `status`: `open`, `in_review`, `changes_requested`, or `closed`.
- `milestone`: milestone id such as `M1`, when the task belongs to a milestone.
- `profile`: profile id.
- `depends_on`: task ids that must close before this task can be selected.
- `validation`: task-specific validation commands.
- `addresses_findings`: findings this task is meant to resolve.

Developer sessions work on exactly one eligible task. Reviewer sessions review
exactly one task in review. The orchestrator updates task status after validating
handoffs and task-file signals.

Task files are generated workflow state. Operators should usually change
requirements through specs and then run `devlab plan` rather than editing task
scope directly.

## Milestones

Milestone state lives under:

```text
.devlab/milestones/
```

Milestones group tasks into coherent integration boundaries. Task files are the
source of truth for task status; milestone files track milestone-level workflow
state such as integration and architecture review.

Common milestone fields include:

- `id` and `title`;
- `status`: for example `planned`, `active`, `tasks_complete`,
  `integration_failed`, `integrated`, or `architecture_reviewed`;
- `task_ids`: tasks in the milestone;
- `integration_required`: whether the integrator should run for this milestone;
- `integrated`: whether integration passed;
- `architecture_reviewed`: whether the architect performed milestone review;
- `integration_handoff` and `architecture_review_handoff`: archived handoff
  filenames under `.devlab/history/`;
- `findings`: findings associated with the milestone.

When all tasks in a milestone close, DevLab routes to the integrator. After a
successful integration handoff, DevLab routes the integrated milestone to the
architect for project-state review. Architecture review is not an approval gate:
remaining drift is recorded as findings.

## Findings

Findings live under:

```text
.devlab/findings/
```

Findings are durable corrective issues created from integrator or architect open
issues. They are not general-purpose bug reports; they represent workflow issues
that need planner follow-up.

Finding status values are:

- `open`: planner still needs to create corrective work.
- `planned`: planner has mapped the finding to a complete set of addressing
  tasks.
- `resolved`: all addressing tasks are closed.

The planner addresses a finding by creating task files whose front matter lists:

```toml
addresses_findings = ["F0001"]
```

The planner handoff must also list the complete finding-to-task mapping. DevLab
marks the finding as planned only after validating both sides of that relation.

## Handoffs

Every role session writes its current handoff to:

```text
.devlab/session-artifacts/<role>/handoff.md
```

After a valid session, DevLab archives it under:

```text
.devlab/history/
```

Handoffs are the session audit trail. They record what the role did, what changed,
what could not be finished, validation evidence, open issues, and recommended next
steps. Later sessions may read them for continuity, but durable state transitions
come from the orchestrator processing validated files and handoffs.

Planner handoffs also include a `## Planning State` section with:

```toml
planning_complete = true
```

or:

```toml
planning_complete = false
```

The orchestrator parses that section and updates `.devlab/workflow.toml`; planner
agents do not edit workflow control state directly.

## Logs and Diagnostics

Agent logs live under:

```text
.devlab/logs/agents/
```

They include resolved invocation metadata, stdout, stderr, and failure diagnostics.
When `--retain-prompts` is used, DevLab also writes full base/session prompts next
to those logs.

Treat logs and retained prompts as sensitive. They may contain target-project
details, command output, file paths, and prompt context.

Useful inspection commands:

- `devlab status --verbose`: current workflow state, resolved providers, and
  approximate prompt sizes.
- `devlab diagnostics --verbose`: workflow-history diagnostics and quality
  warnings.
- `devlab doctor`: workspace configuration and workflow-state validation.
- `devlab history`: recorded session history from metadata files.
- `devlab clean-failed-session`: remove untracked logs/artifacts left by failed
  sessions while preserving target source changes.

## Generations

Active workflow files describe the current planning generation. Archived
generations live under:

```text
.devlab/generations/NNNN/
```

A generation archive contains the prior active generation bundle:

- tasks;
- milestones;
- findings;
- history;
- session artifacts;
- agent logs;
- plans;
- workflow state;
- `generation.toml`.

Target-owned inputs such as `.devlab/specs/`, `.devlab/config/`, and ADRs are not
archived into generations. They remain active inputs for the next planning run.

Archived generations are read-only history. Active selectors ignore archived
tasks and milestones.

## Before Running Unattended

Before running a longer workflow:

- confirm `.gitignore` excludes secrets, caches, local credentials, and large
  generated artifacts;
- review `.devlab/config/agents.toml`;
- review profile lifecycle commands;
- run `devlab doctor`;
- run `devlab agent-smoke-test`;
- commit operator-authored spec/config changes;
- choose a bounded `--max-sessions` value.

DevLab is designed to be resumable. Prefer smaller bounded runs followed by
inspection over one very large unattended run in an unfamiliar target workspace.
