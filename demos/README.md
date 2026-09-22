# DevLab Demonstrations

This directory contains input fixtures, runnable demonstrations, and a controlled
comparison experiment. Use [First workflow](first-workflow/) for a live DevLab
introduction. The larger specifications are inputs for experiments, not examples
of finished software or evidence that a particular run succeeded.

Demo packages are repository-only material used to demonstrate or evaluate
DevLab product characteristics. They are not installed as part of DevLab and are
excluded from both its wheel and source distribution. Run all demo-package
checks from a repository checkout with:

```bash
make -C demos check
```

Available demonstrations:

- [`backtester/`](backtester/) — preserve a substantial desktop backtester
  system/deployment specification pair for complex-workflow experiments.
- [`backtester-web/`](backtester-web/) — preserve the web-based backtester
  system/deployment specification pair.
- [`first-workflow/`](first-workflow/) — run the tutorial's small Python
  workflow from deterministic, resettable inputs using bounded checkpoints.
- [`managed-test-services/`](managed-test-services/) — configure and operate a
  workspace-owned PostgreSQL test service in a disposable target.
- [`system-evolution/`](system-evolution/) — compare DevLab with fresh
  single-agent sessions across an initial full-stack build and a later
  data-preserving specification evolution.

Each demo owns the inputs and instructions applicable to it. Executable demos
also own their graders, grader tests, and retained-evidence protocols. Generic
DevLab workflow evaluation infrastructure remains under `tests/evaluations/`.
