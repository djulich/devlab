# Agent Invocation Observability and Error Handling Plan

## Goal

Make every agent session diagnosable after the fact and make agent failures produce structured `RunResult` / `SessionError` outcomes instead of ad hoc exceptions or exit-code-only messages.

This work covers DevLab's provider invocation boundary: command rendering, subprocess execution, stdout/stderr capture, timeout handling, missing executables, nonzero exits, invalid handoffs, and environment teardown after failures.

## Success Criteria

- Every CLI-backed agent session writes durable stdout and stderr logs under `.devlab/logs/agents/`.
- Failure reports include role, command, timeout, exit code or failure kind, and relevant log paths.
- Subprocess timeouts are converted into structured run failures.
- Missing executables, nonzero exits, and invalid handoffs remain structured `RunResult` failures.
- Environment teardown still runs after agent invocation failures whenever setup succeeded.
- Starter configuration and docs prefer stdin prompt transport where the selected provider supports it.
- Tests cover timeout, missing executable, nonzero exit, invalid handoff, log capture, and teardown-after-failure behavior.

## Non-goals

- Do not implement DevLab's general logging facility from TODO #13 here.
- Do not route agent stdout/stderr through DevLab's own logger; store them as per-session artifacts.
- Do not sandbox agent commands or change the trust model for target-owned executable config.
- Do not add automatic validation command execution.
- Do not persist prompts by default; logs may contain agent output, but prompt text should not be duplicated unless a later explicit debug feature adds it.

## Design

### 1. Treat agent invocation as a structured provider result

Extend `devlab.agents.AgentResult` from only `return_code` to an invocation record:

- `return_code: int`
- `failure_kind: Literal["none", "nonzero_exit", "timeout", "missing_executable", "provider_error"]` or a small string enum
- `message: str`
- `command: tuple[str, ...]`
- `role_name: str`
- `timeout_seconds: int | None`
- `stdout_log: Path | None`
- `stderr_log: Path | None`
- optionally `duration_seconds: float | None`

Keep provider-specific subprocess handling in `agents.py`. The orchestrator should not know how a provider invokes a process; it should only interpret the returned `AgentResult`.

`MockProvider` can keep returning successful minimal results, but tests should be able to construct failures with populated fields.

### 2. Allocate per-session log paths before invoking the provider

Use a deterministic per-session invocation id created by the orchestrator, e.g.:

```text
{timestamp}_{session_number:03d}_{role_name}
```

Log files:

```text
.devlab/logs/agents/{invocation_id}.stdout.log
.devlab/logs/agents/{invocation_id}.stderr.log
.devlab/logs/agents/{invocation_id}.config.toml
```

The existing resolved-agent-config log should be folded into or renamed to the `.config.toml` file so all files for a session share the same prefix. Keep prompt text out of this file.

Recommended config fields:

```toml
role = "developer"
provider = "pi"
model = "gpt-5-codex"
effort = "medium"
uses_stdin = true
timeout_seconds = 3600
command = ["pi", "-p", "--model", "gpt-5-codex"]
stdout_log = ".devlab/logs/agents/20260518T120000_001_developer.stdout.log"
stderr_log = ".devlab/logs/agents/20260518T120000_001_developer.stderr.log"
```

### 3. Pass invocation metadata to providers

Add a small request/context object in `agents.py`, for example:

```python
@dataclass(frozen=True)
class AgentInvocation:
    root: Path
    role_name: str
    system_prompt: str
    session_prompt: str
    invocation_id: str
    stdout_log: Path
    stderr_log: Path
```

Then either:

- change `AgentProvider.invoke(...)` to accept this object, or
- add `invocation_id`, `stdout_log`, and `stderr_log` keyword parameters to the existing protocol.

Prefer the object if the signature keeps growing; update `MockProvider`, tests, and call sites in one pass. Backward compatibility is not required for target projects yet.

### 4. Capture CLI subprocess output directly to files

In `CliAgentProvider.invoke`, open the provided log files and call `subprocess.run` with:

```python
stdout=stdout_handle
stderr=stderr_handle
```

Continue using stdin prompt transport when `stdin_template` is configured:

```python
input=stdin
text=stdin is not None
```

Catch expected subprocess failures inside `CliAgentProvider`:

- `FileNotFoundError` → `failure_kind="missing_executable"`, exit code `127` or DevLab-standard `1`
- `subprocess.TimeoutExpired` → `failure_kind="timeout"`, exit code `124` or DevLab-standard `1`
- unexpected `OSError` → `failure_kind="provider_error"`
- completed process with nonzero return code → `failure_kind="nonzero_exit"`
- zero return code → `failure_kind="none"`

