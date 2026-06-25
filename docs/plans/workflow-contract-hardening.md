# Workflow Contract Hardening Plan

This plan implements TODO #1 from `docs/todo.md`: make workflow state transitions depend on well-defined artifact contracts instead of fragile broad Markdown/text searches.

## Goal

DevLab should fail fast on ambiguous or malformed role artifacts instead of silently making incorrect workflow transitions.

Key outcomes:

- Handoff sections are parsed and validated consistently.
- `Open Issues` semantics are strict.
- Developer completion is scoped to task acceptance criteria.
- Reviewer approval/rejection cannot be confused by stale review text.
- Planner `Addressed Findings` parsing shares the same handoff contract.

## Next Slice: Orchestrator-Owned Validation Enforcement

The remaining hardening work should keep DevLab's normal design pressure: agents should write the minimum structure needed for recovery and review, while DevLab infers deterministic facts from durable state whenever it can.

The goal is not to replace reviewer or integrator judgment with checkboxes. The goal is to separate agent claims from facts the orchestrator can enforce:

- task, milestone, profile, dependency, handoff, and finding state is structurally coherent;
- configured validation commands exist, run, and have recorded exit-code outcomes;
- workflow transitions only happen when the current repository state satisfies the relevant gate;
- gaps in mechanical validation are visible as workflow facts instead of hidden in prose.

### Task-Level Validation: Flexible and Observable

Task-level validation should be useful without making every task a hard integration point.

The orchestrator can infer the required validation source without asking the developer for a rich structured report:

- if task metadata has `validation = ["..."]`, use those task-specific commands;
- if task metadata omits `validation`, use the resolved profile's default validation;
- if task metadata has `validation = []` and the profile contributes no required command, classify the task as having no mechanical validation requirement.

Initial task-level behavior should be conservative:

- after reviewer approval, run known task/profile validation commands when configured;
- record the outcome in durable session/workflow metadata for diagnostics;
- if validation passes, allow the task to close normally;
- if no validation is configured, allow the task to close but emit/report a diagnostics warning;
- if validation fails, prefer a configurable policy rather than one universal rule.

The default policy should probably start as warning or soft rejection while the workflow collects live baselines. A later strict mode can turn failed task validation into `changes_requested`. This avoids prematurely rejecting useful incremental states where a reviewer intentionally approved a coherent task even though the whole repository is temporarily not green.

Developer and reviewer prompts should still make the expectation explicit: implementation tasks should add or update automated validation for their acceptance criteria when practical. The orchestrator should not require a structured acceptance-criteria-to-test map at first. Add that only if diagnostics show repeated failures where agents claim coverage that cannot be audited.

### Milestone-Level Validation: Strict Repository Gate

Milestone validation should be stricter than task validation.

Before marking a milestone integrated, the orchestrator should require configured validation to pass from the milestone repository state. This is the right place for a hard gate because the milestone represents an accepted increment, not an intermediate task boundary.

Recommended behavior:

- resolve the milestone's relevant validation commands from closed tasks and profiles;
- deduplicate commands while preserving a stable order;
- run the commands before or as part of integrator processing;
- if validation passes and the integrator reports no open issues, mark the milestone integrated;
- if validation fails, do not mark the milestone integrated; create or require an integration finding that records the failing command and routes remediation through planner/developer work;
- if no mechanical validation is available for meaningful product work, allow integration only with an explicit warning/finding depending on project strictness.

This preserves task-level flexibility while making milestone acceptance a real repository-state fact.

Tradeoffs:

- bugs caught only at milestone integration may be harder to attribute to one task;
- integration sessions can become heavier if milestones contain many tasks;
- strict milestone gates require reliable target-owned validation commands and clear missing-tool behavior;
- the benefit is a stronger audit boundary: closed tasks can be "reviewed work", while integrated milestones are "validated repository increments".

### Minimal Exception Handling

Avoid adding a broad validation-decision schema up front.

Use existing task/profile metadata as the primary contract. Treat `validation = []` plus absent profile defaults as the deterministic signal that no mechanical validation is configured. Surface that in status/diagnostics rather than requiring every developer to fill out a special exception object.

