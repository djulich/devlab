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
