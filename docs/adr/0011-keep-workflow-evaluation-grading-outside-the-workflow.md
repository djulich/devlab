# ADR 0011: Keep Workflow Evaluation Grading Outside the Workflow

## Status

Accepted.

## Context

DevLab's regular software workflow already has bounded self-correction. Reviewer
rejection returns a task to development. Integrator validation failures and
integration or architecture-review issues create durable findings that route
through planning and corrective tasks.

Workflow evaluations serve a different purpose. Scripted and live evaluations
run the normal workflow in a temporary target repository and then independently
grade the resulting system with structural, behavioral, documentation, hygiene,
and tool-backed black-box checks. Some evaluation checks overlap requirements
or target-owned validation, but they are evidence about the workflow's result,
not another workflow role or validation profile.

Feeding evaluation failures back into the evaluated workflow would allow the
workflow to converge on grader implementation details that were not available
during ordinary operation. A run that passes only after external grader coaching
would no longer measure whether the regular workflow independently produced the
expected result. It would also make outcomes and session counts less comparable
across DevLab versions, agent providers, and configurations.

## Decision

Workflow evaluation grading remains outside the evaluated DevLab workflow.
Evaluation checks run after the evaluated workflow stops and report pass or
failure against the resulting target state.

Evaluation check results must not:

- create or update durable findings, tasks, milestones, or clarifications in the
  evaluated workflow;
- reopen completed work or resume the evaluated workflow;
- invoke additional role sessions to correct the graded target; or
- turn eventual success after grader feedback into success for the original
  evaluated run.

The evaluation harness may persist evaluation-owned diagnostics, logs, and
result copies. Those artifacts record grading evidence; they do not become
authoritative workflow input.

Normal workflow-visible evidence remains inside the self-correction loop. This
includes committed specifications and project knowledge, task acceptance
criteria, target-owned profile and milestone validation commands, reviewer
outcomes, and integrator or architecture-review findings. An evaluation may
independently repeat or strengthen those checks after completion without making
their results visible to the evaluated workflow.

Evaluation failures may motivate a later change to DevLab, its documented
workflow policy, prompts, or the evaluation scenario. Such a change is evaluated
in a new run; it does not repair or reclassify the failed run.

## Consequences

- Evaluation results measure the regular workflow's unassisted output rather
  than its ability to optimize iteratively against an external grader.
- Failed live runs remain useful evidence even when the generated defect is
  small or mechanically repairable.
- Provider, configuration, and DevLab-version comparisons retain meaningful
  first-run role sequences, rework counts, and outcomes.
- Evaluation contracts must state externally enforced requirements precisely;
  hidden or accidentally narrower checker expectations are evaluation defects,
  not feedback for the generated target.
- The regular workflow may still self-correct the same underlying problem when
  its own specifications, validation, reviewer, integrator, or architect expose
  it before completion.
- Evaluation diagnostics can explain failures but cannot make an evaluated
  target pass.
