# Tooling

This document defines the default tooling for this workspace. Task metadata may specify task-specific `validation` commands.

## Required

- Primary programming language: `Python` (version >=3.12)
- Python dependency, lockfile, environment, and command management: `uv`
- Build backend: `uv_build`
- Linting and formatting: `ruff`
- Static type checking: `ty`
- Testing: `pytest`
- Version Control: `git`
- Python package structure: `/src` layout

## Default Validation

- `uv run ruff check`
- `uv run ty check`
- `uv run pytest`

## Optional

- Coverage reporting: `coverage.py`
- Local hook enforcement: `pre-commit`
- Development process cli: `make`
