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
DevLab should make its compatibility promises explicit, prove supported upgrades,
make release verification repeatable, and present a concise public demo.

New capabilities should become 1.0 requirements only when evidence shows that
the current workflow cannot satisfy the intended public contract without them.

## Release Outcomes

### 1. [Define the public compatibility contract](https://github.com/djulich/devlab/issues/1)

Document what remains stable throughout 1.x for:

- CLI commands, options, exit behavior, and structured output;
- agent, profile, prerequisite, and managed-test-service configuration;
- durable workspace formats and schema evolution;
- workspace layout, Git mutations, workflow-owned commits, and milestone tags;
- supported Python package APIs, if any; and
- installation, migration, deprecation, and unsupported-state behavior.

Correctness-critical policy must remain enforced in code and tests. Record
surprising or hard-to-reverse compatibility decisions in ADRs.

### 2. [Prove compatibility and repair behavior](https://github.com/djulich/devlab/issues/2)

Add small fixtures for each historical workspace representation that 1.0 promises
to support. Verify that reporting remains non-mutating, supported interrupted
workflows resume correctly, and unsupported formats fail with actionable
diagnostics instead of silent best-effort migration.

### 3. [Make release verification repeatable](https://github.com/djulich/devlab/issues/3)

Provide one repository-owned command that builds the source distribution and
wheel, inspects their contents and metadata, installs the wheel in a clean
environment, and smoke-tests the installed CLI. Publication and tag creation
remain deliberate operator actions.

### 4. [Complete a representative evidence baseline](https://github.com/djulich/devlab/issues/5)

Use existing live scenarios to cover materially different workflow families,
providers, toolchains, and deployment behavior. Calibrate diagnostic thresholds
from labeled results rather than intuition. Keep external grading outside the
evaluated workflow as required by ADR 0011.

Required evidence should be bounded by distinct risk, not by every possible
provider and tool combination.

### 5. [Prepare the public documentation and demo](https://github.com/djulich/devlab/issues/4)

Reconcile the README, operator guide, design, command help, configuration
reference, and release policy with implemented behavior. Provide a short,
repeatable demonstration that starts from a clean target repository and shows
planning, reviewed implementation, durable state, interruption recovery, and
diagnostics without requiring private infrastructure.

### 6. [Rehearse an immutable candidate release](https://github.com/djulich/devlab/issues/6)

Publish at least one pre-1.0 tag, install it outside an editable checkout, and use
it against a representative existing workspace. Release 1.0 only after candidate
use exposes no unresolved issue that requires breaking the proposed 1.x contract.

## 1.0 Release Gates

DevLab 1.0 is ready when:

- public compatibility surfaces and evolution rules are explicit;
- supported historical workspaces have executable compatibility evidence;
- unsupported durable formats fail safely with repair guidance;
- representative scripted and live workflows pass with calibrated diagnostics;
- reporting and validation paths remain demonstrably non-mutating;
- package artifacts build, contain required resources, and install cleanly;
- an immutable candidate has been used outside an editable checkout;
- public documentation and command help agree with implemented behavior; and
- no known correctness or safety issue requires changing a promised 1.x
  contract.

## Post-1.0 or Evidence-Driven Work

The following are useful directions but do not block 1.0 without concrete
evidence:

- multi-session architecture planning for unusually large specifications;
- workflow attention notifications;
- narrower clarification blocking and additional clarification adapters;
- a server or web operator interface;
- administrator-managed trust policy or optional OS sandboxing;
- broader dependency, manifest, and toolchain diagnostics;
- prompt-context reduction beyond current monitoring;
- concurrent role sessions; and
- extraction of a domain-neutral workflow kernel after a second workflow proves
  genuinely shared semantics.

## Maintenance

Update this roadmap when evidence changes a release gate or strategic outcome.
Put concrete work in GitHub Issues, dated evaluation evidence under
`docs/evaluations/baselines/`, durable decisions in ADRs, and temporary unresolved
designs under `docs/proposals/`.
