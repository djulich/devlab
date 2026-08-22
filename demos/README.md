# DevLab Demonstrations

Each subdirectory is a self-contained, reproducible demonstration or comparative
experiment. It contains the authoritative input specifications, execution
protocol, comparison controls, evidence format, and grading design needed to run
that demonstration without relying on conversational context.

Demo packages are repository-only material used to demonstrate or evaluate
DevLab product characteristics. They are not installed as part of DevLab and are
excluded from both its wheel and source distribution. Run all demo-package
checks from a repository checkout with:

```bash
make -C demos check
```

Available demonstrations:

- [`system-evolution/`](system-evolution/) — compare DevLab with fresh
  single-agent sessions across an initial full-stack build and a later
  data-preserving specification evolution.

Each demo owns its specifications, instructions, executable graders, grader
tests, and retained-evidence protocol. Generic DevLab workflow evaluation
infrastructure remains under `tests/evaluations/`.
