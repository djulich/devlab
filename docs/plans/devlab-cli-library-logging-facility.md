# DevLab CLI and Library Logging Facility Plan

## Goal

Implement TODO #13 by replacing DevLab workflow progress/error `print()` calls with Python standard logging, while preserving command output and interactive prompts as direct user-facing output.

This improves:

- CLI verbosity control for `devlab run`.
- Optional durable DevLab run logs via `--log-file`.
- Library embedding: callers can configure or silence the `devlab` logger instead of receiving unavoidable stdout writes.

This does **not** replace per-session agent stdout/stderr capture in `.devlab/logs/agents/`.

## Scope

In scope:

- Add a single `devlab` logger using Python's `logging` module.
- Add logging configuration for `devlab run` only.
- Replace orchestrator workflow progress/error prints with logger calls.
- Keep `init`, `status`, and `doctor` formatted reports as `print()` output.
- Keep interactive handoff preview and `input()` prompt as direct terminal output.
- Add tests for logging setup and run-loop log-level behavior.

Out of scope:

- JSON/structured logging.
- Per-module child loggers.
- Routing agent subprocess stdout/stderr through DevLab logging.
- Persisting prompts in logs.
- Replacing user-facing report formatting with logs.

## Design decisions

### Logger

Create `src/devlab/_logging.py`:

- `logger = logging.getLogger("devlab")`
- `configure_logging(level: int, log_file: Path | None = None) -> None`

Library code imports and uses this logger. Library callers that do not call `configure_logging()` get normal Python logging behavior and can configure the logger themselves.

### Handler behavior

`configure_logging()` should be idempotent for CLI use:

- Remove handlers previously installed by DevLab's `configure_logging()` to avoid duplicate output in repeated test/library calls.
- Do not disturb non-DevLab handlers that an embedding application may have installed unless they are clearly marked as DevLab-owned.
- Set `logger.propagate = False` after installing DevLab handlers so CLI logs do not duplicate through the root logger.

Implementation detail: mark DevLab-owned handlers with a private attribute such as `_devlab_owned = True`.

### Formatting

Console handler:

- default/info mode: `%(message)s`
- debug mode: `%(levelname)s: %(message)s`

File handler:

- always include timestamp and level: `%(asctime)s %(levelname)-5s %(message)s`
- use UTF-8 text mode
- create parent directories for `--log-file`
- capture DEBUG and above in the file unless a stronger reason emerges to mirror console level exactly

Recommended behavior: console level follows CLI verbosity, file level is `DEBUG` so `--log-file` captures diagnostics even when terminal output is quiet.

### CLI flags

Add to `devlab run`:

- `-q`, `--quiet`: console level `WARNING`
- default: console level `INFO`
- `-v`, `--verbose`: console level `DEBUG`
- `--log-file PATH`: add a file handler

Use a mutually exclusive group for quiet/verbose. Avoid adding logging flags to `init`, `status`, and `doctor` until there is a concrete need.

Potential future extension: `--log-level LEVEL`, but do not add it now unless tests/users show shorthand is insufficient.

### Log level mapping

Use levels consistently:

- `ERROR`: failures that stop the loop.
- `WARNING`: abnormal but non-fatal conditions; none expected initially.
- `INFO`: normal workflow progress visible during `devlab run`.
- `DEBUG`: diagnostics useful for troubleshooting, especially paths and configuration side effects.

Current orchestrator output mapping:

- `invoke_session`: `INFO` for invoke start/exit.
- `run_loop` session selection: `INFO` without decorative separator lines.
- environment setup/teardown start: `INFO`; detailed command logs remain in environment log files.
- no eligible task / all complete / stopping / finished: `INFO`.
- profile/environment/agent/handoff errors: `ERROR`.
- handoff archived, task transitions, milestone transitions, finding creation: `INFO`.
- resolved agent config log path and generated agent log paths: `DEBUG`.

Keep these as direct output:

- interactive handoff preview block in `auto=False`
- `input("Continue? [Y/n]: ")`
- `Stopped by user.` can remain direct output because it is part of the interactive prompt flow, or become `INFO`; prefer direct output for consistency with the prompt.

## Implementation phases

### Phase 1: Logging module and CLI wiring

1. Add `src/devlab/_logging.py`.
2. Add unit tests, likely `tests/test_logging.py`, covering:
   - default console handler setup at `INFO`
   - quiet and verbose levels
   - `--log-file` parent creation and timestamped file output
   - repeated `configure_logging()` calls do not duplicate DevLab-owned handlers
3. Update `src/devlab/cli.py`:
   - add `run` verbosity flags
   - add `--log-file`
   - call `configure_logging()` only for `args.command == "run"` before `run_loop()`
4. Add CLI argument tests if current CLI tests can inspect behavior cheaply.

### Phase 2: Orchestrator conversion

1. Import `logger` from `devlab._logging` in `src/devlab/orchestrator.py`.
2. Replace non-interactive `print()` calls with logger calls.
3. Remove decorative separator prints rather than logging them.
4. Keep interactive preview and prompt prints unchanged.
5. Add/adjust orchestrator tests using `caplog` or a configured stream handler to verify:
   - default/info logs include session selection and completion progress
   - quiet mode suppresses progress but still emits errors
   - verbose/debug mode includes diagnostic paths such as config/stdout/stderr log paths
   - `run_loop()` itself does not configure logging

### Phase 3: Documentation and TODO update

1. Update `docs/devlab-todo.md` item #13 to `initial implementation complete` once implemented.
2. Update user-facing docs if present; at minimum update `docs/agent-configuration.md` or add a short logging section elsewhere if a better user docs file exists by then.
3. Clarify that DevLab run logs are separate from `.devlab/logs/agents/` agent subprocess logs.

## Test strategy

Run:

```bash
uv run ruff check
uv run ty check
uv run pytest
uv run devlab doctor
```

Focused behavior tests:

- `configure_logging(logging.INFO)` writes `INFO` to console stream with message-only format.
- `configure_logging(logging.WARNING)` suppresses `INFO` and emits `ERROR`.
- `configure_logging(logging.DEBUG)` prefixes console output with level name.
- `configure_logging(..., log_file=path)` writes DEBUG+ messages to the file and creates parent directories.
- Reconfiguring does not duplicate messages.
- `devlab run --quiet` suppresses progress logs.
- `devlab run --verbose` includes DEBUG diagnostics.
- `devlab status`, `devlab doctor`, and `devlab init` continue to print their formatted command output without requiring logging setup.

## Risks and mitigations

- **Breaking tests that assert stdout text.** Update tests to capture logs for workflow progress while preserving stdout assertions for report commands and interactive preview.
- **Duplicate logs in embedded use.** Mark and replace only DevLab-owned handlers; document that library callers can configure `logging.getLogger("devlab")` directly.
- **Quiet mode hiding important terminal information.** Use `ERROR` for stop conditions so quiet mode still surfaces failures.
- **Log file accidentally containing prompts.** Do not log prompt text. Debug logs may include paths, role names, command shape, and failure metadata only.
- **Confusion with agent logs.** Documentation and messages should call DevLab logs `run logs` or `DevLab logs`, while agent stdout/stderr logs remain per-session agent diagnostics under `.devlab/logs/agents/`.
