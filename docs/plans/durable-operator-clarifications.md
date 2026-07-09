# Durable Operator Clarifications

This plan implements TODO #6 from `docs/todo.md`: support bounded operator clarification when a role session encounters an ambiguity, contradiction, missing prerequisite, or scope decision that cannot be resolved safely from repository state.

## Current Progress

The initial durable clarification workflow slice is implemented. DevLab now has repository-backed clarification records, a single active resume pointer, handoff parsing for bounded clarification requests, CLI answer/supersede/resume commands, prompt context for answered clarifications, and initial status/doctor integration.

Completed implementation:

- `src/devlab/clarifications.py`: file-backed tracker for `.devlab/clarifications/CLXXXX_slug.md`.
- `src/devlab/clarification_ops.py`: shared answer, supersede, validation, and resume operations for CLI and future adapters.
- `src/devlab/handoffs.py`: optional `## Clarification Request` parsing and validation.
- `src/devlab/workflow_state.py`: optional `.devlab/workflow.toml [resume]` pointer support.
- `src/devlab/workspace.py`: clarification access through `Workspace` and `WorkspaceSnapshot`.
- `src/devlab/orchestrator.py`: clarification request handling, conservative pending-blocker checks, resume pointer creation, wrong-command guard, and resume pointer clearing after matching continuation.
- `src/devlab/cli.py`: `devlab clarify list/show/answer/supersede` and `devlab resume`.
- `src/devlab/prompts.py`: concise answered clarification context in role prompts.
- `src/devlab/status.py` and `src/devlab/doctor_workflow_state.py`: initial read-only reporting and validation.
- Documentation and packaged prompt conventions for clarification artifacts and answer/resume flow.
- Focused tests, including tracker, handoff, orchestration, CLI, status, doctor, and prompt coverage.

Validation from the completed slice:

```bash
uv --cache-dir /tmp/uv-cache run ruff check src tests
uv --cache-dir /tmp/uv-cache run pytest
```

Observed result: ruff passed and pytest reported `490 passed, 7 skipped`.

The remaining work is refinement and extension rather than the first durable path:

- keep scoped clarification blocking deferred; precise `blocks` values are preserved, but pending blocking clarifications still stop conservatively until real usage justifies task/milestone routing complexity;
- finish strengthening resume validation so developer/reviewer resume cannot silently switch tasks and stops clearly when the interrupted task is missing, closed, dependency-blocked, or superseded by higher-priority reconciliation work;
- continue tightening wrong-command guidance across command paths;
- continue reporting refinements as needed; `devlab workflow-state` now includes clarification blockers and resume pointers in text, digest, and JSON output;
- add diagnostics for clarification stops, answer latency/session distance, and repeated clarification requests;
- continue improving repair guidance where needed; reusable manual-edit answer validation now distinguishes pending, empty answered, malformed, superseded, and choice-mismatch records, and `devlab resume` validates answers before invoking a role;
- optionally add the editor adapter after shared operations are stable;
- defer `decision_refs` traceability extensions until real usage shows scope-based prompt selection is insufficient.

## Goal

DevLab should remain as autonomous as possible while giving agents a durable, auditable way to stop instead of inventing requirements.

Key outcomes:

- Role sessions can request clarification through a structured artifact contract.
- DevLab stops in a durable "needs clarification" state.
- Operators can answer through the CLI, by editing repository files, or through future operator-interface adapters.
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

## Operator Interface Boundary

Clarifications should be designed as a workflow capability, not as a terminal-only feature. The first implementation should expose CLI commands because that is DevLab's current interface, but core workflow code should not assume that the operator is answering through a terminal.

Architectural rule:

```text
The repository-backed clarification record and resume pointer are the source of truth.
CLI, editor, HTTP API, email, webhooks, or a future web UI are adapters over the same operations.
```

Keep these operations reusable outside the CLI:

```python
create_clarification(...)
answer_clarification(...)
validate_clarification_answer(...)
supersede_clarification(...)
resume_workflow(...)
```

The exact function/module names can follow the implementation shape, but the boundary matters:

- trackers own clarification file parsing and mutation;
- workflow-state helpers own resume pointer parsing and mutation;
- orchestration owns workflow transitions and resume validation;
- CLI/editor/API/webhook adapters may present questions, collect answers, notify operators, and request resume;
- adapters must not bypass trackers or mutate `.devlab/workflow.toml` ad hoc;
- reporting paths remain read-only.

