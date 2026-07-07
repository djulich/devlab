# Durable Operator Clarifications

This plan implements TODO #6 from `docs/todo.md`: support bounded operator clarification when a role session encounters an ambiguity, contradiction, missing prerequisite, or scope decision that cannot be resolved safely from repository state.

## Goal

DevLab should remain as autonomous as possible while giving agents a durable, auditable way to stop instead of inventing requirements.

Key outcomes:

- Role sessions can request clarification through a structured artifact contract.
- DevLab stops in a durable "needs clarification" state.
- Operators can answer through the CLI or by editing repository files.
- DevLab records how the interrupted workflow should resume, so operators do not need to remember whether `devlab plan` or `devlab implement` is the correct next command.
- Answered clarifications become stable workflow references.
- Relevant answers are included in later role prompts.
- Clarifications that affect project meaning, architecture, task scope, deployment expectations, or validation expectations are promoted into durable project knowledge when appropriate.
- The mechanism is bounded so it does not become an open-ended conversational phase.

## Design Direction

DevLab should borrow the intent of GSD's `Discuss` step, not copy its exact phase structure.

GSD discusses implementation decisions before planning so later roles do not guess about libraries, edge cases, or behavior. DevLab should express the same idea as durable clarification records plus conservative autonomy defaults:

- make safe, evidence-backed assumptions where possible;
- stop only for high-impact or unsafe ambiguity;
- require every clarification request to include context, expected answer shape, and a recommended default unless no safe default exists;
- store the question and answer as workflow state, not conversational memory;
- reference stable clarification IDs from tasks, findings, and future milestone verification records instead of duplicating prose.

This should be two related mechanisms:

- **Proactive planning clarifications**: architect or planner can request operator decisions before finalizing design or task plans.
- **Reactive blocking clarifications**: any role can stop when continuing would mean inventing requirements, ignoring a contradiction, or making a risky scope/tooling decision.

## Storage Model

Add a new file-backed tracker, not findings and not only workflow state:

```text
.devlab/clarifications/
  CL0001_auth-session-timeout.md
```

Findings mean repository work is needed. Clarifications mean operator intent is needed. They may relate, but they should remain different workflow objects.

Recommended front matter:

```toml
+++
id = "CL0001"
title = "Auth session timeout"
status = "pending"
asking_role = "planner"
session_id = "20260707T101500_002_planner"
scope = "milestone:M1"
blocks = "planning"
answer_shape = "choice"
recommended_option = "A"
decision_refs = []
created_at = "2026-07-07T10:15:00Z"
answered_at = ""
+++
```

Allowed values:

- `status`: `pending`, `answered`, `superseded`
- `answer_shape`: `choice`, `text`, `file-edit`
- `scope`: `workspace`, `planning`, `milestone:<id>`, `task:<id>`, `finding:<id>`
- `blocks`: `planning`, `implementation`, `milestone:<id>`, `task:<id>`, `none`

Recommended body:

```md
# CL0001: Auth session timeout

## Context
The specification requires login sessions but does not define expiry behavior.

## Question
Should sessions expire?

## Options
- A: 24-hour idle timeout. Recommended because it is a safe MVP default.
- B: No expiry for MVP.
- C: Operator-provided policy.

## Recommended Default
A

## Answer
- Pending
```

For text answers:

```md
## Expected Answer
State the required timeout behavior and whether idle timeout, absolute timeout, or both apply.
```

For file-edit answers:

```md
## Expected File Edits
- `.devlab/specs/system/auth.md`: define the session expiry policy.
```

## Tracker API

Add a compact tracker module:

```text
src/devlab/clarifications.py
tests/test_clarifications.py
```

Suggested domain types:

```python
class ClarificationStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    SUPERSEDED = "superseded"

class ClarificationAnswerShape(StrEnum):
    CHOICE = "choice"
    TEXT = "text"
    FILE_EDIT = "file-edit"

@dataclass(frozen=True)
class Clarification:
    id: str
    title: str
    status: ClarificationStatus
    path: Path
    asking_role: str
    session_id: str
    scope: str
    blocks: str
    answer_shape: ClarificationAnswerShape
    recommended_option: str
    decision_refs: tuple[str, ...]
    body: str
```

Suggested tracker operations:

```python
class FileClarificationTracker:
    def list_clarifications(self) -> list[Clarification]: ...
    def pending(self) -> list[Clarification]: ...
    def answered(self) -> list[Clarification]: ...
    def get(self, clarification_id: str) -> Clarification: ...
    def create_from_handoff(self, *, role_name: str, session_id: str, handoff: Handoff) -> Clarification: ...
    def answer(self, clarification_id: str, answer: str, *, operator: str = "") -> None: ...
    def supersede(self, clarification_id: str, reason: str) -> None: ...
```

