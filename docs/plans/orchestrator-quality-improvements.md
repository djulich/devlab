# Plan: Orchestrator Quality Improvements

Status: **mostly implemented; a few cleanup/design follow-ups remain**.

This plan is a historical quality-improvement checklist for `src/devlab/orchestrator.py` after the logging, handoff extraction, agent invocation, evaluation, version-control, and session-context work. Keep `docs/todo.md` as the canonical cross-project backlog; this file tracks orchestrator-specific cleanup candidates and the status of previously identified weaknesses.

## Current state summary

The orchestrator is in a healthier state than when this plan was created:

- Agent invocation now catches explicit `ProviderError` only; provider implementations convert expected operational failures into structured `AgentResult` values.
- Per-session identity/log paths/prompt-log handling live in `SessionContext`.
- Session start/finish log formatting lives in `src/devlab/session_logging.py` rather than inline in the workflow loop.
- Reviewer outcome mismatch handling is intentionally lenient: contradictory reviewer signals no longer invalidate the handoff; they default the task to `changes_requested` and log a warning.
- Handoff parsing is no longer duplicated for normal processing: `run_loop` parses and validates the handoff once, then passes the parsed `Handoff` to `process_handoff`.
- Shared test helpers exist in `tests/helpers.py` for handoff text, task creation, acceptance completion, and review approval.

Validation baseline at the time this plan was refreshed:

```text
uv run ruff check      OK
uv run ty check        OK
uv run pytest -q       277 passed, 4 skipped
uv run devlab doctor   OK
```

## Resolved items

### 1. Narrow broad exception handling around agent invocation

Previous concern: the workflow loop converted any exception from provider invocation into a provider error, which could hide programming mistakes.

Current state: resolved. `run_loop` catches `ProviderError` around `invoke_session`; expected CLI failures are represented by `AgentResult` values from provider implementations. Unexpected exceptions from provider code are allowed to surface normally.

### 2. Add focused reviewer outcome coverage

Previous concern: reviewer validation and safe-default behavior lacked focused coverage.

Current state: resolved. `tests/test_orchestrator.py` now covers:

- no task awaiting review still rejects the reviewer handoff;
- approval with no open issues is accepted;
- rejection with open issues is accepted;
- mismatch cases are accepted structurally and handled by `process_handoff` as `changes_requested`.

### 3. Eliminate duplicate handoff parsing in normal processing

Previous concern: validation parsed a handoff and processing parsed it again.

Current state: resolved. `run_loop` calls `parse_handoff(...)`, validates the resulting `Handoff`, and passes it directly to `process_handoff(...)`. `process_handoff` still archives the handoff artifact before applying state transitions, but it does not re-parse the archive.

### 4. Extract per-session lifecycle data

Previous concern: per-session log paths, prompt retention paths, config logging, and invocation construction were threaded through `run_loop` as loose variables.

Current state: resolved. `SessionContext` owns per-session identity and log paths, constructs `AgentInvocation`, writes retained prompts, and logs resolved agent config metadata.

### 5. Move session context logging out of orchestrator

Previous concern: role-specific start/finish log formatting added reporting details to the workflow loop.

Current state: resolved. `src/devlab/session_logging.py` owns lightweight session start/finish context formatting. `orchestrator.py` still decides when to log session boundaries, but formatting is separated.

### 6. Share common test helpers

Previous concern: e2e workflow tests and evaluation support duplicated handoff/task helper code.

Current state: mostly resolved. `tests/helpers.py` contains shared helpers. Continue using it when adding new e2e or evaluation scenarios instead of recreating handoff/task formatting locally.

## Remaining orchestrator-specific follow-ups

### A. Decide whether to remove the dead `close_task` helper

`close_task()` still exists in `orchestrator.py` and has a direct unit test, but production task closure happens inline in `process_handoff` for reviewer approval. This creates two task-closing paths to keep in mind.

Recommendation: remove `close_task()` and its dedicated test unless a near-term caller appears. If kept, add a short comment explaining why this helper exists despite not being used by production orchestration.

Priority: low.

### B. Consider a smaller `run_loop` after the next orchestration change

`run_loop` remains readable but still owns many responsibilities: role selection, prompt construction, environment lifecycle, provider invocation, handoff validation, handoff processing, Git commits/tags, progress callbacks, and interactive continuation.

Recommendation: do not refactor solely for aesthetics. When the next substantial orchestration feature lands, consider extracting one cohesive slice, such as:

- environment lifecycle around a session;
- agent invocation/error handling around a `SessionContext`;
- commit/tag policy after `process_handoff`.

Keep workflow policy visible in `orchestrator.py`; extracted modules should not obscure state-transition decisions.

Priority: medium-low.

### C. Keep reviewer mismatch safe-default behavior under live-eval observation

The current design intentionally accepts reviewer signal mismatches structurally and defaults to `changes_requested`. This is safer for real agents than failing the whole run on likely formatting drift, but it can spend extra bounded sessions.

Recommendation: keep collecting live-evaluation evidence. If mismatch loops become common, improve diagnostics/prompts first; only add a structured reviewer outcome block if Markdown ambiguity remains a persistent real-world issue.

Priority: monitor.

### D. Post-reviewer structural validation belongs in a separate design slice

Reviewer correctness is still partly prompt-dependent. Profile validation commands exist as durable project configuration, but the orchestrator does not yet automatically run them after reviewer approval and convert failures into `changes_requested`.

Recommendation: handle this through the broader workflow-contract hardening item in `docs/todo.md`, not as incidental orchestrator cleanup. The design should specify command selection, stdout/stderr capture, failure reporting, task status transition, and interaction with reviewer approval.

Priority: medium, but separate from this cleanup plan.

## Guidance for future changes

- Keep `orchestrator.py` focused on workflow selection, session lifecycle, handoff processing, and error recovery.
- Put provider-specific behavior in `agents.py`.
- Put reporting-only formatting in focused modules such as `session_logging.py` or `workflow_diagnostics.py`.
- Keep durable task/finding/milestone mutations behind workspace/tracker abstractions.
- Add focused tests for every state transition and safe-default behavior change.
