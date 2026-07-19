# Tooling Policy

## Coding Standards

- Prefer readable, explicit code over cleverness.
- Preserve separation of concerns and add focused tests for behavior changes.
- Include a `README.md` with installation and first-usage instructions.

## Python

Use `uv` for dependency and environment management, `uv_build` for builds,
`ruff` for linting and formatting, `ty` for static type checking, `pytest` for
tests, and a `src/` layout for importable package code.

Ignore `.venv/`, `__pycache__/`, `dist/`, `build/`, `*.egg-info`,
`.ruff_cache/`, and `.pytest_cache/`. Include `py.typed` in typed packages.