Write a short diagnostic line to stderr log for failures that happen before the child process can write anything, especially missing executable and timeout.

### 5. Let orchestrator map `AgentResult` to `RunResult`

Refactor `invoke_session` to return `AgentResult`, not `int`.

In `run_loop`:

- invoke provider
- always run environment teardown if setup succeeded
- if `AgentResult.failure_kind != "none"`, return `RunResult(..., completed=False, errors=(SessionError(...), ...))`
- include log paths and command details in the `SessionError.message`
- if teardown also fails, include both errors, preserving the agent error as the primary exit code

Suggested `SessionError.phase` values:

- `agent_invocation` for missing executable, timeout, provider error, and nonzero exit
- `handoff_validation` for invalid handoff after a successful agent exit
- existing environment phases remain unchanged

### 6. Make invalid handoff errors include invocation diagnostics

Invalid handoff is not a provider subprocess failure, but it is an agent-session failure from the user's perspective. When validation fails, include the current session's stdout/stderr log paths and config path in the error message.

Do not parse logs to explain the invalid handoff; the handoff parser remains the source of the validation error.

### 7. Prefer stdin prompt transport where supported

Current config already supports `stdin_template`. Update starter config and docs so stdin is the preferred pattern for providers that support it because it:

- avoids argv length limits
- avoids prompt leakage through process listings
- keeps rendered command logs prompt-free

Implementation guidance:

- Use `args` for CLI prompt placeholders and `stdin_template` for stdin prompt transport.
- Keep command/config logs prompt-free regardless of transport.
- Update `.devlab/config/agents.toml` starter comments to put stdin examples first where appropriate.
- Only change the default provider to stdin if the default command is known to support stdin reliably; otherwise keep the default working and document the recommended stdin pattern.

## Implementation Phases

### Phase 1: Data model and provider log capture

Files:

- `src/devlab/agents.py`
- `tests/test_agents.py`

Work:

- Extend `AgentResult`.
- Add `AgentInvocation` or equivalent metadata.
- Update `CliAgentProvider.invoke` to write stdout/stderr logs.
- Catch timeout, missing executable, nonzero exit, and provider errors.
- Update `MockProvider` and test helpers.

Tests:

- CLI provider writes stdout/stderr to given log files.
- Nonzero exit returns structured failure and preserves logs.
- Timeout returns structured timeout failure.
- Missing executable returns structured missing-executable failure and writes diagnostic stderr log.
- Command in `AgentResult` excludes prompts when stdin is used and includes only the actual argv used.

### Phase 2: Orchestrator integration

Files:

- `src/devlab/orchestrator.py`
- `tests/test_orchestrator.py`

Work:

- Generate one invocation id per session.
- Write one config log with the same prefix as stdout/stderr logs.
- Change `invoke_session` to return `AgentResult`.
- Map result failures to `SessionError` / `RunResult`.
- Preserve environment teardown after agent failure.
- Add log path details to invalid handoff errors.

Tests:

- `run_loop` returns structured timeout error.
- `run_loop` returns structured missing-executable error.
- `run_loop` returns structured nonzero-exit error including log paths.
- Invalid handoff error includes log paths.
- Environment teardown runs after agent failure and teardown errors are included if teardown fails.
- Successful sessions still archive handoffs and transition state.

### Phase 3: Configuration and docs

Files:

- `src/devlab/resources/init/config/agents.toml`
- `.devlab/config/agents.toml` if keeping dogfood starter config aligned
- `docs/agent-configuration.md`
- possibly `docs/todo.md`

Work:

- Emphasize stdin prompt transport in starter comments/examples.
- Document per-session log files and failure diagnostics.
- Document that command/config logs intentionally omit prompt text.
- Mark TODO #2 as partially or initially complete after implementation.

Tests:

- Existing init/resource tests continue to pass.
- Add or update prompt/config resource tests if they assert exact starter content.

## Edge Cases

- **Timeout after partial output:** preserve whatever stdout/stderr was written before timeout and append a timeout diagnostic to stderr.
- **Missing executable:** stdout may be empty; stderr should contain a DevLab diagnostic line.
- **Provider test doubles:** `MockProvider` should not need to spawn processes, but should support returning structured failures.
- **External provider exceptions:** catch unexpected exceptions around provider invocation in the orchestrator as `agent_invocation` with `failure_kind="provider_error"` if not already converted by the provider.
- **Concurrent sessions:** not supported yet, but invocation ids should still avoid collisions by including timestamp, session number, role, and existing counter fallback if needed.

## Validation Commands

Run after implementation:

```bash
uv run ruff check
uv run ty check
uv run pytest
uv run devlab doctor
```
