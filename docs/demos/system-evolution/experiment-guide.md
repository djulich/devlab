# System Evolution Experiment Guide

## 1. Purpose

Run a controlled comparison between:

- DevLab's repository-backed, multi-role workflow; and
- two fresh single-agent coding sessions, one per specification generation.

The primary outcome is independently measured product correctness after each
generation, especially preservation and migration behavior in generation 2.
Secondary outcomes are auditability, validation quality, cost, tokens, elapsed
time, and operator intervention.

## 2. Prerequisites

Install these outside the target repositories:

- Git;
- DevLab and its configured agent providers;
- Docker Engine with Compose v2, or a deliberately selected compatible Compose
  implementation;
- a coding-agent CLI for the single-agent arm;
- host tools required by the future independent grader; and
- a timing and usage-recording method appropriate to the chosen providers.

Do not let DevLab, the generated product, or the grader install missing host
tools. Record a missing prerequisite as unverified.

Use a machine with enough free container storage for two isolated PostgreSQL,
backend, and frontend stacks. Never reuse the same Compose project name or
database volume between arms.

## 3. Fix the experiment controls

Before starting, record in a copy of `evidence-template.md`:

- DevLab commit/version;
- provider, model, reasoning/effort, and permission configuration for every
  DevLab role;
- provider, model, reasoning/effort, and permission configuration for each
  single-agent session;
- maximum session/runtime/token limits;
- container engine and Compose versions;
- operating system and architecture;
- exact grader revision;
- whether network access is available to agents and builds; and
- the rule for counting elapsed time, tokens, and monetary cost.

Prefer the same implementation-capable model for DevLab developer sessions and
the single-agent sessions. If reviewer or planning roles use different models,
report that plainly. Do not describe unequal compute budgets as a pure workflow
comparison.

Run multiple repetitions when drawing general conclusions. Randomize arm order
when practical so registry caches, provider conditions, and operator familiarity
do not systematically favor one arm.

## 4. Prepare identical target repositories

Create two empty directories outside the DevLab source repository, for example:

```text
demo-runs/<run-id>/devlab/
demo-runs/<run-id>/single-agent/
```

Initialize each as an independent Git repository with the same default branch,
Git identity, `.gitignore`, and initial README. Commit this identical baseline.
Record both initial commit IDs and verify their trees are identical.

Use distinct environment files and Compose project names:

```text
COMPOSE_PROJECT_NAME=idea-greenhouse-<run-id>-devlab
COMPOSE_PROJECT_NAME=idea-greenhouse-<run-id>-single
```

Do not commit real credentials or provider configuration.

## 5. Run generation 1: DevLab arm

1. Run `devlab init` in the DevLab target repository.
2. Copy `generation-1/system-spec.md` to the initialized system-spec location,
   normally `.devlab/specs/system/idea-greenhouse.md`.
3. Copy `generation-1/deployment-spec.md` to the deployment-spec location,
   normally `.devlab/specs/deployment/compose.md`.
4. Configure agent providers and profiles outside committed shared evidence when
   they contain machine-specific or secret values.
5. Commit the specifications and safe configuration.
6. Record the starting revision and start time.
7. Run `devlab plan` until planning stops successfully.
8. Inspect only for experiment validity: confirm the workflow did not stop for a
   missing external prerequisite or unresolved clarification. Do not repair its
   plans or product manually.
9. Run `devlab implement` until the workflow completes or reaches the declared
   experiment limit. Continue bounded runs after a normal session-limit stop;
   record each command.
10. Record final workflow state, diagnostics JSON, run summaries, session count,
    commits, tags, logs, and resource usage.
11. Do not edit the target before grading.
12. Run the generation 1 independent grader and retain its machine-readable and
    human-readable reports.

If the workflow requests clarification, answer only from the specification or
the experiment's predeclared policy. Record the question and answer. Do not use
clarification to coach DevLab toward a grader implementation detail that is not
part of the specification.

## 6. Run generation 1: single-agent arm

1. Copy the generation 1 specifications into the single-agent repository under
   a documented `specs/` directory and commit them.
