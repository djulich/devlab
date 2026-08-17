# Revise a Specification

Use this procedure when intended system or deployment behavior changes after a
DevLab plan has been created.

## 1. Edit the authoritative specification

Update the relevant Markdown files under:

```text
.devlab/specs/system/
.devlab/specs/deployment/
```

Keep the change focused and state the new acceptance criteria and constraints.
These files are operator-owned; generated plans and tasks are downstream state,
so do not edit them as a substitute for changing the specification.

## 2. Commit the change

```bash
git add .devlab/specs
git commit -m "Revise project specification"
```

Planning operates against committed specifications and requires a clean working
tree.

## 3. Reconcile planning state

```bash
devlab doctor
devlab plan
```

When committed specifications changed since the recorded baseline, DevLab
archives the previous active generation under `.devlab/generations/` and asks
the architect and planner to create a fresh active planning graph. Previous
state remains historical evidence; still-valid work may be carried forward.

Inspect the new plans, tasks, and milestones, then continue:

```bash
devlab doctor
devlab implement --max-sessions 20
```

## Related planning modes

Use `devlab plan --revise` when the specifications have not changed but you
explicitly want the architect and planner to review the active plans. Use
`devlab plan --replace-plan` when you intentionally want a complete fresh plan.

Use `devlab plan --mark-specs-planned` only for an operator-confirmed typo-only,
format-only, or otherwise plan-neutral specification commit. It advances the
recorded baseline without architect or planner review and therefore bypasses
the normal reconciliation guardrail.