If live runs show this is too ambiguous, add one narrow exception section only for non-default cases, such as intentionally deferred or manual validation. Any such exception should require a reason, be visible to the reviewer and integrator, and be counted in diagnostics. It should not become routine output for normal tasks.

### Implementation Order

1. Add a validation-resolution helper that determines effective task validation from task metadata and resolved profile defaults without mutating state.
2. Add durable validation outcome records for command, exit status, role/session context, task or milestone id, and a short output summary.
3. Run and record task-level validation after reviewer approval using a soft policy first: pass closes, missing validation warns, failure records a warning or configurable rejection.
4. Add diagnostics/status reporting for tasks closed without mechanical validation and tasks with failed recorded validation.
5. Add milestone-level validation before marking milestones integrated, with a stricter default: failing configured validation blocks integration and creates or requires an integration finding.
6. Update developer/reviewer/integrator prompts to state the minimum contract: acceptance criteria should be mechanically validated where practical, but DevLab infers validation commands from task/profile metadata.
7. Add strict task-validation mode only after live baselines show the soft policy is too weak.

## Phase 1: Centralize Handoff Parsing

Add a focused handoff parser, preferably in:

```text
src/devlab/handoffs.py
tests/test_handoffs.py
```

Suggested API:

```python
@dataclass(frozen=True)
class Handoff:
    path: Path
    role_name: str
    sections: dict[str, str]

    def section(self, heading: str) -> str: ...
    @property
    def open_issues(self) -> str: ...
    @property
    def addressed_findings(self) -> str: ...
```

Suggested functions:

```python
def parse_handoff(path: Path, role_name: str) -> Handoff
def validate_handoff_contract(path: Path, role_name: str) -> tuple[bool, str]
```

Validation rules:

- Required sections exist:
  - `## Done`
  - `## Changed Artifacts`
  - `## Open Issues`
  - `## Addressed Findings`
  - `## Next Session Hint`
- Required sections appear in that exact order.
- Required sections are not empty.
- Duplicate required headings are invalid.
- Decide explicitly whether extra `##` sections are allowed. Recommendation: allow extra sections only after required sections, or reject for now to keep the contract tight.

Tests:

- valid handoff
- missing heading
- duplicate heading
- out-of-order heading
- empty required section
- extra section behavior
- missing handoff file
- empty handoff file

## Phase 2: Harden `Open Issues` Semantics

Current logic is too loose because text containing `none` can be treated as clean.

New rule:

A section means “no issues” only if it is exactly one semantic none item.

Accept:

```md
- None
```

Optionally accept:

```md
None
```

Treat as open issues or invalid:

```md
- No tests exist
- None, but deployment is missing
- None
- API validation is missing
```

Suggested helper:

```python
def section_is_none(section: str) -> bool: ...
def section_has_real_content(section: str) -> bool: ...
```

Use this for:

- architect finding creation
- integrator finding creation
- reviewer rejection detection
- unrecoverable issue detection, if retained

Tests:

- `- None` means no issues
- `None` means no issues if accepted
- `- No tests exist` means open issue
- `- None, but X` is not clean
- mixed `- None` plus another item is invalid or treated as open issue

## Phase 3: Scope Task Completion to Acceptance Criteria

Current developer completion checks all checkboxes in the whole task file. That is too broad.

New rule:

A developer session marks a task `in_review` only if:

- the task has a `## Acceptance Criteria` section,
- the section contains at least one checkbox,
- all checkboxes in that section are checked.

Ignore checkboxes elsewhere, such as:

- review checklist
- notes
- requested changes
- validation checklist

Preferred implementation location:

```text
src/devlab/task_tracker.py
```

Suggested API:

```python
@dataclass(frozen=True)
class Task:
    ...

    @property
    def acceptance_criteria_complete(self) -> bool: ...
```

Then update orchestrator developer processing to use the selected `Task` record rather than reparsing the path directly.

Tests in `tests/test_task_tracker.py`:

- all acceptance criteria checked means complete
- one unchecked criterion means incomplete
- no acceptance criteria means incomplete
- no checkbox in acceptance criteria means incomplete
- checkboxes outside acceptance criteria do not matter
- uppercase `[X]` is accepted

