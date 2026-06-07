# Logging Facility Plan

Status: initial implementation complete. DevLab uses a single `devlab` logger for `run` workflow output, supports `devlab run --quiet`, `--verbose`, and `--log-file`, includes lightweight session start/finish context, and leaves report/interactive command output as direct prints.

## Motivation

Before the logging facility, DevLab used direct `print()` calls for progress output and error reporting. That had several problems:

- **No level control.** Progress messages, errors, and debug information all go to stdout with no way to filter. A user watching a long run gets workflow state transitions mixed with error messages.
- **No output routing.** Everything goes to stdout. There is no way to send a log to a file while keeping the terminal clean, or to capture structured output for post-run analysis.
- **Library unfriendly.** If DevLab is used as a library (calling `run_loop` programmatically), the caller has no control over output — `print()` writes directly to stdout regardless.

A logging facility would give real-time workflow visibility at configurable verbosity, route output to files for debugging, and let programmatic callers control or suppress output entirely.

## Design

### Use Python's `logging` module

No custom framework. Python's `logging` is well-understood, supports levels, handlers, and formatters out of the box, and integrates with standard tooling.

### Single named logger

All DevLab modules share one logger: `logging.getLogger("devlab")`. Modules use it directly rather than creating per-module loggers — the codebase is small enough that module-level granularity adds complexity without benefit. If finer control becomes necessary later, per-module child loggers (`devlab.orchestrator`, etc.) are a backward-compatible extension.

### Log levels

Map the existing print calls to standard levels:

| Level | Used for | Examples |
|-------|----------|---------|
| `ERROR` | Failures that stop the loop | `ERROR: agent command not found`, `ERROR: Invalid handoff` |
| `WARNING` | Conditions that might indicate problems | (none currently; available for future use) |
| `INFO` | Workflow progress visible during normal runs | `Starting session 3: developer task=T0001 ...`, `Finished session 3: developer task=T0001 status=in_review next=reviewer`, `Milestone M1 marked integrated` |
| `DEBUG` | Diagnostic detail useful for troubleshooting | Resolved agent config paths, handoff validation details, environment setup/teardown steps |

The 6 existing `ERROR:` prefixed prints become `logger.error()`. The ~19 workflow progress prints become `logger.info()`. Visual separators (`===`, `---`) are formatting concerns handled by the log formatter, not the log messages themselves. The 3 `cli.py` prints of formatted command output (`status`, `doctor`, `init`) stay as `print()` — they are command output, not log messages.

### CLI configuration

Add a `--log-level` option (or `-v`/`-q` shorthand) to the `run` subcommand:

| Flag | Level | Behavior |
|------|-------|----------|
| `-q` / `--quiet` | `WARNING` | Errors and warnings only |
| (default) | `INFO` | Workflow progress |
| `-v` / `--verbose` | `DEBUG` | Full diagnostic output |

Add an optional `--log-file PATH` flag that adds a `FileHandler` alongside the console handler, so the user can watch progress on screen while capturing everything to a file.

### Setup location

A `configure_logging()` function in a new `src/devlab/_logging.py` module, called once from `cli.py` before dispatching to commands. This keeps logger setup out of the library code — `run_loop` and other functions just call `logger.info(...)` and the caller decides where output goes.

Library callers who don't call `configure_logging()` get Python's default behavior (no output unless they configure the `devlab` logger themselves).

### Formatter

Console output uses a minimal formatter: `%(message)s` at INFO level (same feel as current print output), `%(levelname)s: %(message)s` at DEBUG level (adds the level prefix for diagnostic context). File output always includes timestamps: `%(asctime)s %(levelname)-5s %(message)s`.

### Session context

Normal run logs include lightweight context at session boundaries without parsing extra handoff prose or computing full workflow diagnostics:

```text
Starting session 5: developer task=T0002 status=open profile=python-app domain=general milestone=M1
Finished session 5: developer task=T0002 status=in_review next=reviewer
```

Role-specific start context is intentionally small:

- developer/reviewer: task id, status, profile, domain, milestone when present
- planner: task/open-finding counts
- integrator: selected milestone and closed task count
- architect: initial design or architecture-review mode

Finish context reports the same task/milestone identity where known plus the next selected role, or `next=complete`. Full historical diagnostics belong in `devlab diagnostics`, not normal run logs.

### Non-interactive run output

Workflow progress is reported through logging; reporting commands that present direct user output remain separate.

## Implementation steps

1. **Create `src/devlab/_logging.py`** with `configure_logging(level, log_file)` and a module-level `logger = logging.getLogger("devlab")`.

2. **Replace prints in `orchestrator.py`** with `logger.info()`, `logger.error()`, and `logger.debug()` calls. Remove visual separator prints (`=` and `-` lines) — the formatter handles visual structure. Keep the interactive handoff preview and `input()` prompt as `print()`.

3. **Update `cli.py`** to call `configure_logging()` based on new `--log-level` / `-v` / `-q` / `--log-file` arguments. The `status`, `doctor`, and `init` command output stays as `print()`.

4. **Add tests** for `configure_logging()` (handler setup, level propagation) and verify that orchestrator log output appears at expected levels.

## Scope boundaries

- This plan covers DevLab's own output. Agent subprocess output (stdout/stderr from invoked agents) is not routed through this logger — agents write to their own streams and log files.
- Per-module child loggers are deferred until there is a concrete need.
- Structured/JSON log output is deferred — plain text is sufficient for now.
