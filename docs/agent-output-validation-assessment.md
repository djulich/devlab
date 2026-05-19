# Agent output validation: safe-default assessment

Assessment of all orchestrator validation points against the "assume the work isn't done" principle (ADR 0007). Written after applying the principle to reviewer validation; this document captures which other validations could be softened and which should stay strict.

## Principle

When an agent produces conflicting or incomplete structured output, default to the least damaging assumption rather than halting. An unnecessary extra cycle is self-correcting; prematurely advancing is not.

## Validation points

### Handoff parsing (`handoffs.py: parse_handoff`)

**Verdict: stay strict.**

Missing, empty, or structurally malformed sections mean the handoff is uninterpretable. There is no agent intent to fall back on — the orchestrator cannot determine what the agent meant. This is a structural contract violation, not ambiguous output.

### "unrecoverable" keyword (`orchestrator.py: validate_handoff`)

**Verdict: stay strict.**

The agent is explicitly requesting a stop. Ignoring it would contradict the agent's own assessment. The safe default here *is* to stop.

### Reviewer outcome mismatch (`orchestrator.py: _validate_reviewer_outcome`)

**Verdict: softened (done).**

See ADR 0007. Mismatch between handoff open-issues and task approval checkbox defaults to `changes_requested`. Both signals must agree to close a task.

### Planner addressed findings (`orchestrator.py: _validate_planner_addressed_findings`)

**Verdict: keep strict for now; observe live runs before changing.**

Planner addressed-findings validation protects the invariant that a finding is only marked `planned` when the planner provides an explicit valid finding-to-task mapping and each task confirms that relation with `addresses_findings` metadata. Softening too early could hide prompt/workflow problems or burn sessions in a planner loop.

Three error cases currently halt the workflow:

1. **Unknown finding ID** — planner references a finding that doesn't exist. Likely a hallucination or typo. Safe default: skip the mapping, log a warning. The finding (if it actually exists under a different ID) stays open and triggers replanning.

2. **Unknown task ID** — planner claims a task addresses a finding, but the task file doesn't exist. Same cause and same safe default: skip the mapping.

3. **Task doesn't list finding in `addresses_findings` metadata** — planner wrote the correct handoff text ("F0001: T0002") but forgot to add `addresses_findings = ["F0001"]` to T0002's front matter. This is the most likely real-agent failure mode, analogous to the reviewer's missing checkbox. Safe default: skip the mapping, finding stays open, planner gets re-invoked.

All three cases could theoretically share the same fallback: ignore the bad mapping, leave the finding open, and let the next planner cycle fix it. That fallback is less obviously safe than reviewer mismatch handling because it may create repeated planner cycles unless diagnostics are excellent.

Current decision: leave this validation strict until more live evaluations show whether malformed mappings are common and which failure mode dominates. If live runs mostly show case 3 with otherwise valid IDs, consider softening only that case. If failures include hallucinated IDs or confusing mappings, improve prompts and diagnostics first.

When this validation fails in live runs, capture the exact error, handoff path, agent log paths, retained prompt paths if enabled, and whether rerunning the planner repairs the issue.

### Developer acceptance criteria (`orchestrator.py: process_handoff`)

**Verdict: already follows the principle.**

If acceptance criteria are not complete, the task stays open and the developer is re-invoked. No validation error is raised.

### Reviewer "no task awaiting review" (`orchestrator.py: _validate_reviewer_outcome`)

**Verdict: stay strict.**

This is a structural precondition — the orchestrator selected the reviewer role but no task is in `in_review` status. This indicates a bug in role selection logic, not agent sloppiness. No safe default can fix it.

## Summary

| Validation | Current | Recommendation |
|---|---|---|
| Handoff structure (parse) | Strict | Keep strict |
| "unrecoverable" keyword | Strict | Keep strict |
| Reviewer outcome mismatch | Softened | Done (ADR 0007) |
| Planner addressed findings | Strict | Keep strict pending live-eval evidence |
| Developer acceptance | Already soft | No change needed |
| Reviewer no task | Strict | Keep strict |
