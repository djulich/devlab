# System Evolution External Grader

This repository-only grader independently evaluates Idea Greenhouse targets. It
is tailored to the generation 1 and generation 2 specifications in the parent
directory and is not part of the installed DevLab product.

Run the implemented generation 1 foundation from the DevLab repository root:

```bash
uv run python demos/system-evolution/grader/system_evolution_grader.py \
  --generation 1 \
  --target /path/to/clean/target \
  --compose-project idea-greenhouse-run01 \
  --json-out /path/to/evidence/generation-1.json
```

Generation 1 also writes `/path/to/evidence/generation-1-fixture.json` and
`/path/to/evidence/generation-1-resume.json` by default. Override those locations
with `--generation-1-fixture-out` and `--generation-1-resume-out`. The fixture is
shareable grading evidence. The resume file contains randomized evaluator
database credentials, is created with mode `0600`, and must remain private. The
grader refuses to replace either artifact or write it inside the target checkout.

The target must be a clean Git checkout. Docker Engine with Compose v2 is an
external prerequisite. The grader allocates a host port and randomized test
data, builds and starts exactly the target's `db`, `api`, and `frontend`
services, exercises generation 1 API and browser behavior through the frontend
origin, verifies persistence, and writes versioned dimensional JSON. Browser
checks use a pinned evaluator-owned Playwright container and an absolute package
path, never target dependencies. They cover loading/runtime errors, the empty
state, blank-title validation without an API request, creation/counts, stage and
filter behavior, editing, identified deletion confirmation, accessible names,
keyboard focus, and exposed filter selection. After removing its temporary
persistence probe, it creates one seed, sprout, and bloom through the public API
and records their complete responses, target revision, Compose project, and a
canonical SHA-256 digest. Every Compose mutation is scoped to the validated
project name. Cleanup stops only that project and never deletes its database
volume.

Run the implemented Generation 2 migration/preservation checks against the same
Compose project and preserved volume:

```bash
uv run python demos/system-evolution/grader/system_evolution_grader.py \
  --generation 2 \
  --target /path/to/updated-clean-target \
  --compose-project idea-greenhouse-run01 \
  --generation-1-fixture /path/to/evidence/generation-1-fixture.json \
  --generation-1-resume /path/to/evidence/generation-1-resume.json \
  --json-out /path/to/evidence/generation-2.json
```

The grader verifies both artifact digests and the Compose-project identity before
touching Docker. It refuses a missing replacement volume, restores the evaluator
database configuration, starts Generation 2 in place, checks every preserved
field and new default, verifies Alembic is at head, restarts the API, and repeats
the preservation checks. It then uses uniquely prefixed temporary records to
check next-action normalization and validation, archive/restore transitions,
global counts and archive/stage filters, and versioned deletion of active and
archived ideas. Temporary records are removed with their current versions;
cleanup failures are reported as grader errors. The grader also checks the full
expected-version syntax/status matrix, mutation-error precedence, sequential
stale update/archive/restore/delete safety, and eight synchronized two-writer
races that must each produce one success and one conflict. A separate
Generation 2 Playwright flow creates an evaluator probe, opens a stale edit,
mutates the server representation through the frontend `/api` boundary, and
checks visible conflict recovery, preservation of unsaved title and notes,
explicit reload, the stale quoted `If-Match`, and absence of a silent retry. It
removes the probe with the latest server version even when the browser check
fails.

The grader never invokes agents, repairs targets, creates DevLab findings, or
feeds results back into a workflow. Product failures, unavailable prerequisites,
and grader failures remain distinct results.

Run its fast safety and result-model tests directly with:

```bash
make -C demos check
```

The complete fixed grading contract and deferred checks are documented in
`../grading-design.md`.
