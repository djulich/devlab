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

The target must be a clean Git checkout. Docker Engine with Compose v2 is an
external prerequisite. The grader allocates a host port and randomized test
data, builds and starts exactly the target's `db`, `api`, and `frontend`
services, exercises generation 1 API and browser behavior through the frontend
origin, verifies persistence, and writes versioned dimensional JSON. Browser
checks use a pinned evaluator-owned Playwright container and an absolute package
path, never target dependencies. They cover loading/runtime errors, the empty
state, blank-title validation without an API request, creation/counts, stage and
filter behavior, editing, identified deletion confirmation, accessible names,
keyboard focus, and exposed filter selection. Every Compose mutation is scoped
to the validated project name. Cleanup stops only that project and never deletes
its database volume.

The grader never invokes agents, repairs targets, creates DevLab findings, or
feeds results back into a workflow. Product failures, unavailable prerequisites,
and grader failures remain distinct results. Generation 2 is accepted by the
CLI only to reserve its interface and is explicitly unverified until fixture,
migration, and concurrency grading is implemented.

Run its fast safety and result-model tests directly with:

```bash
make -C demos check
```

The complete fixed grading contract and deferred checks are documented in
`../grading-design.md`.