Keep all parsing and mutation behind this tracker. Other modules should not parse clarification files directly.

Add workspace boundary support:

```python
workspace.clarifications()
snapshot.list_clarifications()
snapshot.pending_clarifications()
snapshot.blocking_clarifications()
```

## Resume State

Clarification records store the question and answer. Workflow resume intent should be stored as orchestrator-owned workflow-control state, not inferred later from handoff prose.

Extend `.devlab/workflow.toml` with a compact optional resume pointer:

```toml
[resume]
blocked_by = "CL0001"
command = "implement"
role = "developer"
task = "T0003"
milestone = ""
```

Semantics:

- `blocked_by` names the clarification that stopped the workflow.
- `command` is the command family that may resume the interrupted work: `plan` or `implement`.
- `role` is the interrupted role.
- `task` is set for developer/reviewer task work.
- `milestone` is set for integrator or architecture-review milestone work.
- Empty `task` or `milestone` means the field does not apply.

The resume pointer is a convenience and safety guard. It is not the source of the clarification answer; the clarification file remains the source for operator intent.

When a clarification is answered, DevLab should not require the operator to use a special resume command. The stored resume intent lets DevLab handle all reasonable next commands consistently:

- `devlab resume` resumes the stored command family.
- `devlab clarify answer CL0001 ... --resume` answers and immediately resumes through the stored command family.
- `devlab plan` may resume only when `command = "plan"`.
- `devlab implement` may resume only when `command = "implement"`.
- The wrong plain command stops with precise guidance rather than silently crossing the planning/implementation boundary.

Example wrong-command message:

```text
Workflow is waiting to resume after CL0007.
This clarification blocked implementation task T0003.

Run:
  devlab resume

Or explicitly:
  devlab implement
```

Plain `devlab plan` should not consume an implementation resume pointer. DevLab intentionally allows planning after implementation has started, but after a developer clarification the operator's plain planning command is ambiguous: it does not resume the interrupted task, and it may or may not be intended as a planning revision. Stop and ask for an explicit command instead.

`devlab plan --revise` is different. It should be allowed to override an implementation resume pointer because the operator is explicitly choosing to revise planning. If the revision supersedes or changes the interrupted task, DevLab should preserve auditability by referencing or superseding the clarification and clearing the stale resume pointer only after the planning revision succeeds.

For interrupted developer sessions, resume should target the same task. A developer clarification must not move the task to `in_review`; the task stays in its previous developable status, usually `open` or `changes_requested`. On resume, DevLab should verify:

- the blocking clarification is answered;
- the interrupted task still exists;
- the task is still in a developable status;
- dependencies are still satisfied;
- no spec reconciliation blocker has appeared.

If those checks pass, DevLab invokes the developer for the same task with the answered clarification in prompt context. If the task is no longer eligible, DevLab stops with a clear reconciliation message instead of selecting another task.

## Handoff Contract

Extend handoffs with an optional `## Clarification Request` section.

Only one clarification request should be allowed per role session in the first implementation. This keeps bounded sessions intact and prevents agents from dumping a broad questionnaire into the workflow.

Recommended format:

```md
## Clarification Request
clarification_required = true
title = "Auth session timeout"
scope = "milestone:M1"
blocks = "planning"
answer_shape = "choice"
recommended_option = "A"

### Context
The specification requires login sessions but does not define expiry behavior.

### Question
Should sessions expire?

### Options
- A: 24-hour idle timeout. Recommended because it is a safe MVP default.
- B: No expiry for MVP.
- C: Operator-provided policy.
```

If a role does not need clarification, it omits the section. Do not require agents to write `clarification_required = false`; absence is cleaner.

Validation rules:

- Section is optional for all roles.
- If present, it must contain a TOML header block followed by Markdown details.
- Required TOML keys: `clarification_required`, `title`, `scope`, `blocks`, `answer_shape`.
- `clarification_required` must be `true`.
- `recommended_option` is required when `answer_shape = "choice"`.
- `scope`, `blocks`, and `answer_shape` must use known values.
- Markdown details must contain `### Context` and `### Question`.
- Choice clarifications must contain `### Options`.
- Non-choice clarifications must contain `### Expected Answer` or `### Expected File Edits`.
- A session with a clarification request may have `## Open Issues` describing that it is blocked, but DevLab should not create a finding solely because a clarification was requested.

