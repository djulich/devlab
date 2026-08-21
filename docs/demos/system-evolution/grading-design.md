# Automatic Grading Design

## Can product quality be evaluated automatically?

Much of the quality relevant to this demo can be evaluated automatically, but
not all of it and not honestly as one magic score.

An external grader can measure:

- REST contract correctness;
- real browser behavior and accessibility basics;
- Compose topology and health;
- nginx/API/PostgreSQL integration;
- persistence across restart;
- migration and generation 1 data preservation;
- stale and concurrent mutation safety;
- target-owned tests and documented commands;
- Git/artifact hygiene; and
- leakage of obvious secrets or internal configuration.

It cannot fully and objectively measure maintainability, architectural clarity,
visual polish, explanation quality, or whether a design will remain pleasant to
change for years. Those require a separate blinded human review or carefully
bounded static proxies. Do not let subjective review alter black-box correctness
results.

## Independence boundary

The grader belongs to DevLab's evaluation environment, not to either generated
product and not to the evaluated workflow. It follows ADR 0011:

- targets never receive grader source, hidden cases, or previous grader output;
- grader failures never become DevLab findings or tasks;
- the grader never resumes a workflow or invokes an agent;
- it never repairs target code, specifications, migrations, or data;
- it treats target-owned tests as evidence but independently rechecks behavior;
  and
- it writes results outside the committed target, or into an explicitly
  evaluator-owned untracked artifact location after grading.

## Proposed program

Implement a Python grading CLI in DevLab's evaluation code, with a thin demo
runner selecting generation 1 or 2. A possible operator interface is:

```text
uv run python -m tests.evaluations.system_evolution_grader \
  --generation 1 \
  --target /path/to/target \
  --compose-project idea-greenhouse-run01-devlab \
  --json-out /path/to/evidence/g1-devlab.json
```

Generation 2 additionally receives a fixture artifact created by the generation
1 seeding step:

```text
  --generation-1-fixture /path/to/evidence/g1-devlab-fixture.json
```

The exact module name and CLI should be decided during implementation. Reuse
small evaluation utilities where their contracts fit, but keep this grader
independent of the generated target's project commands and DevLab workflow
state.

## Grader lifecycle

For each target and generation:

1. Validate inputs and record the immutable target revision.
2. Require a clean target worktree before grading.
3. Allocate a unique Compose project name, host port, temporary artifact
   directory, and randomized test-data prefix.
4. Run non-mutating structural and configuration checks.
5. Build images from the target checkout.
6. Start exactly the target's three-service stack.
7. Wait for health with a bounded deadline.
8. Run public-boundary API and browser checks.
9. Run persistence, migration, and concurrency checks appropriate to the
   generation.
10. Capture bounded Compose status and logs on failure.
11. Stop grader-started containers without deleting the evolution volume.
12. Confirm the target Git worktree remains clean.
13. Write structured JSON plus a concise human report.

Cleanup must be idempotent and scoped by the validated unique Compose project
name. It must never run a broad container or volume deletion.

## Generation 1 checks

### Structure and configuration

- Required source, migration, lockfile, container, Compose, Makefile, and README
  artifacts exist.
- `docker compose config` succeeds.
- Resolved Compose configuration has exactly `db`, `api`, and `frontend`.
- Only frontend publishes a host port.
- The database uses a named volume and the expected service dependencies/health
  checks exist.
- Images/build contexts do not include `.git`, `.devlab`, `.env`, or obvious
  credentials.

### API behavior

- Database-aware health success.
- Empty list/count response.
- Create defaults and normalization.
- Create validation for blank/overlong/wrong-type values.
- Read/list/filter/order/count behavior.
- Partial update and timestamp behavior.
- Stage changes.
- Delete and missing IDs.
- Stable error envelope and correct status classes.
- Randomized Unicode and whitespace cases within the written contract.

### Browser behavior

Using Playwright through the frontend host port:

- load the application without page or severe console errors;
- see empty/loading behavior;
- reject a blank title visibly;
- create an idea and observe it and counts;
- filter and change stage;
- edit it;
- require deletion confirmation;
- delete it; and
- verify accessible names and keyboard reachability for principal controls.

### Deployment and persistence

- API and database are reachable through frontend `/api`, not a host-published
  API port.
- Restart only API and verify data remains.
- Stop/start the stack without volumes and verify data remains.
- Verify all three services return healthy after restart.

### Evolution fixture

After scoring generation 1, create the seed/sprout/bloom fixture through the
public API and save IDs, complete response bodies, target revision, Compose
project, and a content digest in evaluator-owned JSON. Stop without removing the
database volume.

## Generation 2 checks

Run all still-applicable generation 1 checks plus:

### Migration and preservation

- Start generation 2 against the preserved generation 1 volume.
- Fetch every recorded fixture by its original ID.
- Verify original title, notes, stage, `created_at`, and `updated_at` are
  preserved.
