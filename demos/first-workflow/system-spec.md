# Hello DevLab System Specification

## Goal

Create a small Python command-line application named `hello-devlab` that greets
one person. This is a learning project, so keep the implementation simple.

## Behavior

- Running `uv run hello-devlab Ada` prints exactly `Hello, Ada!`.
- The command accepts one required name argument.
- When the name is missing, the command exits unsuccessfully and shows usage
  information.

## Quality requirements

- Use a `src/` package layout.
- Add focused pytest tests for successful and missing-name behavior.
- Keep the project compatible with Python 3.12 or newer.
- Document installation and first usage in the project `README.md`.

## Acceptance criteria

- `uv run hello-devlab Ada` prints `Hello, Ada!` followed by a newline.
- `uv run pytest` passes.
- `uv run ruff check` passes.
- `uv run ty check` passes.
