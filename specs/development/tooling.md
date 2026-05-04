# Tooling

This documents defines the tooling decisions made for this project.

## Required

- Primary programming language: `Python` (version >=3.12)
- Python dependency, lockfile, environment, and command management: `uv`
- Build backend: `uv_build`
- Linting and formatting: `ruff`
- Static type checking: `ty`
- Testing: `pytest`
- Version Control: `git`
- Python package structure: `/src` layout

## Optional

- Coverage reporting: `coverage.py`
- Local hook enforcement: `pre-commit`
- Development process cli: `make`