## Orchestrator Behavior

When processing a valid handoff with a clarification request:

1. Archive the handoff normally.
2. Create a clarification file under `.devlab/clarifications/`.
3. Write the `.devlab/workflow.toml` resume pointer for the interrupted command, role, task, or milestone.
4. Do not advance the role's normal workflow state transition.
5. Commit the clarification record and resume pointer through the existing automatic version-control path.
6. Stop the run with a clear completed-but-blocked result:

```text
Workflow stopped: operator clarification required.
CL0001 Auth session timeout
Answer and resume with: devlab clarify answer CL0001 --choice A --resume

Or answer now and resume later:
  devlab clarify answer CL0001 --choice A
  devlab resume
```

This should not be treated as an agent failure. The role made a valid bounded stop.

Before selecting the next role, DevLab should check blocking pending clarifications:

- `blocks = "planning"` blocks `devlab plan` and planner/architect planning sessions.
- `blocks = "implementation"` blocks developer, reviewer, integrator, and architecture-review continuation.
- `blocks = "task:T0003"` blocks only that task's developer/reviewer flow.
- `blocks = "milestone:M1"` blocks integration and architecture review for that milestone.
- `blocks = "none"` does not block progress but appears in status.

Initial implementation can conservatively block the whole command for any pending clarification except `blocks = "none"`. Add narrower task/milestone scoping after the basic tracker and CLI are stable.

When an answered clarification has an active resume pointer:

- matching `devlab plan` or `devlab implement` resumes normally;
- `devlab resume` dispatches to the stored command family;
- wrong plain commands stop with exact guidance;
- explicit `devlab plan --revise` may override an implementation resume pointer and should clear or replace it only after successful planning reconciliation.

Clear the resume pointer only after the resumed workflow gets past the interrupted blocker safely. For a developer clarification, that means the next developer session for the same task is invoked and processed without requesting the same clarification again. If the resumed session requests a new clarification, update the pointer to the new clarification.

## CLI UX

Add a `clarify` command group and a top-level `resume` command:

```bash
devlab clarify list
devlab clarify show CL0001
devlab clarify answer CL0001 --choice A --note "Use 24h idle timeout for MVP."
devlab clarify answer CL0001 --choice A --resume
devlab clarify answer CL0001 --text "Use a 24h idle timeout and a 30d absolute timeout."
devlab clarify supersede CL0001 --reason "Spec was edited to remove auth."
devlab resume
```

Recommended behavior:

- `list` shows pending items first, with id, title, asking role, scope, and blocks.
- `show` prints the full clarification file.
- `answer --choice` validates the selected option exists in the body.
- `answer --text` records free text under `## Answer`.
- `answer` sets `status = "answered"` and `answered_at`.
- `answer --resume` answers, validates the stored resume pointer, then dispatches to the correct workflow command.
- `supersede` sets `status = "superseded"` and appends a short reason.
- `resume` resumes the answered clarification named by `.devlab/workflow.toml [resume]`.
- `resume CL0001` may be added if multiple answered resume candidates become possible later.
- Commands mutate only clarification files unless the operator explicitly passes `--resume` or runs `devlab resume`.

Operators may also answer by editing the file directly. `doctor` should validate that edited answered clarifications satisfy the required shape.

If the operator manually edits the clarification file and then runs `devlab resume`, DevLab should validate the edited answer before invoking any role. Invalid or empty answered records remain blocking and should produce a repair-oriented message.

Future UX options:

- `devlab clarify answer CL0001 --use-default`
- `devlab plan --auto-clarify-defaults`
- `devlab implement --auto-clarify-defaults`
- `devlab clarify export --pending`

Do not implement auto-answering in the first slice. The first slice should prove the durable state and stop/resume behavior.

## Prompt Integration

Prompt assembly should include relevant answered clarifications.

Recommended prompt context:

- all pending blocking clarifications for the selected role or command;
- answered clarifications scoped to the selected task, milestone, or planning flow;
- recent workspace-scoped answered clarifications;
- omit superseded clarifications by default, except in diagnostics/history views.

Keep the prompt text concise:

```md
## Operator Clarifications

- CL0001 Auth session timeout: Use a 24-hour idle timeout for MVP.
```

Do not include entire clarification files in normal role prompts unless the selected role is directly resolving planning or task scope and needs the full context.

Prompt rules:

