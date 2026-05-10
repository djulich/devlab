# Tooling Policy

## Python

Use:

- `uv` for dependency, lockfile, environment, and command management
- `uv_build` as the build backend
- `ruff` for linting and formatting
- `ty` for static type checking
- `pytest` for testing

Do not introduce alternative Python tooling such as Poetry, Pipenv, tox, mypy, Black, Flake8, or unittest unless explicitly required by an approved task.
