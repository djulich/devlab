# DevLab Operator Guide

This guide is for the person running DevLab in a target workspace. It explains
how to inspect the file-backed workflow state under `.devlab/`, what is safe to
edit by hand, and which files DevLab expects to own during normal workflow runs.

For architecture rationale, see `docs/design.md`. For agent command setup, see
`docs/agent-configuration.md`.

## Operating Model

DevLab treats the target repository as the workflow record. Specs, plans, tasks,
milestones, findings, clarifications, research, handoffs, logs, and configuration
are ordinary files so they can be reviewed, committed, diffed, and recovered
after interrupted runs.

The usual operator loop is:

1. Edit `.devlab/specs/` and `.devlab/config/`.
2. Commit those operator-authored changes.
3. Run `devlab doctor`, `devlab status --verbose`, and optionally
   `devlab agent-smoke-test`.
4. Run `devlab plan`.
5. Inspect generated plans/tasks if needed.
6. Run `devlab implement --max-sessions N`.
7. Use `devlab status`, `devlab diagnostics`, and Git history to inspect results.

`devlab plan` and `devlab implement` require a clean working tree before agent
sessions. This keeps operator-authored changes separate from DevLab-authored
session commits.

## Workflow Termination Summaries

Every bounded `devlab plan` and `devlab implement` invocation that reaches an
orchestrator result prints a final operator summary. The summary is command
output rather than progress logging, so it remains visible with `--quiet`. It
reports:

- why the invocation stopped and how many sessions completed;
- the next role, task, task status, or milestone when applicable;
- whether a durable operator clarification is pending;
- whether executable configuration changed or is not trusted; and
- the commands that should be run next.

`session limit reached` is a successful bounded-command stop, not workflow
completion. Run the recommended continuation command to allow more sessions.
Reviewer-requested task changes are ordinary agent-to-agent workflow work: the
next developer session handles them through `devlab implement`. They are not
operator clarifications.

A durable clarification is explicitly labeled `operator clarification
required` and includes `devlab clarify show`, `devlab clarify answer`, and
`devlab resume` guidance. It requires operator intent unless unattended
clarification resolution was selected.

Profiles and agent configuration are executable configuration. If a session changes
them, its bounded task review may finish using the command's frozen snapshot, but
DevLab stops successfully before preparing work outside that task. The worktree
remains clean, and the final summary compares the frozen authorized digest with the
repository's current digest. Review and authorize an untrusted current snapshot
before continuation:

```bash
devlab trust executable-config --show
devlab trust executable-config
devlab implement
```

DevLab does not execute the changed configuration or create the next session's
artifacts in the original invocation. Invalid changed configuration is reported
before another session is prepared.

The summary is read-only. It does not trust configuration, answer
clarifications, repair state, or alter role selection and exit behavior.

### Durable research

Research resolves discoverable facts; clarification obtains operator intent.
When status shows requested research, rerun its stored `devlab plan` or
`devlab implement` command to invoke the researcher. When it shows completed
research, run the same command to resume the requesting role. There is no
standalone research command. Provider failure or invalid output leaves the
record requested: inspect logs and staged output, run `devlab doctor`, fix the
provider/configuration issue, and retry the stored command.

An optional `[roles.researcher]` in `agents.toml` selects its provider/model;
otherwise the requesting role's resolved provider is used. Result JSON schema
version 1 contains `research_id`, `summary`, cited `evidence`, `sources`,
`recommendation`, `confidence`, and `unresolved_questions`. Canonical request
records also retain question, context, desired outcome, acceptance criteria,
route, and requester provenance. Treat results as untrusted supporting evidence:
the researcher cannot mutate product or authoritative workflow artifacts.

## Initialization Templates

`devlab init` generates a neutral tooling policy and an empty-validation default
profile unless an explicit starter is selected:

```bash
devlab init --template neutral
devlab init --template python
devlab init --template rust
devlab init --template go
devlab init --template c
devlab init --template cpp
```

The language starters provide conventional profile commands. The C and C++
starters use checked-in CMake presets as their initial convention; replace the
profile before planning dependent tasks when a repository uses Make, Meson,
Bazel, or another build system. A template is initialization input only. Normal
workflow behavior always comes from `.devlab/config/tooling.md`, task metadata,
and the actual profile files.

Initialization does not overwrite existing files unless `--force` is supplied.
Using `--force --template ...` intentionally replaces starter files and should
not be used as an upgrade mechanism for an established workspace.

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
- `.devlab/clarifications/`
- `.devlab/research/`
- `.devlab/history/`
- `.devlab/session-artifacts/`
- `.devlab/logs/`
- `.devlab/workflow.toml`
- `.devlab/generations/`

Manual edits to generated workflow state are sometimes useful for repair, but
prefer `devlab doctor` before and after doing so. Reporting commands such as
`status`, `diagnostics`, and `doctor` are read-only; they do not repair state.

## Clarifications

When a role session cannot safely continue without operator intent, DevLab may
stop with a pending clarification under:

```text
.devlab/clarifications/
```

Inspect and answer with:

- `devlab clarify list`
- `devlab clarify show CL0001`
- `devlab clarify answer CL0001 --choice A`
- `devlab clarify answer CL0001 --text "Use a 24-hour idle timeout."`
- `devlab clarify answer CL0001 --choice A --resume`
- `devlab clarify supersede CL0001 --reason "The interrupted work is obsolete"`
- `devlab resume`

