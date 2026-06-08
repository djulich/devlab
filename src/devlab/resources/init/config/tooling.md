# Tooling Policy

## Coding Standards

- Prefer readable, explicit code over cleverness.
- Preserve separation of concerns: put behavior in the owning module/abstraction and avoid leaking storage formats, external service details, environment assumptions, or workflow rules into unrelated code.
- Add focused tests for behavior changes.
- Add comments/docstrings only when they clarify purpose, contracts, invariants, or design tradeoffs.
- Include a `README.md` with a project overview, installation instructions, and a first-usage example. Create it as part of the project scaffold; keep it current as features are added.

## Python

Use:

- `uv` for dependency, lockfile, environment, and command management
- `uv_build` as the build backend
- `ruff` for linting and formatting
- `ty` for static type checking
- `pytest` for testing
- a `src/` package layout for importable Python package code

Include a `.gitignore` covering standard Python artifacts (`.venv/`, `__pycache__/`, `dist/`, `build/`, `*.egg-info`, `.ruff_cache/`, `.pytest_cache/`). Create it as part of the project scaffold.

Include a `py.typed` marker in the package directory for typed packages.

Do not place importable Python package code directly at the repository root unless explicitly required by an approved task.

Do not introduce alternative Python tooling such as Poetry, Pipenv, tox, mypy, Black, Flake8, or unittest unless explicitly required by an approved task.