2. Start one fresh agent session using
   `prompts/single-agent-generation-1.md`.
3. Provide the agent the repository and normal tool access, but no DevLab
   artifacts, DevLab role prompts, grader source, grader results, or information
   from the DevLab run.
4. Let the agent work until it declares completion or reaches the predeclared
   limit. Do not provide implementation suggestions or manual fixes.
5. Record the final revision, working-tree status, transcript/log location,
   elapsed time, tokens, cost, and commands run.
6. Do not edit the target before grading.
7. Run the same generation 1 independent grader and retain its reports.

If the agent asks a blocking question, answer under the same rule used for
DevLab clarifications and record the exchange. The answer becomes repository
evidence only if the agent chooses to write it there.

## 7. Seed evolution data

Generation 2 must test migration of real generation 1 state rather than only an
empty schema.

After generation 1 grading, use the generation 1 public API through the frontend
origin to create a grader-owned fixture set in each target:

- one seed idea;
- one sprout idea; and
- one bloom idea.

Use distinct titles with a recorded run ID. Retain the returned IDs, timestamps,
and response bodies. Stop the stacks without deleting their database volumes.

The seeding program must be part of the independent grader, not an agent-authored
target script. Do not seed one arm from a database dump produced by the other.

## 8. Apply generation 2: DevLab arm

1. Replace the authoritative system and deployment specs with the complete
   generation 2 files.
2. Commit only that specification change.
3. Record the pre-reconciliation revision and confirm the generation 1 database
   volume still exists.
4. Run `devlab plan` without bypassing reconciliation.
5. Verify from DevLab's durable reporting that the old generation was archived
   and the architect/planner produced current generation 2 design and task state.
6. Run `devlab implement` to completion or the declared limit, using the same
   continuation policy as generation 1.
7. Record workflow state, diagnostics, summaries, sessions, commits, tags, logs,
   resource usage, and the archived/current planning evidence.
8. Do not manually repair code, migrations, data, plans, or Compose resources.
9. Run the generation 2 grader against the preserved generation 1 volume.

Starting with an empty replacement database invalidates the evolution portion
of the run. Record such a result as invalid, not as a passing clean installation.

## 9. Apply generation 2: single-agent arm

1. Replace the repository's generation 1 specifications with the complete
   generation 2 files and commit only that change.
2. Preserve the generation 1 database volume.
3. Start a fresh agent session using
   `prompts/single-agent-generation-2.md`.
4. Do not provide the generation 1 transcript, hidden summary, DevLab output,
   grader implementation, other arm's result, or manual explanation of the
   existing code. The repository and generation 2 specs are authoritative.
5. Let the agent update and validate the existing product until completion or
   the declared limit.
6. Record revision, working-tree status, transcript/log location, elapsed time,
   tokens, cost, commands, and any questions.
7. Do not manually repair code, migration history, or the database.
8. Run the same generation 2 grader against the preserved generation 1 volume.

## 10. Evidence integrity

The grader is external to both workflows. Never:

- place grader source or hidden cases in a target repository;
- feed grader failures back to DevLab as findings or tasks;
- ask either agent arm to repair the generated target after grading;
- edit temporary targets to determine whether a small fix would pass;
- discard failed runs without recording the declared exclusion reason; or
- compare one arm before migration with the other after a clean reinstall.

Diagnostic investigation may read failed targets and logs after grading. Keep
that analysis separate from the immutable scored revision.

## 11. Report the comparison

Report each repetition independently before aggregates. Include:

- generation 1 and generation 2 functional scores;
- migration/data-preservation score;
- deployment and cross-boundary score;
- committed target-owned test/validation score;
- security and artifact-hygiene findings;
- workflow or session completion status;
- human interventions and clarifications;
- elapsed time, tokens, cost, and number of agent invocations;
- repository commits and worktree cleanliness; and
- auditable planning/review evidence, reported separately from product quality.

Do not combine these into one opaque winner score. A useful conclusion explains
which additional costs bought which measurable quality or auditability gains.