## Phase 4: Harden Reviewer Approval/Rejection Contract

Current reviewer approval is inferred only from task Markdown:

```md
## Review
- [x] Approved
```

A stale approval marker could accidentally close a later rejected task.

New decision table:

| Handoff Open Issues | Task Review Approved | Result |
|---|---:|---|
| none | yes | close task |
| none | no | invalid session artifact |
| issues | yes | invalid conflicting artifact |
| issues | no | mark `changes_requested` |

Implementation options:

```python
class ReviewerOutcome(StrEnum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


def task_review_approved(task: Task) -> bool: ...
def reviewer_outcome(task: Task, handoff: Handoff) -> ReviewerOutcome: ...
```

Location can start in `orchestrator.py`; extract later if it grows.

Tests in `tests/test_orchestrator.py`:

- approved handoff plus approved task review closes task
- open issues plus no approval marks `changes_requested`
- open issues plus stale approval fails validation/session processing
- no open issues plus missing approval fails validation/session processing
- stale approval from an earlier review cannot close a rejected task

Prompt update:

Update `src/devlab/resources/prompts/conventions.md` and reviewer prompt to clarify:

- approval requires `## Open Issues` to be exactly `- None`
- approval requires task file `## Review\n- [x] Approved`
- rejection must not leave an approved review marker
- rejection must put actionable items in both `## Requested Changes` and handoff `## Open Issues`

## Phase 5: Strengthen Planner `Addressed Findings` Parsing

Existing strict validation is good, but it should use the shared handoff parser.

Rules:

`## Addressed Findings` must be exactly one of:

```md
- None
```

or one or more mappings:

```md
- F0001: T0002
- F0002: T0003, T0004
```

Invalid:

- prose lines
- malformed IDs
- duplicate finding entries
- duplicate task IDs for one finding
- mixing `- None` with mappings
- mapping to unknown tasks
- mapping to a task that does not list the finding in `addresses_findings`

Most domain checks already exist in `orchestrator.py`; this phase should mostly centralize section extraction and tighten malformed-section behavior.

Tests:

- valid single mapping
- valid multi-task mapping
- `- None`
- mixed `- None` and mapping
- duplicate finding
- duplicate task ID
- unknown finding
- unknown task
- task missing `addresses_findings`
- prose line rejected

## Phase 6: Remove Legacy Loose Helpers

After behavior is migrated, remove or shrink these ad hoc helpers in `src/devlab/orchestrator.py`:

- `_handoff_has_open_issues`
- `_handoff_section`
- `_task_is_complete`
- broad duplicated regex parsing where replaced by the handoff parser or task properties

Target orchestrator shape:

```python
handoff = parse_handoff(archived, role_name)

if role_name == "architect":
    if handoff.has_open_issues:
        workspace.findings().create_from_handoff(...)
```

Keep orchestration policy visible in `orchestrator.py`; move reusable parsing/contract validation to the owning helper module.

## Suggested Implementation Order

1. Add handoff parser and tests without changing orchestration behavior.
2. Switch `Open Issues` handling to strict parser helpers.
3. Move acceptance criteria completion into `Task` and update developer processing.
4. Harden reviewer outcome decision and add stale-approval tests.
5. Refactor planner `Addressed Findings` to shared parser.
6. Remove obsolete helpers and update prompts/docs.

Each phase should be independently testable.

## Expected Files Changed

Likely source files:

```text
src/devlab/handoffs.py
src/devlab/orchestrator.py
src/devlab/task_tracker.py
src/devlab/resources/prompts/conventions.md
src/devlab/resources/prompts/role-reviewer.md
```

Likely tests:

```text
tests/test_handoffs.py
tests/test_orchestrator.py
tests/test_task_tracker.py
```

## Definition of Done

- Ambiguous handoffs fail validation instead of causing silent state transitions.
- Task completion only depends on acceptance criteria.
- Reviewer stale approval cannot close a rejected task.
- Planner addressed-finding mappings use the shared handoff section parser.
- Existing workflow tests still pass.
- New tests cover malformed/ambiguous real-agent outputs.
- Validation passes:

```bash
uv run ruff check
uv run ty check
uv run pytest
```
