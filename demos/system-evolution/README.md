# System Evolution Demo

This demo compares DevLab with ordinary single-agent coding sessions while a
small full-stack product evolves across two authoritative specification
generations.

The product is **Idea Greenhouse**, a PostgreSQL-backed application for moving
ideas through `seed`, `sprout`, and `bloom` stages. Generation 1 establishes a
working React/API/database system deployed as three Compose services.
Generation 2 changes the existing system by adding next actions, archiving, and
optimistic concurrency without losing generation 1 data.

The comparison is intended to test a specific claim:

> DevLab's durable planning, bounded implementation/review sessions, and
> specification reconciliation produce more reliable and auditable software
> evolution than handing each complete specification generation to one fresh
> coding-agent session.

It does not assume that DevLab is faster or cheaper. Report quality, cost,
elapsed time, and agent usage separately.

## Contents

```text
generation-1/
  system-spec.md
  deployment-spec.md
generation-2/
  system-spec.md
  deployment-spec.md
prompts/
  single-agent-generation-1.md
  single-agent-generation-2.md
experiment-guide.md
evidence-template.md
grading-design.md
grader/
  README.md
  system_evolution_grader.py
  test_system_evolution_grader.py
```

Both generation 2 specifications are complete authoritative desired-state
specifications. Their change-summary sections are navigation aids, not a
substitute for the full contract.

## Experiment arms

### DevLab arm

DevLab receives generation 1, plans and implements it to completion, then
receives generation 2 as a committed specification change. Normal spec
reconciliation must update the design and project plan before implementation
continues.

### Single-agent arm

One agent session receives generation 1 and implements it. After independent
grading, a fresh agent session with no transcript from the first receives the
existing repository and the complete generation 2 specifications and updates
the product.

The two arms use the same starting repository, specifications, available host
tools, external grader, and prohibition on manual repair.

## Status

The documentary protocol and specifications are ready. The first-version grader
choices are fixed in `grading-design.md`: Docker Compose v2, evaluator-owned
Playwright without axe-core, eight synchronized concurrency repetitions,
lightweight image/runtime inspection, dimensional results without a weighted
score, and isolated target-owned deployment checks.

The grader implements the versioned result model, scoped Compose lifecycle,
structural/topology checks, core generation 1 API checks, evaluator-owned
Playwright browser/accessibility checks, and restart persistence checks.
Generation 1 fixture seeding and generation 2 migration/concurrency grading
remain subsequent slices. See `grader/README.md` for its current interface and
boundaries.