- Verify `next_action` and `archived_at` are null and version is 1.
- Verify the Alembic database revision is current.
- Restart API and re-run migration startup safely.
- Separately test an empty clean installation through the full migration chain
  using an isolated temporary Compose project/volume.

### New fields and archive behavior

- Create/edit/clear next actions with trimming and length limits.
- Archive and restore with correct version increments/timestamps.
- Default active filtering excludes archived ideas.
- `active`, `archived`, `all`, and stage combinations return correct items.
- Counts remain global and follow the specified active/archive meanings.
- Invalid archive transitions return the documented conflict.
- Permanent deletion works for active and archived ideas.

### Optimistic concurrency

- Missing, malformed, weak, zero, and negative `If-Match` cases.
- Successful mutation increments version exactly once.
- Sequential stale update, archive, restore, and delete each return `409` and do
  not change stored data.
- Conflict response includes the stable error and current representation.
- Two genuinely concurrent requests use the same version and a synchronization
  barrier; assert exactly one success and one conflict.
- Repeat the concurrent case enough times to make a read-then-write race likely,
  while keeping runtime bounded and results deterministic enough for CI.

### Browser conflict behavior

Use the API to mutate an idea after the page loads, then attempt an edit from the
stale page:

- the UI sends its stale `If-Match` value;
- it shows a visible conflict instead of overwriting;
- unsaved form content remains available;
- Reload current idea displays the server representation; and
- no silent automatic retry occurs.

## Target-owned validation checks

Run documented target commands in addition to black-box grading:

- backend tests;
- frontend tests/build;
- Compose config/build;
- target-owned smoke or deployment check; and
- generation 2 migration/concurrency tests.

Record each command, exit status, duration, and bounded output. A target receives
credit for useful committed tests, but passing self-authored tests never overrides
a failed independent check.

## Result model

Produce versioned JSON with at least:

```json
{
  "schema_version": 1,
  "demo": "system-evolution",
  "generation": 2,
  "target_revision": "...",
  "valid_run": true,
  "invalid_reasons": [],
  "dimensions": {
    "api": {"passed": 20, "failed": 0, "unverified": 0},
    "browser": {"passed": 8, "failed": 0, "unverified": 0},
    "deployment": {"passed": 10, "failed": 0, "unverified": 0},
    "migration": {"passed": 8, "failed": 0, "unverified": 0},
    "concurrency": {"passed": 8, "failed": 0, "unverified": 0},
    "target_validation": {"passed": 5, "failed": 0, "unverified": 0},
    "hygiene": {"passed": 5, "failed": 0, "unverified": 0}
  },
  "checks": []
}
```

Each check should have a stable ID tied to specification requirement IDs,
status (`passed`, `failed`, or `unverified`), duration, concise evidence, and
diagnostic artifact references.

Keep dimensional results visible. If a numeric summary is useful, report both
unweighted pass rate and a predeclared weighted score; never publish only the
weighted score.

## Hard gates and scoring

Some failures invalidate or dominate a result rather than merely subtracting one
point:

- target cannot build or start;
- generation 2 uses a new/empty volume instead of upgrading the fixture;
- migration loses or changes generation 1 records;
- more or fewer than three long-running services are used;
- API or database is published contrary to the deployment boundary;
- concurrent stale writers can both succeed;
- grader or operator manually repaired the target; or
- credentials are committed or exposed in frontend assets.

Report these as named hard-gate failures. Preserve the remaining check results so
the report still explains partial quality.

Do not score DevLab planning history as product correctness. Auditability is a
separate experiment dimension with observations such as durable task provenance,
recorded verification, review/rework cycles, spec-generation archives, and clean
session commits. The single-agent arm can earn analogous auditability evidence
when it commits plans, validation logs, or clear change history voluntarily.

## Human review supplement

After automated grading, a reviewer blind to experiment arm may assess:

- architecture and ownership boundaries;
- migration readability and reversibility limitations;
- test clarity and failure diagnostics;
- frontend usability and visual coherence;
- documentation comprehensibility; and
- unnecessary complexity or scope creep.

Use a predeclared rubric and two reviewers where feasible. Reveal the arm only
after scores are recorded. Keep these results separate from automatic checks.

## Questions to decide before implementation

1. Should the grader invoke Docker only, or support Podman/Compose compatibility
   from the start?
2. Should target-owned `make deployment-check` run before or after independent
   startup, given that both need exclusive Compose project/port ownership?
3. How many concurrent-writer repetitions balance race detection and runtime?
4. Which accessibility checks should be automated with Playwright alone, and
   should axe-core be an evaluator-owned dependency?
5. Should generated image contents be inspected through `docker image save`, or
   should the first grader limit hygiene checks to build context and container
   runtime inspection?
6. What scoring weights, if any, should be fixed before the first run?
7. How should provider token/cost data be normalized when DevLab roles use
   heterogeneous models?

These choices should be settled and committed before observing either arm's
first graded result.