- Architect/planner may ask broad scope, architecture, library, UX, deployment, and planning questions.
- Developer may ask only task-local blockers, missing prerequisites, contradictions, or unsafe implementation choices.
- Reviewer/integrator should usually create findings; they may request clarification only when the correct verdict depends on operator intent rather than code quality.
- All roles must prefer evidence-backed assumptions when the risk of being wrong is low.
- A clarification request must be specific, answerable, and include a recommended default unless no safe default exists.

## Durable Knowledge Promotion

Answered clarifications should not automatically rewrite `CONTEXT.md` or ADRs. Agents should promote them when the answer affects durable project meaning.

Rules for prompts:

- Update `CONTEXT.md` when a clarification defines project language, domain rules, user-visible behavior, or scope boundaries.
- Create or update an ADR only when the answer is hard to reverse, surprising without context, and trade-off based.
- Reference the clarification ID in tasks or findings when the answer constrains implementation.

Future task/front-matter metadata:

```toml
decision_refs = ["CL0001"]
```

Do not add this metadata in the first slice unless needed for prompt selection. It can follow after the clarification tracker exists.

## Status, Doctor, And Diagnostics

Update reporting without mutating state.

`devlab status`:

- show pending clarification count;
- show the first few blocking clarification IDs and titles;
- show whether the current workflow is blocked by clarification.

`devlab workflow-state`:

- include clarification blockers in the lifecycle report and JSON output.

`devlab doctor`:

- validate clarification file front matter;
- validate known status, scope, blocks, and answer shape values;
- validate pending records have question/context;
- validate answered records have non-empty answer text;
- warn if a choice answer does not match listed options;
- warn if old pending clarifications are non-blocking but still unanswered.

Diagnostics:

- count clarification stops by role;
- track time or session distance between created and answered clarifications when possible;
- flag repeated clarification requests from the same role/session area as a planning-quality smell.

## Autonomy Defaults

The default should be "assume with evidence, ask only when high-impact or unsafe."

Clarifications should be reserved for cases such as:

- contradictory requirements;
- missing operator-owned prerequisite;
- architecture or deployment choice with durable cost;
- security, data-loss, privacy, compliance, or irreversible migration ambiguity;
- acceptance criteria that cannot be made concrete without operator intent;
- requested technology choice that conflicts with existing project/tooling policy.

Clarifications should not be used for:

- ordinary implementation details where existing code conventions are clear;
- small UI copy choices;
- local naming choices;
- questions that can be answered by reading repository files;
- broad "what should I do next?" prompts;
- dumping every possible edge case on the operator.

## Implementation Phases

### Phase 1: Clarification Tracker

Add `src/devlab/clarifications.py` and `tests/test_clarifications.py`.

Implement:

- parse and format clarification files;
- list, get, pending, answered;
- create with stable `CLXXXX` IDs;
- answer and supersede mutations;
- validation errors for malformed records.

Add `Workspace.clarifications()` and `WorkspaceSnapshot` read helpers.

### Phase 2: Handoff Parsing

Extend `src/devlab/handoffs.py`.

Implement:

- optional `Clarification Request` section;
- parser for TOML header plus Markdown details;
- validation for required fields and bounded shape;
- tests for valid choice, valid text, valid file-edit, malformed TOML, missing context, missing question, missing options, and invalid enum values.

### Phase 3: Orchestrator Stop/Resume

Integrate clarification requests into `process_handoff()` and `run_loop()`.

Implement:

- create clarification from archived handoff;
- write and parse `.devlab/workflow.toml [resume]`;
- stop without normal workflow transition;
- return an outcome that CLI can report as blocked rather than failed;
- pre-role blocking check for pending blocking clarifications;
- matching-command resume for `devlab plan` and `devlab implement`;
- wrong-command guidance when the active resume pointer belongs to the other command family;
- top-level `devlab resume` dispatch semantics in orchestration or CLI glue;
- same-task resume validation for interrupted developer and reviewer sessions;
- events for `clarification_requested` and `clarification_answered` if workflow events are already suitable.

Tests:

- planner clarification blocks planning and does not update planning state;
- developer clarification does not move task to review;
- reviewer clarification does not close or reject task;
- answered clarification allows the next run to continue;
- `devlab resume` dispatches to the stored command family;
- matching `devlab plan` resumes planning clarification;
- matching `devlab implement` resumes implementation clarification;
- wrong plain command stops with exact resume guidance;
- `devlab plan --revise` may override an implementation resume pointer;
- developer resume selects the same task;
- developer resume stops if the task no longer exists or is no longer developable;
- pending clarification is committed through normal version-control flow.

### Phase 4: CLI Commands

Add `devlab clarify` and `devlab resume`.

