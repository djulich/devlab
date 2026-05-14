# Tooling Policy

## Coding Standards

- Prefer readable, explicit code over cleverness.
- Preserve separation of concerns: put behavior in the owning module/abstraction and avoid leaking storage formats, external service details, environment assumptions, or workflow rules into unrelated code.
- Add focused tests for behavior changes.
- Add comments/docstrings only when they clarify purpose, contracts, invariants, or design tradeoffs.

## Python

Use:

- `uv` for dependency, lockfile, environment, and command management
- `uv_build` as the build backend
- `ruff` for linting and formatting
- `ty` for static type checking
- `pytest` for testing
- a `src/` package layout for importable Python package code

Do not place importable Python package code directly at the repository root unless explicitly required by an approved task.

Do not introduce alternative Python tooling such as Poetry, Pipenv, tox, mypy, Black, Flake8, or unittest unless explicitly required by an approved task.
