# Roadmap to DevLab 1.0

DevLab is pre-1.0 software with a working end-to-end workflow. The route to 1.0
focuses on stabilizing and demonstrating the existing product rather than adding
broad feature surface.

This document records strategic outcomes and release gates. GitHub Issues and
milestones should hold owners, priorities, implementation checklists, and other
actionable work.

Actionable 1.0 work is tracked in the
[DevLab roadmap project](https://github.com/users/djulich/projects/1) and the
[DevLab 1.0 stabilization milestone](https://github.com/djulich/devlab/milestone/1).

## Current Direction

The core software workflow is implemented and exercised by deterministic tests,
scripted evaluations, and a growing set of live-agent baselines. Before 1.0,
DevLab should refine the operator model without premature compatibility
constraints, make release verification repeatable, and present a concise public
demo. The public compatibility contract and immutable baseline are frozen only
after a release candidate has exercised the resulting interfaces.

New capabilities should become 1.0 requirements only when evidence shows that
the current workflow cannot satisfy the intended public contract without them.

## Release Outcomes

### Compatibility freeze — deferred to the 1.0 candidate

Issues [#1](https://github.com/djulich/devlab/issues/1) and
[#2](https://github.com/djulich/devlab/issues/2) established useful format-safety
and release-policy groundwork, but their proposed baseline was deliberately
withdrawn before release. There are no external users or deployed workspaces to
support, and preserving an imagined baseline would constrain necessary operator
and format changes during `0.x`.

The immutable baseline and executable compatibility suite must instead be
created from the exercised 1.0 release candidate. Until then, current-format
validation and refusal before unsafe mutation remain required, but historical
development representations are not supported interfaces.

### Issue #3 — [Add repeatable package and release verification](https://github.com/djulich/devlab/issues/3)

Provide one repository-owned command that builds the source distribution and
wheel, inspects their contents and metadata, installs the wheel in a clean
environment, and smoke-tests the installed CLI. Publication and tag creation
remain deliberate operator actions.

### Issue #5 — [Complete and calibrate the representative live baseline](https://github.com/djulich/devlab/issues/5)

Use existing live scenarios to cover materially different workflow families,
providers, toolchains, and deployment behavior. Calibrate diagnostic thresholds
from labeled results rather than intuition. Keep external grading outside the
evaluated workflow as required by ADR 0011.

Required evidence should be bounded by distinct risk, not by every possible
provider and tool combination.

### Issue #4 — [Prepare the public repository and colleague demo](https://github.com/djulich/devlab/issues/4)

Reconcile the README, operator guide, design, command help, configuration
reference, and release policy with implemented behavior. Provide a short,
repeatable demonstration that starts from a clean target repository and shows
planning, reviewed implementation, durable state, interruption recovery, and
diagnostics without requiring private infrastructure.

### Issue #6 — [Rehearse an immutable pre-1.0 release](https://github.com/djulich/devlab/issues/6)

Publish at least one pre-1.0 tag, install it outside an editable checkout, and use
it against a representative existing workspace. Once candidate use exposes no
unresolved issue requiring an interface or format break, define the 1.x contract,
capture its immutable fixture, and verify that the candidate satisfies it before
releasing 1.0.

## 1.0 Release Gates

DevLab 1.0 is ready when:

- public compatibility surfaces and evolution rules have been frozen from an
  exercised release candidate;
- the candidate workspace representation has an independently authored,
  executable compatibility baseline;
- unsupported durable formats fail safely with repair guidance;
- representative scripted and live workflows pass with calibrated diagnostics;
- reporting and validation paths remain demonstrably non-mutating;
- package artifacts build, contain required resources, and install cleanly;
- an immutable candidate has been used outside an editable checkout;
- public documentation and command help agree with implemented behavior; and
- no known correctness or safety issue requires changing the candidate 1.x
  contract.

## Post-1.0 or Evidence-Driven Work

The following are useful directions but do not block 1.0 without concrete
evidence:

- multi-session architecture planning for unusually large specifications;
- optional workflow attention notifications, including best-effort webhook
  delivery that does not control workflow outcomes;
- narrower clarification blocking and additional clarification adapters;
- broader research lifecycle support, such as cancellation and additional
  requesting roles, when live use justifies it;
- a server-backed operator interface with a REST API over workflow operations
  and a GUI for status, continuation, bounded stop requests, and validated
  recovery or restart;
- administrator-managed trust policy or optional OS sandboxing;
- broader dependency, manifest, and toolchain diagnostics;
- prompt-context reduction beyond current monitoring;
- external task-tracker adapters that preserve the task-tracker boundary and
  current workflow semantics;
- concurrent role sessions; and
- extraction of a domain-neutral workflow kernel after a second workflow proves
  genuinely shared semantics.

The server direction is deliberately not current implementation work. If a
concrete remote-operation use case promotes it, the server, webhook delivery,
and GUI should be adapters over the same repository-backed state and structured
operations as the CLI, not a second workflow authority. A request to stop should
take effect at a safe bounded-session boundary; recovery or restart must preserve
the existing authorization, clarification, reconciliation, and interruption
contracts rather than bypassing them or relying on hidden server state. Introduce
an internal event-observer abstraction only when multiple concrete consumers
justify it.

## Promoting Directions to Issues

Promote a roadmap direction to an actionable GitHub Issue only when:

- concrete evidence or a real use case justifies the work;
- the outcome can be bounded as an implementation, evaluation spike, or design
  decision;
- objective acceptance criteria can show when it is complete;
- prerequisites and correctness-critical constraints are understood; and
- the work is plausible to prioritize in an upcoming development cycle.

When uncertainty itself can be tested, open a bounded evaluation issue rather
than an implementation issue. For a cross-cutting design, open the issue first,
add a temporary proposal only when meaningful alternatives require review, and
record accepted hard-to-reverse decisions in an ADR. Add promoted issues to the
project as `Todo`; assign a release milestone only when the outcome is genuinely
required for that release. Do not use issues as a parking lot for every deferred
direction. Revisit unpromoted directions when new evaluation evidence, operator
needs, or release planning supplies a concrete trigger.

## Maintenance

Update this roadmap when evidence changes a release gate or strategic outcome.
Put concrete work in GitHub Issues, dated evaluation evidence under
`docs/evaluations/baselines/`, durable decisions in ADRs, and temporary unresolved
designs under `docs/proposals/`.