Implement:

- `list`;
- `show CLXXXX`;
- `answer CLXXXX --choice ... --note ...`;
- `answer CLXXXX --choice ... --resume`;
- `answer CLXXXX --text ...`;
- `supersede CLXXXX --reason ...`.
- `resume`;

Tests:

- list ordering;
- show output;
- answer choice validation;
- answer text mutation;
- answer with resume dispatch;
- supersede mutation;
- resume with answered clarification;
- resume with pending clarification;
- resume with no active resume pointer;
- unknown clarification ID;
- command output for pending and answered states.

### Phase 5: Prompt Context

Update `prompts.py` and role prompt resources.

Implement:

- concise answered clarification context;
- role instructions for when clarification is allowed;
- a minimal handoff example for `## Clarification Request`;
- prompt-size tests if existing prompt-context assertions need adjustment.

Tests:

- answered workspace/planning clarifications appear in architect/planner prompts;
- task-scoped answers appear in developer/reviewer prompts for that task;
- unrelated answered clarifications are omitted or summarized according to the chosen relevance rule;
- pending blockers are visible in status but should normally prevent prompt invocation.

### Phase 6: Reporting And Validation

Update `status`, `workflow-state`, `doctor`, and diagnostics.

Implement:

- pending blocker summaries;
- doctor checks for malformed clarification records;
- JSON fields for automation;
- diagnostics counters for clarification stops by role.

Tests:

- status reports pending blockers;
- workflow-state JSON includes clarification blockers;
- doctor rejects invalid status/shape and missing answer on answered records;
- diagnostics counts clarification stops.

### Phase 7: Traceability Extensions

Add optional `decision_refs` only after the core workflow is stable.

Candidate extensions:

- task front matter `decision_refs`;
- finding front matter `decision_refs`;
- milestone verification references once structured milestone verification exists;
- prompt relevance based on `decision_refs`.

This phase should be deferred until there is enough real usage to know whether scope-based prompt selection is insufficient.

## Open Design Choices To Set During Implementation

- Whether initial blocking should be global for all pending clarifications or honor task/milestone scope immediately.
- Whether clarification files should use `answered_at = ""` or omit `answered_at` until answered.
- Whether CLI `answer` should require `--note` for choice answers or allow the chosen option text to be the whole answer.
- Whether a clarification request should be allowed alongside normal role state transitions. Recommendation: no for the first slice.
- Whether `blocks = "none"` should be allowed in first implementation. Recommendation: yes for future-proofing, but it should be rare and visible.
- Whether `[resume]` should support only one active pointer or a list. Recommendation: one active pointer for the first slice, because bounded sessions produce one clarification at a time.
- Exactly when to clear `[resume]`. Recommendation: clear only after the matching command successfully gets past the interrupted blocker, not merely when the answer is written.

## Non-Goals

- Do not add a new clarification role.
- Do not add open-ended interactive chat to the workflow loop.
- Do not turn every planner uncertainty into an operator question.
- Do not store clarification state only in logs or conversation memory.
- Do not use findings as the primary clarification storage.
- Do not automatically rewrite `CONTEXT.md` or ADRs from CLI answers.
- Do not implement auto-answering defaults until the explicit answer path is stable.

## Documentation Updates

Update:

- `docs/todo.md`: mark item #6 as planned once this design is accepted.
- `docs/design.md`: document clarification records as durable workflow state.
- `CONTEXT.md`: add clarification terminology once implementation begins.
- `src/devlab/resources/prompts/conventions.md`: document clarification artifacts and handoff section.
- `README.md` and `docs/operator-guide.md`: explain how to answer a blocked workflow.
- `docs/plans/README.md`: list this plan while active.

## Test Strategy

Unit tests should cover tracker parsing/mutation and handoff validation. Orchestrator tests should cover stop/resume state transitions. CLI tests should cover operator workflows. Prompt tests should verify concise inclusion of answered clarifications without overloading unrelated roles.

Suggested test files:

- `tests/test_clarifications.py`
- `tests/test_handoffs.py`
- `tests/test_orchestrator.py`
- `tests/test_cli.py`
- `tests/test_status.py`
- `tests/test_doctor.py`
- `tests/test_prompt_context.py`

The first complete implementation should run:

```bash
uv --cache-dir /tmp/uv-cache run pytest tests/test_clarifications.py tests/test_handoffs.py tests/test_orchestrator.py tests/test_cli.py tests/test_status.py tests/test_doctor.py tests/test_prompt_context.py
```

Run the full suite before marking TODO #6 initially implemented.
