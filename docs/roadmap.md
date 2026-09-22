# DevLab Roadmap

This document is authoritative for DevLab's strategic direction and release
gates. The [DevLab roadmap project](https://github.com/users/djulich/projects/1)
tracks actionable work across releases and product-lifecycle milestones. Linked
GitHub Issues hold concrete scope, acceptance criteria, and implementation work;
GitHub milestones group that work by release or another significant lifecycle
event.

## Current Release Focus: DevLab 1.0

DevLab is pre-1.0 software with a working end-to-end workflow. The route to 1.0
focuses on stabilizing and demonstrating the existing product rather than adding
broad feature surface.

The core software workflow is implemented and exercised by deterministic tests,
scripted evaluations, and a growing set of live-agent baselines. Before 1.0,
DevLab should refine the operator model without premature compatibility
constraints, make release verification repeatable, and present a concise public
demo. The public compatibility contract and immutable baseline are frozen only
after a release candidate has exercised the resulting interfaces.

New capabilities should become 1.0 requirements only when evidence shows that
the current workflow cannot satisfy the intended public contract without them.

## 1.0 Outcomes

The [DevLab 1.0 stabilization milestone](https://github.com/djulich/devlab/milestone/1)
groups the actionable work for these outcomes. The roadmap project reflects the
current status of the linked issues.

### Freeze compatibility from an exercised candidate

Issues [#1](https://github.com/djulich/devlab/issues/1) and
[#2](https://github.com/djulich/devlab/issues/2) established useful format-safety
and release-policy groundwork, but their proposed baseline was deliberately
withdrawn before release. Those development representations were not adopted
as a public compatibility contract; treating them as a frozen baseline would
constrain necessary operator and format changes during `0.x`.

The immutable baseline and executable compatibility suite must instead be
created from the exercised 1.0 release candidate. Until then, current-format
validation and refusal before unsafe mutation remain required, but historical
development representations are not supported interfaces.

### Make public use understandable and reproducible

Public documentation, command help, configuration guidance, and release policy
should agree with implemented behavior. Installation must work from a clean
clone, and a bounded, repeatable demonstration should show planning, reviewed
implementation, durable state, interruption recovery, diagnostics, and final
verification without depending on private infrastructure.

### Back product claims with representative evidence

Use existing live scenarios to cover materially different workflow families,
providers, toolchains, and deployment behavior. Calibrate diagnostic thresholds
from labeled results rather than intuition. Keep external grading outside the
evaluated workflow as required by ADR 0011.

Required evidence should be bounded by distinct risk, not by every possible
provider and tool combination.

### Verify releases independently of the development checkout

Repository-owned verification should build and inspect release artifacts,
install them in a clean environment, and smoke-test the installed CLI. A tagged
pre-1.0 candidate must be installed outside an editable checkout and exercised
against representative new and existing workspaces before the 1.x contract is
frozen. Publication remains a deliberate operator action.

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

## Future or Evidence-Driven Directions

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
Put concrete work in GitHub Issues and track it in the roadmap project. Use
milestones to group work by release or another significant product-lifecycle
event. Put dated evaluation evidence under `docs/evaluations/baselines/`, durable
decisions in ADRs, and temporary unresolved designs under `docs/proposals/`.
