# DevLab Operator Guide

This guide is for the person running DevLab in a target workspace. It explains
how to inspect the file-backed workflow state under `.devlab/`, what is safe to
edit by hand, and which files DevLab expects to own during normal workflow runs.

For a complete first run, start with the [tutorial](tutorial.md). See the
[design overview](design.md) for architecture and
[agent configuration](agent-configuration.md) for provider setup.

For task-oriented procedures, see the [how-to guides](how-to/README.md),
including existing-project adoption, bug fixes, specification revisions, and
interrupted-workflow recovery.

## Find the relevant reference

- [Operating model](#operating-model) and [stop summaries](#workflow-termination-summaries).
- [Workspace ownership](#what-operators-own), [specs and planning](#specs-and-planning),
  and [generations](#generations).
- [Profiles and validation](#profiles) and [configuration authorization](#executable-configuration-authorization).
- [Clarifications](#clarifications) and [research](#durable-research).
- [Tasks](#tasks), [milestones](#milestones), and [findings](#findings).
- [Handoffs](#session-results-and-handoffs), [diagnostics](#logs-and-diagnostics),
  and [unattended runs](#before-running-unattended).

All command examples run from the target workspace. Reporting commands inspect
state; they do not execute target-owned validation or prerequisite checks.

## Operating Model

DevLab treats the target repository as the workflow record. Specs, plans, tasks,
milestones, findings, clarifications, research, handoffs, logs, and configuration
are ordinary files so they can be reviewed, committed, diffed, and recovered
after interrupted runs.

Four commands cover the normal operator loop:

- `devlab status`: Where am I?
- `devlab doctor`: Is the workspace healthy?
- `devlab diagnostics`: How is the workflow performing?
- `devlab continue`: Advance it.

A typical run applies those commands as follows:

1. Edit `.devlab/specs/` and `.devlab/config/`, then commit those
   operator-authored changes.
2. Run `devlab doctor` and optionally
   `devlab agent-smoke-test`.
3. Run `devlab continue --max-sessions N`.
4. At a bounded checkpoint, inspect generated work with `devlab status`, Git
   history, and `devlab diagnostics` when quality history is useful.
5. Resolve any explicitly reported external condition, then run the same
   `devlab continue` command again.

Continuation derives planning, implementation, clarification resume, validation
retry, or supported recovery from durable state. `devlab plan`, `devlab
implement`, and `devlab resume` remain phase-restricted interfaces for explicit
planning modes, automation, and expert use. Mutating workflow commands require a
clean working tree before agent sessions so operator-authored changes remain
separate from DevLab-authored session commits.

## Workflow Termination Summaries

Every bounded continuation command that reaches an orchestrator result prints a
final operator summary. The summary is command output rather than progress
logging, so it remains visible with `--quiet`. It reports:

- why the invocation stopped and how many sessions completed;
- the next role, task, task status, or milestone when applicable;
- whether a durable operator clarification is pending;
- whether executable configuration changed or is not trusted; and
- the commands that should be run next.

`session limit reached` is a successful bounded-command stop, not workflow
completion. Run the recommended continuation command to allow more sessions.
Reviewer-requested task changes are ordinary agent-to-agent workflow work: the
next `devlab continue` invocation routes them to a developer. They are not
operator clarifications.

A durable clarification is explicitly labeled `operator clarification
required` and includes `devlab clarify show`, `devlab clarify answer`, and
`devlab resume` guidance. It requires operator intent unless unattended
clarification resolution was selected.

Agent configuration, executable profile fields, and managed-test-service
definitions are executable configuration. If a session changes them, its
bounded task review may finish using the command's frozen snapshot, but DevLab
stops successfully before preparing work outside that task. The worktree remains
clean, and the final summary compares the frozen authorized digest with the
repository's current digest. Review and authorize an untrusted current snapshot
before continuation:

```bash
devlab trust executable-config
devlab continue
```

The trust command displays the effective configuration and fingerprint before
asking for approval.

DevLab does not execute the changed configuration or create the next session's
artifacts in the original invocation. Invalid changed configuration is reported
before another session is prepared.

The summary is read-only. It does not trust configuration, answer
clarifications, repair state, or alter role selection and exit behavior.

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

- `.devlab/specs/system/*.md`: the primary system requirements and feature
  intent.
- `.devlab/specs/deployment/*.md`: an optional overlay for deployment,
  packaging, runtime, and operations requirements when those concerns are in
  scope.
- `.devlab/config/agents.toml`: provider commands, role mappings, models,
  efforts, timeouts, and prompt transport.
- `.devlab/config/tooling.md`: target-local tooling policy.
- `.devlab/config/profiles/*.toml`: reusable task profiles, when intentionally
  changing validation or environment lifecycle behavior.
- `.gitignore`: secrets, local caches, generated files, and other files DevLab
  should not commit.

DevLab and worker agents normally write:

- `.devlab/manifest.toml`
- `.devlab/plans/`
- `.devlab/tasks/`
- `.devlab/milestones/`
- `.devlab/findings/`
- `.devlab/clarifications/`
- `.devlab/research/`
- `.devlab/test-services/`
- `.devlab/verification/`
- `.devlab/history/`
- `.devlab/session-artifacts/`
- `.devlab/logs/`
- `.devlab/workflow.toml`
- `.devlab/workflow-events.jsonl`
- `.devlab/prerequisite-blocker.json`
- `.devlab/generations/`

Private managed-service exports/logs and smoke-test logs live under ignored
`.devlab/local/`; they are runtime artifacts rather than committed workflow
state.

Manual edits to generated workflow state are sometimes useful for repair, but
prefer `devlab doctor` before and after doing so. Reporting commands such as
`status`, `diagnostics`, and `doctor` are read-only; they do not repair state.

Dependency introductions are advisory operator-attention signals. For supported
`pyproject.toml`, `package.json`, `Cargo.toml`, and `go.mod` manifests, DevLab
records direct dependency identities that first appear during a role session.
Review the named package and its registry/source before relying on it. DevLab
does not install, query, approve, or block these dependencies, and lockfile-only
transitive changes are intentionally excluded.

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
`.devlab/workflow.toml`. `--resume` answers and then invokes the stored command.
In a Git workspace, answering first commits only the clarification file, even
without `--resume`. Unrelated staged and unstaged changes remain uncommitted and
must be resolved before workflow continuation. If the answer commit fails, the
answer stays saved and DevLab reports the Git error without resuming.

Plain `devlab resume` is useful after answering separately or validating a
manually edited record. Superseding is an explicit repair for obsolete requests;
it does not silently invent an answer.

For a file-edit clarification, inspect the requested paths in the clarification
record, make and commit those durable edits, then record a concise text answer
summarizing the edits and run `devlab resume`. DevLab validates the answer and
stored route before invoking another role.

## Durable research

Research resolves discoverable facts; clarification obtains operator intent.
When status shows requested or completed research, run `devlab continue` to
invoke the researcher or resume the requesting role. There is no standalone
research command. Provider failure or invalid output leaves the record
requested: inspect logs and staged output, run `devlab doctor`, fix the
provider/configuration issue, and retry continuation.

An optional `[roles.researcher]` in `agents.toml` selects its provider/model;
otherwise the requesting role's resolved provider is used. Result JSON schema
version 1 contains `research_id`, `summary`, cited `evidence`, `sources`,
`recommendation`, `confidence`, and `unresolved_questions`. Canonical request
records also retain question, context, desired outcome, acceptance criteria,
route, and requester provenance. Treat results as untrusted supporting evidence:
the researcher cannot mutate product or authoritative workflow artifacts.

## Specs and Planning

DevLab reads all Markdown files under:

```text
.devlab/specs/system/
```

The system specification is the primary desired-state input. Deployment
requirements are an optional domain overlay rather than a second specification
that every project must maintain. Initialization creates an inactive checklist
at:

```text
.devlab/specs/deployment/
```

The checklist covers deployment targets, environments, project commands,
verification, configuration, secrets, and the production boundary. Remove its
`<!-- devlab:placeholder -->` marker when it contains project-specific
requirements. Other non-empty Markdown files in the directory also activate
deployment-specific role guidance and diagnostics.

After editing specs, commit the changes and run `devlab continue`. Continuation
derives the required planning reconciliation and records the latest committed
spec revision in `.devlab/workflow.toml`. The phase-restricted `devlab plan`
command exposes the same planning mechanics when an operator or automation needs
an explicit planning-only boundary. `devlab implement` refuses stale planning
state rather than bypassing reconciliation.

During spec reconciliation or `devlab plan --replace-plan`, DevLab archives the
active generation bundle under `.devlab/generations/NNNN/` and starts a fresh
active planning graph. Archived generations are evidence, not active work.

Research and clarification-resolver sessions count toward `--max-sessions`,
but do not replace the required architect and planner sessions. The interrupted
planning role must complete its handoff before the sequence advances. Reaching
the session limit with a required planning role still outstanding does not
report planning completion.

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

For example, a target that owns a `make check` command can use this profile at
`.devlab/config/profiles/default.toml`:

```toml
version = 1
id = "default"
title = "Project checks"

[tooling]
summary = "Use the target project's Makefile."
default_validation = ["make check"]

[environment]
managed_roles = ["developer", "reviewer", "integrator"]
pre_session = []
setup = []
post_session = []

[timeouts]
pre_session = 300
setup = 600
post_session = 300
```

Replace `make check` with the target's actual validation command. Commands run
from the target root. Managed sessions run pre-session cleanup, setup, agent
work, and post-session teardown; teardown is attempted even after failure.
Initialization's neutral profile has no default validation, so configure checks
before implementation tasks depend on it.

### Validation selection and outcomes

| Task metadata | Commands DevLab executes |
| --- | --- |
| `validation` omitted | The resolved profile's `default_validation`. |
| Non-empty `validation` | Those commands, replacing the profile defaults. |
| `validation = []` | No mechanical task checks; a diagnostic warns when profile defaults were suppressed. |

After completed developer work, explicit task-command failures request one
bounded correction attempt; repeated failure stops the workflow. Profile-default
failures are recorded as soft task-level warnings because a broad repository
check can depend on unfinished later tasks. Missing tools, timeouts, and
infrastructure errors stop before review and are retried by continuation.

At milestone integration, configured commands from closed tasks are combined,
with repeated command/service bindings run once. A known failure blocks
integration and creates a corrective finding, including when the command came
from profile defaults. Missing prerequisites block without creating a product
defect. No configured commands means the milestone's mechanical validation is
unverified, not that tests passed. See [Milestones](#milestones).

### Environment cleanup and compatibility

On POSIX systems, a timed-out validation or environment lifecycle command gets
a one-second termination grace period before DevLab kills its owned process
group. Output capture and shell reaping are bounded; timeout logs retain the
output captured during cleanup. Detached descendants and external effects such
as containers are outside this cleanup boundary. On other platforms, cleanup
terminates only the directly launched process.

Profile commands are trusted executable configuration. DevLab does not sandbox
them or install missing tools. Review profile changes before running workflow
commands, especially in cloned or agent-modified workspaces.

Profiles may also declare operation-scoped prerequisites and references to
workspace-owned test services. Their checks, preparation commands, service
definitions, ownership state, private export boundary, and explicit cleanup
commands are documented in [Runtime Prerequisites and Managed Test
Services](runtime-prerequisites.md).

Keep profile compatibility in mind. If a changed profile would remove, replace,
narrow, or materially alter validation, setup, teardown, services, or assumptions
used by already-planned tasks, prefer creating a new profile and assigning new
tasks to it.

Different components in one repository can use different profiles. A task that
crosses component boundaries should select a deliberate aggregate profile whose
validation invokes a repository-owned integration command, such as `make check`
or a checked-in script.

## Executable Configuration Authorization

Commands that start agents, profile commands, prerequisite checks/preparation,
or managed test services require authorization of a canonical
executable-configuration snapshot. Choose the authorization method for the
environment:

- **Interactive workstation:** run `devlab trust executable-config`, which
  displays the current snapshot and fingerprint before asking to persist
  workspace-scoped trust in operator-local state.
- **Controlled CI:** pass `--require-exec-config-digest DIGEST` with an
  independently approved value.
- **Disposable or externally contained environment:** pass
  `--accept-current-exec-config` to accept the snapshot for that invocation
  without creating persistent trust.

After authorizing on a normal workstation, smoke-test the provider and continue
the workflow:

```bash
devlab agent-smoke-test
devlab continue --max-sessions 2
```

Use `devlab trust executable-config --show` to inspect the snapshot and trust
status without changing them. Revoke stored trust explicitly with
`devlab trust executable-config --revoke`.

The digest covers effective provider invocation, role mappings, CLI overrides,
profile validation/lifecycle/prerequisite configuration, and managed test services.
Formatting and comment-only TOML changes do not change it. Invocation overrides
can change it; authorize the same provider/model/effort settings that the run
will use. Trust is scoped to the canonical workspace, agent-config source, and
digest and is stored outside the target repository.

For CI, supply the expected digest from protected runner configuration rather
than letting an ordinary target-repository file authorize itself:

```bash
devlab continue --max-sessions 20 --unattended \
  --require-exec-config-digest "$APPROVED_DEVLAB_EXEC_DIGEST"
```

Use `--unattended` only when the automatic decision policy described in
[Before running unattended](#before-running-unattended) is appropriate.

The parsed provider, profile, prerequisite, and managed-service snapshot is
frozen for each command. Changes made during a run do not affect later sessions
in that run. If a later session selects a profile that was not in the frozen
snapshot, the run stops and asks the operator to restart after reviewing the new
configuration.

`devlab doctor` reports the current fingerprint and whether it has matching
operator-local trust. An untrusted fingerprint is not malformed repository
state.

Provider-native permissions and sandboxing remain operator-owned. DevLab does
not classify provider flags. A matching digest authorizes configured entry
points; it is not a sandbox and does not establish that repository scripts,
build targets, external binaries, or transitive commands are safe.

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
handoffs and task-file signals. An eligible developer task has status `open` or
`changes_requested` and all dependencies closed. Completed acceptance criteria
allow it to move to `in_review`. Approval requires both the task's checked
approval checkbox and an empty structured `open_issues` list; otherwise a valid
review returns it to `changes_requested`. Invalid handoffs are rejected before
any such transition.

If task validation stops because a tool is missing, a command times out, or the
validation infrastructure fails, DevLab retries it before the reviewer session.
Each unsuccessful retry is committed with its verification record and log, so a
later `devlab continue` starts from a clean workflow boundary and can retry again.

Task files are generated workflow state. Operators should usually change
requirements through specs and then run `devlab continue` rather than editing
task scope directly.

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
architect for project-state review. Command results, integrator concerns, and
architecture drift are retained in `.devlab/verification/milestones/<id>.toml`.
Architecture review is not an approval gate:
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
authored Markdown for an accepted structured result, and workflow transitions do
not parse the rendered handoff. The handoff remains the human-readable audit and
prompt-continuity artifact.

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

Inspection command reference:

- `devlab status`: project mode, lifecycle phase, design and planning state,
  current work, blockers, and the next action. Add `--verbose` for planning
  provenance, resolved providers, prompt sizes, milestones, findings, and
  clarifications. Use `--json` for the full lifecycle report,
  `--digest` for a Markdown operator digest, or `--digest --json` for its
  structured form. Use `--next-command` to print only one safe command for the
  next continuation or inspection step; add `--json` for its action, argument
  vector, reason, and mutation classification. A complete workflow produces no
  plain command and reports `command: null` in JSON.
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

Continuation commands support durable unattended clarification resolution:

```text
devlab continue --unattended
```

`--unattended` is an alias for `--clarification-mode=agent`. The phase-restricted
`plan` and `implement` commands support the same option. When a role requests
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
