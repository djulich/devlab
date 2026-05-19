# Plan: Orchestrator Quality Improvements

Seven weaknesses identified in the current codebase after the logging, handoff extraction, agent invocation, and evaluation harness work. Grouped by priority and sequenced to minimize churn.

## Priority 1: Correctness and debuggability

### 1a. Narrow the broad `Exception` catch in agent invocation

`orchestrator.py:456` catches bare `Exception` from `invoke_session`. `CliAgentProvider` already handles `FileNotFoundError`, `TimeoutExpired`, and `OSError` internally and returns structured `AgentResult` values. The bare `Exception` catch silently converts programming errors (`AttributeError`, `TypeError`, etc.) into "provider_error" diagnostic strings instead of letting them propagate as crashes with tracebacks.

**Change:** Narrow to `OSError` or, if custom providers need a catch-all escape hatch, introduce a `ProviderError` exception in `agents.py` that providers raise for anticipated operational failures. Let genuine programming errors crash with a traceback.

**Files:** `src/devlab/orchestrator.py`, `src/devlab/agents.py` (if adding `ProviderError`).

### 1b. Add tests for `_validate_reviewer_outcome`

`_validate_reviewer_outcome` enforces strict alignment between handoff open-issues state and task review-approved state. It has no dedicated test coverage. The existing `ChangesRequestedWorkflow` e2e test exercises both outcomes on the happy path but does not test the three error cases: (1) no task awaiting review, (2) open issues but task is approved, (3) no open issues but task is not approved.

**Change:** Add focused unit tests for all three error returns plus the two success returns.

**Files:** `tests/test_orchestrator.py`.

## Priority 2: Dead code and redundancy (quick wins)

### 2a. Remove or inline dead `close_task` function

`close_task()` at `orchestrator.py:168` is exported and has a direct test (`TestCloseTask`), but is never called from production code. The actual task-closing logic in `process_handoff` (lines 241-246) does the same work inline. Having two close-task code paths is confusing.

**Change:** Delete `close_task` and its test. The inline logic in `process_handoff` is the canonical path.

**Files:** `src/devlab/orchestrator.py`, `tests/test_orchestrator.py`.

### 2b. Eliminate double `parse_handoff` for valid handoffs

`validate_handoff` (line 138) calls `parse_handoff`, validates the result, then discards the `Handoff` object. `process_handoff` (line 212) immediately calls `parse_handoff` again on the archived copy. The validated `Handoff` should flow from validation into processing.

**Change:** Make `validate_handoff` return the parsed `Handoff` on success (changing the return type to `tuple[Handoff | None, str]` or similar). Have `run_loop` pass it into `process_handoff`. This also means `process_handoff` no longer needs to parse or archive independently — it receives a pre-validated `Handoff`.

Note: the current code validates the original but processes the archive. The archive is a `shutil.copy2`, so the content is identical. After the change, validate and archive first, then parse once from the archive.

**Files:** `src/devlab/orchestrator.py`.

## Priority 3: Structural improvements

### 3a. Extract session lifecycle from `run_loop`

`run_loop` is ~195 lines with 6 log-path local variables, conditional prompt logging, config logging, and error-message construction threaded through the loop body. Each new observability concern added inline plumbing.

**Change:** Extract a frozen dataclass (e.g. `SessionContext`) that holds `invocation_id`, `stdout_log`, `stderr_log`, `system_prompt_log`, `session_prompt_log`, `config_log`, and the `AgentInvocation`. Add a factory function that builds it from `root`, `session_number`, `role_name`, and `retain_prompts`. Move the config-logging and prompt-logging calls into methods or companion functions that operate on this dataclass. `run_loop` creates a `SessionContext` per iteration, then passes it to invocation/validation/processing steps.

This should reduce `run_loop` by ~40-50 lines and make the per-session setup testable independently.

**Files:** `src/devlab/orchestrator.py`, possibly `tests/test_orchestrator.py` for the new dataclass.

### 3b. Share helpers between e2e tests and evaluation harness

`tests/evaluations/harness.py` (456 lines) and `tests/evaluations/scripted_agents.py` (337 lines) duplicate task-writing, approval, and handoff-building helpers that already exist in `tests/test_orchestrator_e2e.py`. Both `harness.handoff()` and `test_orchestrator_e2e._handoff()` produce valid handoff text with nearly identical signatures. The `write_task`, `complete_acceptance`, and `approve_review_task` functions in `scripted_agents.py` mirror `_write_task`, `_check_acceptance`, and `_approve_review_task` in `test_orchestrator_e2e.py`.

**Change:** Extract shared test utilities (handoff builder, task writer, acceptance checker, review approver) into a `tests/helpers.py` module. Update both `test_orchestrator_e2e.py` and `tests/evaluations/scripted_agents.py` to import from it.

**Files:** `tests/helpers.py` (new), `tests/test_orchestrator_e2e.py`, `tests/evaluations/scripted_agents.py`, `tests/evaluations/harness.py`.

## Priority 4: Monitor, do not change yet

### 4. `_validate_reviewer_outcome` strictness with real agents

The reviewer validation requires strict alignment between handoff open-issues and task review-approved state. This is correct as a contract, but it will likely be the first validation to break with real agents — an agent might write "no open issues" in the handoff but forget to add the `## Review / - [x] Approved` checkbox, or vice versa. Whether this should stay strict (force agents to comply) or become lenient (trust one signal over the other) depends on live-agent experience. No code change now; watch live evaluations and revisit if rejection rates are high.

## Implementation sequence

| Step | Item | Risk | Estimated size |
|------|------|------|----------------|
| 1 | 1a. Narrow Exception catch | Low | ~15 lines changed |
| 2 | 2a. Remove dead close_task | None | ~15 lines deleted |
| 3 | 1b. Add reviewer validation tests | None | ~40 lines added |
| 4 | 2b. Eliminate double parse_handoff | Low | ~20 lines changed |
| 5 | 3a. Extract session lifecycle | Medium | ~80 lines refactored |
| 6 | 3b. Share test helpers | Low | ~60 lines moved |

Steps 1-4 are independent and could be done in any order. Step 5 (session lifecycle extraction) should come after step 4 (double parse) since both modify `run_loop`. Step 6 is independent of the others.
