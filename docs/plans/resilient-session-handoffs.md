# Resilient Session Handoffs

Status: active.

## Purpose

Make an otherwise successful role session recoverable when its handoff does not
satisfy DevLab's artifact contract, without rerunning task work, trusting invented
workflow claims, or leaving partially applied handoff-driven state.

This plan is the implementation reference for handoff recovery. The broader
cross-cutting concerns remain in `architectural-improvements.md`; in particular,
atomic tracker writes and general concurrent-process policy are not expanded into
this feature.

## Problem

A role session can successfully edit the target workspace and still stop the
workflow because `.devlab/session-artifacts/<role>/handoff.md` is missing,
malformed, or inconsistent with durable workflow state. The handoff currently
serves three purposes at once:

- a human-readable account of the completed role session;
- context for later role sessions;
- a machine-readable source of workflow transition facts.

Consequently, a representation error at the end of a session can discard the
orchestrator's ability to accept otherwise useful work. A normal retry is unsafe:
the original session may already have changed product files, task records, or
other target-workspace state, and a fresh ordinary session may duplicate or
reinterpret that work.

Recovery must also account for the current ordering in `run_loop()`: some
planner handoff-driven workflow state can be applied before all later consistency
checks have passed. Retrying on top of partially accepted state would make the
repair evidence ambiguous.

## Goals

- Complete all handoff parsing and semantic validation before applying any
  handoff-driven workflow mutation.
- Give handoff failures stable, typed reason codes and an explicit recovery
  classification.
- Recover bounded representation failures without rerunning the original task.
- Permit at most one constrained agent repair attempt per completed role session.
- Enforce that repair changes only the failed handoff artifact.
- Preserve the invalid artifact, repair attempt, validation outcome, and session
  provenance for diagnosis.
- Keep CLI exit-code behavior unchanged unless a separate policy is adopted.
- Retain one role per ordinary session and one task per developer/reviewer
  session.

## Non-goals

- Do not automatically retry an ordinary developer, reviewer, planner,
  integrator, or architect session after a handoff failure.
- Do not let a repair agent edit product files or durable workflow state.
- Do not repair semantic contradictions by choosing whichever claim makes the
  workflow continue.
- Do not add unbounded retries or allow a repair session to request another
  repair session.
- Do not add concurrent agents, general workspace rollback, or a database.
- Do not depend on provider-specific structured-output support.
- Do not split narrative and machine-readable handoff artifacts in the first
  recovery slice; that is a later protocol improvement described below.

## Recovery Policy

Use the following lifecycle after an agent provider reports success:

```text
role session completes
    -> refresh read-only workspace state
    -> parse and validate the complete handoff
    -> if recoverable, perform at most one constrained repair
    -> parse and validate again from the beginning
    -> apply handoff-driven workflow mutations
    -> archive the accepted handoff and continue normal integration
```

No workflow mutation derived from the handoff may occur before the validation
phase succeeds. Product and workflow edits made directly by the original role
session remain present and are evidence for validation, but they must be frozen
during repair.

### Failure categories

Introduce a stable reason enum owned by `handoffs.py`, with human-readable
messages carried separately. Exact names can be refined during implementation,
but callers must not branch on message text.

Initial categories:

| Category | Example reasons | Default policy |
| --- | --- | --- |
| Missing artifact | file absent or empty | constrained repair |
| Representation | missing/duplicate/out-of-order heading, malformed structured section, invalid field shape | deterministic repair when provably lossless; otherwise constrained repair |
| Semantic | unknown finding/task mapping, reviewer outcome mismatch, planner state contradiction, unsubstantiated completion state | stop; allow original-role repair only for explicitly classified cases with sufficient evidence |
| Safety/limits | oversized artifact, repair changed forbidden paths, unreadable file | stop |
| Reported failure | handoff declares an unrecoverable issue | stop |

Each raised validation failure should expose at least:

```python
class HandoffFailureReason(StrEnum): ...

class HandoffError(ValueError):
    reason: HandoffFailureReason
    message: str
    repairability: HandoffRepairability
```

`HandoffRepairability` should distinguish deterministic repair, constrained agent
repair, and non-repairable failure. The reason-to-policy mapping belongs in code,
not prompts.

Start conservatively. A failure becomes repairable only when tests demonstrate
that the repair does not require inventing role intent. Unknown failures stop.

## Validation Before Mutation

Refactor post-session handling into two conceptual phases while keeping workflow
policy visible in `orchestrator.py`:

1. **Prepare**: parse the handoff and validate its contract, role-specific
   assertions, clarification request, addressed findings, planner preservation,
   planner progress, and any other preconditions against a read-only snapshot.
2. **Apply**: update planner workflow state, create clarification/finding records,
   transition tasks or milestones, archive the accepted handoff, and perform the
   existing version-control integration.

Preparation should return a small immutable value only if it avoids repeating
expensive parsing or captures validated transition facts. It must not become a
second orchestration layer or move tracker-owned parsing out of `handoffs.py`.

Acceptance:

- every `HandoffError` reachable during preparation leaves handoff-driven
  workflow state unchanged;
- planner consistency checks occur before `_apply_planner_workflow_state()`;
- `process_handoff()` is called only with a fully validated handoff;
- focused tests compare relevant workflow files before and after each failure.

## Deterministic Repair

Add deterministic normalization only for transformations proven to preserve
meaning. The initial implementation may deliberately support none if no existing
failure can be repaired without interpretation.

Permitted candidates include line-ending normalization or removal of an exact
duplicate empty optional section. Reordering or synthesizing headings is allowed
only when section boundaries and content are unambiguous.

Rules:

- never synthesize substantive section content;
- never change identifiers, decisions, approval claims, planning completion,
  clarification choices, or open-issue meaning;
- preserve the original invalid bytes before replacement;
- record which transformation was applied;
- re-run the complete parser and semantic validator afterward;
- use atomic replacement when the shared atomic-write helper is available.

## Constrained Agent Repair

The first implementation should reuse the failed session's role/provider
configuration with a repair-only prompt. This preserves ownership of semantic
claims and avoids introducing a new configurable role before evaluations show a
specialist is useful. The repair invocation is not an ordinary workflow role
session and must not perform the role's task again.

The prompt should include:

- the original role, session, task, and milestone identifiers;
- the precise typed failure reason and human-readable diagnostic;
- the invalid handoff content, clearly delimited as data;
- the handoff contract or canonical template;
- relevant read-only task/milestone/finding state;
- a concise changed-path summary from the original role session;
- instructions to inspect existing evidence, replace only the handoff, avoid
  new claims, and leave all other files untouched.

The orchestrator must enforce the prompt contract:

- snapshot target-workspace paths before repair using the existing resolver
  isolation machinery where it fits;
- permit only the failed role's `handoff.md` to change;
- reject symlink/path escapes and changes to any workflow or product file;
- do not run the role's ordinary environment lifecycle unless a later evidenced
  requirement justifies it;
- allow exactly one repair invocation;
- validate the repaired handoff from the beginning;
- never recursively repair a repair result.

If enforcement detects another changed path, stop and leave the unexpected edit
for operator inspection. Do not perform broad rollback that could discard
pre-existing operator changes.

## Artifact Preservation and Observability

Do not overwrite the only evidence of the failure. Before repair, copy the
invalid artifact into session history or a repair-specific artifact directory
with the original session identifier. Record:

- original session identifier and role;
- failure reason and diagnostic;
- repair kind (`deterministic` or `agent`);
- repair invocation identifier when applicable;
- repaired artifact path;
- final validation result;
- unexpected changed paths, if any.

Session metadata and diagnostics should distinguish:

- initial handoff validation failure recovered successfully;
- repair attempted and rejected;
- non-repairable handoff failure;
- repair invocation/provider failure.

Do not report a repair attempt as another completed developer/reviewer task
cycle. It may count toward the overall session budget only if that policy is made
explicit alongside structured `RunResult` stop reasons. Until then, expose a
separate repair-attempt count and preserve current CLI exit behavior.

## Configuration

Begin with conservative built-in defaults:

```toml
[handoff_repair]
enabled = false
max_attempts = 1
```

The exact configuration location should follow the existing agent/workflow
configuration boundary. Enabling repair must be an explicit operator choice in
the first release because repair invokes another paid agent session. A future
default change should be based on evaluation evidence.

Do not initially add a `handoff-fixer` workflow role. If evaluations demonstrate
that a specialized configuration materially improves repair success, add an
optional repair-agent configuration in `agent_config.py` and keep its invocation
mechanics in `agents.py`. Repair selection and policy remain in
`orchestrator.py`.

## Implementation Slices

### 1. Typed failures and read-only preparation

- Add typed handoff failure reasons and repairability.
- Convert parser and orchestrator semantic validation without string matching.
- Reorder planner and other checks so all validation precedes handoff-driven
  mutation.
- Add focused no-mutation tests for failed preparation.

This slice is independently valuable and is a prerequisite for every retry
policy.

### 2. Repair artifacts and deterministic framework

- Preserve invalid artifacts and add repair metadata.
- Add the bounded repair dispatcher and deterministic-repair interface.
- Implement only proven lossless repairs.
- Revalidate completely and test preservation on failed repair.

### 3. One constrained repair invocation

- Add opt-in configuration and repair-only prompt assembly.
- Invoke the failed role's provider configuration without ordinary task or
  environment execution.
- Enforce handoff-only edits and a single attempt.
- Add successful, still-invalid, provider-failure, and forbidden-edit tests.

### 4. Evaluation and specialist decision

- Add scripted malformed-handoff scenarios for representative roles.
- Record repair success by reason, added invocation cost, and false-repair or
  forbidden-edit rates.
- Decide from evidence whether to add a configurable specialist handoff repair
  agent.

### 5. Structured transition manifest exploration

After recovery is stable, evaluate splitting the current artifact into:

- a small structured transition manifest used for orchestration decisions;
- a Markdown narrative retained for humans and later role context.

The manifest should be provider-neutral, bounded in size, atomically written,
and semantically validated against tracker state. This is not required for the
initial recovery implementation because structured syntax alone cannot make
agent claims true.

## Testing

Focused tests should cover:

- every typed failure reason and its recovery classification;
- validation failures causing no handoff-driven mutation;
- a valid handoff preserving all existing behavior;
- one successful constrained repair followed by normal processing;
- a repaired artifact that remains invalid;
- a repair agent that fails or times out;
- a repair attempt that edits an unauthorized path;
- no second repair attempt after any repair outcome;
- preservation and attribution of original and repaired artifacts;
- unchanged CLI exit behavior for unrecovered failures;
- diagnostics that do not count repair as an ordinary task cycle.

Run after each slice:

```bash
uv --cache-dir /tmp/uv-cache run ruff check src tests
uv --cache-dir /tmp/uv-cache run pytest
```

## Completion Criteria

The initial feature is complete when an explicitly enabled DevLab run can recover
from a representative malformed handoff through one enforced handoff-only repair
invocation, while semantic contradictions stop safely, all rejected paths leave
handoff-driven workflow state unchanged, and the complete failure/repair history
remains available for operator diagnosis.