This keeps open the future possibility of running DevLab as a server that exposes workflow-start, workflow-status, clarification-answer, and resume APIs. Do not build that server now. The near-term requirement is simply to keep core workflow operations callable without requiring stdin/stdout interactivity.

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
+++
```

Allowed values:

- `status`: `pending`, `answered`, `superseded`
- `answer_shape`: `choice`, `text`, `file-edit`
- `scope`: `workspace`, `planning`, `milestone:<id>`, `task:<id>`, `finding:<id>`
- `blocks`: `planning`, `implementation`, `milestone:<id>`, `task:<id>`, `none`

`answered_at` is omitted while a clarification is pending and added only when the clarification is answered.

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
- `answer --choice` validates the selected option exists in the body and records the chosen option text as the answer.
- `answer --choice` does not require `--note`; an optional note may add operator rationale.
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
- `devlab plan --interactive-clarifications`
- `devlab implement --interactive-clarifications`
- `devlab plan --auto-clarify-defaults`
- `devlab implement --auto-clarify-defaults`
- `devlab clarify export --pending`

Do not implement auto-answering in the first slice. The first slice should prove the durable state and stop/resume behavior.

## Interactive And External Interfaces

The default clarification behavior should remain durable stop-and-resume. Unexpectedly launching an editor or waiting on a network callback would be bad for unattended workflows, CI, scripted runs, or remote sessions.

After the core clarification operations are stable, add operator-interface adapters as optional UX layers.

### Editor Adapter

An attended terminal run may opt into editor-based clarification:

```bash
devlab implement --interactive-clarifications
devlab plan --interactive-clarifications
```

When a clarification is requested:

1. DevLab writes the clarification file and resume pointer.
2. DevLab opens `$VISUAL`, then `$EDITOR`, on the clarification file.
3. The operator fills `## Answer` and exits the editor.
4. DevLab validates the answer through the same clarification validation operation used by the CLI.
5. If valid, DevLab marks the clarification answered and resumes through the stored resume intent.
6. If invalid or still pending, DevLab prints the validation issue and either reopens the editor or stops with normal resume instructions.

If neither `$VISUAL` nor `$EDITOR` is set, DevLab should print the clarification path and stop. It must not install or assume an editor.

### Future API, Webhook, Or Email Adapters

Later interfaces can use the same underlying operations:

- an HTTP API could expose pending clarifications, answer submission, and resume endpoints;
- a webhook adapter could notify an external system when a clarification is created;
- an email adapter could send the question and accept a structured reply;
- a web UI could render the clarification file and call the answer/resume operations.

All of these should preserve the same invariants:

- durable repository files remain authoritative;
- answer validation is shared;
- resume semantics are shared;
- command boundaries between planning and implementation remain explicit;
- external adapters cannot silently advance workflow state outside the orchestrator.

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

Status: implemented in the initial slice.

Add `src/devlab/clarifications.py` and `tests/test_clarifications.py`.

Implement:

- parse and format clarification files;
- list, get, pending, answered;
- create with stable `CLXXXX` IDs;
- answer and supersede mutations;
- validation errors for malformed records.

Add `Workspace.clarifications()` and `WorkspaceSnapshot` read helpers.

### Phase 2: Handoff Parsing

Status: implemented in the initial slice.

Extend `src/devlab/handoffs.py`.

Implement:

- optional `Clarification Request` section;
- parser for TOML header plus Markdown details;
- validation for required fields and bounded shape;
- tests for valid choice, valid text, valid file-edit, malformed TOML, missing context, missing question, missing options, and invalid enum values.

### Phase 3: Orchestrator Stop/Resume

Status: partially implemented. The durable stop, answer, resume pointer, wrong-command guard, conservative pending-blocker path, and same-task/same-route resume validation exist. Scoped task/milestone blocker routing is intentionally deferred pending real usage evidence.

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

### Phase 4: Operator Interface Boundary

Status: implemented for current adapter needs. Shared clarification operations exist in `clarification_ops.py`, including reusable manual-edit answer validation and structured resume dispatch results. Future adapters may add more result variants as their UX requires them.

Extract any CLI-facing answer/resume behavior into reusable application operations before adding richer UX.

Implement:

- core answer operation callable by CLI and future adapters;
- core answer validation operation;
- core resume operation or dispatch helper callable by CLI and future adapters;
- structured results for answered, pending, invalid, wrong-command, and resumed outcomes;
- no direct terminal prompts inside tracker or orchestration core.

Tests:

- core answer operation updates the clarification without CLI parsing;
- core validation rejects malformed manual edits;
- core resume dispatch reports structured wrong-command guidance;
- CLI commands delegate to the shared operations.

### Phase 5: CLI Commands

Status: implemented for the durable stop/answer/resume flow. `devlab resume` validates manually edited answers before invoking a role. Remaining CLI work is improved wrong-command copy and optional future commands such as `--use-default`.

Add `devlab clarify` and `devlab resume`.

Implement:

- `list`;
- `show CLXXXX`;
- `answer CLXXXX --choice ...`;
- `answer CLXXXX --choice ... --note ...`;
- `answer CLXXXX --choice ... --resume`;
- `answer CLXXXX --text ...`;
- `supersede CLXXXX --reason ...`;
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

### Phase 6: Prompt Context

Status: implemented for concise answered clarification context and role prompt conventions. Relevance can be refined later if task/finding `decision_refs` are added.

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

### Phase 7: Reporting And Validation

Status: partially implemented. `status`, `doctor`, and `workflow-state` have clarification coverage. Doctor reuses shared answer validation for answered records, and workflow-state reports blockers plus resume pointers in text, digest, and JSON output. Remaining work is diagnostics counters, answer latency/session-distance reporting, and repeated-request smell detection.

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

### Phase 8: Optional Editor Adapter

Status: remaining and optional.

Add interactive editor support only after durable stop/resume and shared operations are stable.

Implement:

- `--interactive-clarifications` for `devlab plan` and `devlab implement`;
- editor command resolution using `$VISUAL`, then `$EDITOR`;
- answer validation after editor exit;
- resume through stored resume intent when valid;
- stop with ordinary resume guidance when no editor exists or the answer remains invalid.

Tests:

- editor mode opens the configured editor command in a controlled test double;
- valid edited answer resumes;
- invalid edited answer stops or reopens according to the chosen UX;
- missing editor stops with the clarification path and resume instructions.

### Phase 9: Traceability Extensions

Status: deferred.

Add optional `decision_refs` only after the core workflow is stable.

Candidate extensions:

- task front matter `decision_refs`;
- finding front matter `decision_refs`;
- milestone verification references once structured milestone verification exists;
- prompt relevance based on `decision_refs`.

This phase should be deferred until there is enough real usage to know whether scope-based prompt selection is insufficient.

## Resolved Design Choices

Blocking should remain conservative for now. Any pending clarification with `blocks` other than `none` blocks the matching top-level command family instead of trying to route around task- or milestone-specific blockers. This avoids workflow routing complexity and avoids accidentally continuing through unresolved operator intent. The tracker still validates and preserves precise `blocks` values so narrower task/milestone scoping can be added later without changing the file format, but that behavior should wait for concrete usage pain.

Resume validation is worth implementing before scoped blocking. A stored resume pointer must not silently switch to another task, role, or milestone after the operator answers. If the interrupted work no longer exists, is no longer eligible for the interrupted role, has unsatisfied dependencies, or is no longer the selected route, DevLab stops with repair-oriented guidance and preserves the resume pointer for reconciliation.

Clarification files omit `answered_at` while pending and add it only when answered. This keeps front matter meaningful and matches the existing tracker style of omitting optional metadata until it applies.

CLI choice answers should not require `--note`. Selecting a valid option is enough to answer the clarification; `--note` is optional operator rationale.

A clarification request must not be allowed alongside normal role state transitions in the first slice. A role either completes its ordinary transition or asks for clarification and stops. Mixing both would make rollback, auditability, and resume semantics ambiguous.

`blocks = "none"` is allowed in the first implementation for non-blocking decisions that should still be durable and visible. It should be rare, appear in status/reporting, and must not block workflow progress.

`[resume]` supports one active pointer in the first slice. Bounded sessions produce one clarification at a time, so a list would add complexity before there is a real workflow need.

Clear `[resume]` only after the matching command successfully gets past the interrupted blocker, not merely when the answer is written.

Editor mode should allow one reopen prompt after an invalid answer only in explicitly interactive mode. Otherwise DevLab stops, prints the clarification path, and prints exact resume instructions.

Future server/API structured result types should be limited to what the CLI needs now, but core operations must return structured results rather than only printing so later adapters can reuse the same semantics.

## Non-Goals

- Do not add a new clarification role.
- Do not add open-ended interactive chat to the workflow loop.
- Do not implement a DevLab server, REST API, email integration, webhook integration, or web UI in the first clarification slice.
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