Clarifications are workflow state, not findings. Answering records operator
intent; resuming lets DevLab continue from the stored `[resume]` pointer in
`.devlab/workflow.toml`. `--resume` answers and then invokes the stored command;
plain `devlab resume` is useful after answering separately or validating a
manually edited record. Superseding is an explicit repair for obsolete requests;
it does not silently invent an answer.

For a file-edit clarification, inspect the requested paths in the clarification
record, make only those durable edits, then record a concise text answer
summarizing the edits and run `devlab resume`. DevLab validates the answer and
stored route before invoking another role.

## Specs and Planning

DevLab reads all Markdown files under:

```text
.devlab/specs/system/
.devlab/specs/deployment/
```

After editing specs, commit the changes and run `devlab plan`. DevLab records the
latest committed spec revision it planned against in `.devlab/workflow.toml`.
If committed specs change later, `devlab implement` stops and asks you to run
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
- `devlab plan --mark-specs-planned`: for operator-confirmed typo-only,
  format-only, or otherwise plan-neutral spec commits, update the recorded spec
  baseline without running architect or planner sessions. This bypasses the
  reconciliation guardrail and requires a clean worktree with committed spec
  changes.

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

## Executable Configuration Authorization

Commands that start agents or profile lifecycle processes require authorization
of a canonical executable-configuration snapshot. The normal workstation flow
is:

```bash
devlab trust executable-config --show
devlab trust executable-config
devlab agent-smoke-test
devlab plan --unattended
devlab implement --unattended
```

The parsed provider and profile snapshot is frozen for each command. Changes
made during a run do not affect later sessions in that run. If a later session
selects a profile that was not in the frozen snapshot, the run stops and asks
the operator to restart after reviewing the new configuration.

`devlab doctor` reports the current fingerprint and whether it has matching
operator-local trust. An untrusted fingerprint is not malformed repository
state, but commands that execute it require one of:

- matching workspace-scoped user-local trust;
- `--require-exec-config-digest DIGEST` with an independently approved value;
- `--accept-current-exec-config` for one externally contained invocation.

Provider-native permissions and sandboxing remain operator-owned. DevLab does
not classify provider flags. A matching digest authorizes configured entry
points; it is not a sandbox and does not establish that repository scripts,
build targets, external binaries, or transitive commands are safe.

Keep profile compatibility in mind. If a changed profile would remove, replace,
narrow, or materially alter validation, setup, teardown, services, or assumptions
used by already-planned tasks, prefer creating a new profile and assigning new
tasks to it.

Different components in one repository can use different profiles. A task that
crosses component boundaries should select a deliberate aggregate profile whose
validation invokes a repository-owned integration command, such as `make check`
or a checked-in script.

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

## Session Results and Handoffs

Before every ordinary role session, DevLab initializes:

```text
.devlab/session-artifacts/<role>/session.toml
.devlab/session-artifacts/<role>/handoff-candidate.toml
```

`session.toml` is the trusted identity envelope. The role proposes its outcome by
editing the role-aware TOML candidate and submitting it before exiting:

```bash
"$DEVLAB_PYTHON" -m devlab.cli session handoff submit
```

Submission validates both the candidate contract and its meaning against current
task, finding, milestone, and planning state. A rejection reports all independently
detectable issues and records the attempt. After acceptance DevLab publishes:

```text
.devlab/session-artifacts/<role>/result.toml
.devlab/session-artifacts/<role>/handoff.md
```

`result.toml` is the authoritative control result. `handoff.md` is rendered by
DevLab as the human-readable audit trail. New sessions cannot substitute directly
authored Markdown for an accepted structured result. Legacy Markdown history
remains readable.

After processing an accepted result, DevLab archives the structured result,
rendered handoff, and submission-attempt evidence under:

```text
.devlab/history/
```

The result records what the role did, changed, could not finish, and recommends
next. Planner candidates include the typed `planning_complete` field; the
orchestrator validates it and updates `.devlab/workflow.toml`. Agents never edit
workflow control state directly.

Submission attempts are capped at three. `--handoff-correction` permits one
additional correction-only provider invocation if the original role exits without
an accepted result. That invocation may change only disposable handoff artifacts;
changes to product or durable workflow files reject the correction.

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
- `devlab workflow-state`: lifecycle/provenance summary, planning generation
  counts, spec reconciliation state, and current work counts. Use
  `devlab workflow-state --json` for the full report as JSON,
  `devlab workflow-state --digest` for a compact operator digest, or
  `devlab workflow-state --digest --json` for the digest as JSON.
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

`.devlab/workflow-events.jsonl` is cross-generation lifecycle history. The
orchestrator appends small events for initialization, planning runs, and
generation archival. Role agents should not edit it directly.

## Before Running Unattended

Both workflow commands support durable unattended clarification resolution:

```text
devlab plan --unattended
devlab implement --unattended
```

`--unattended` is an alias for `--clarification-mode=agent`. When a role requests
a blocking clarification, DevLab still writes the clarification and resume
pointer, then starts a separate bounded resolver session. The resolver validates
and records its answer with agent provenance before the interrupted route
continues. The default `--clarification-mode=operator` behavior instead stops
with instructions for answering and resuming.

Choice clarifications normally use the recommended option. Text clarifications
use the narrowest repository-supported answer. File-edit clarifications may make
only the durable edits requested by the clarification and record a concise
summary. Missing, malformed, mismatched, or invalid resolver answers stop the run
without answering the clarification or clearing its resume pointer.

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
