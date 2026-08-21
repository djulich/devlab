# Roadmap to DevLab 1.0.0

Status: proposed stabilization roadmap.

## Goal

Release DevLab 1.0.0 with an explicit, evidence-backed compatibility contract
for its CLI, target-workspace formats, configuration, installation, and durable
workflow behavior.

The core software workflow is already implemented and covered by deterministic
tests, scripted evaluations, and a growing set of live-agent baselines. The
remaining path to 1.0 is therefore primarily stabilization: finish calibrating
the current behavior, decide which public surfaces are stable, prove supported
upgrade paths, rehearse packaging and releases, and reconcile documentation
with the resulting contract.

This roadmap does not make every open feature in `docs/todo.md` a 1.0 blocker.
New capabilities should enter the critical path only when evaluation evidence
shows that the existing workflow cannot meet the intended 1.0 contract without
them.

## Current baseline

At the start of this roadmap:

- the package version is `0.1.0`, and no immutable release tag has yet been
  created;
- the Git-backed workflow, durable role handoffs, task review and rework,
  milestone integration, architecture review, spec reconciliation, executable
  configuration authorization, clarifications, and research sessions are
  implemented;
- deterministic workflow evaluations cover representative command-line, API,
  frontend, and deployment scenarios;
- opt-in live evaluations exist for representative agent-driven scenarios;
- Rust, Go, C, and C++ dedicated-profile live baselines are complete;
- direct dependency-introduction diagnostics are implemented but still require
  realistic calibration; and
- `docs/release-policy.md` identifies compatibility surfaces, but does not yet
  define a complete 1.0 support and evolution contract for each surface.

## Principles

- Prefer evidence and contract clarification over adding feature breadth.
- Keep black-box evaluation grading outside the evaluated workflow, as required
  by ADR 0011.
- Treat reporting and validation paths as read-only.
- Preserve repository files as authoritative workflow state.
- Keep software-workflow policy explicit; do not extract a generic workflow
  kernel without a concrete second workflow.
- Do not install missing host or target tools. Record unverified prerequisites.
- Do not turn advisory quality or dependency warnings into workflow findings,
  tasks, or blocking policy without labeled evidence.
- Use pre-1.0 releases to discover contract problems before promising semantic
  compatibility.

## Phase 1: Complete current diagnostic calibration

Calibrate dependency-introduction diagnostics using the existing React/Vite
live scenario when a configured provider and Podman environment are available.
If that environment is unavailable, add a focused scripted evaluation that
uses the ordinary session metadata, diagnostics, and run-summary path.

Verify that:

1. each addition is attributed to the introducing session and product task;
2. direct `package.json` dependencies appear exactly once;
3. lockfile and transitive dependencies do not appear;
4. later sessions do not repeat an earlier session's warning;
5. `devlab diagnostics --json`, verbose text diagnostics, and the structured
   final run summary agree; and
6. warnings remain advisory and do not affect task closure, black-box grading,
   workflow exit status, or milestone completion.

Record false positives, false negatives, and calibration conclusions in
`docs/plans/dependency-introduction-diagnostics.md`. Change the roadmap in
`docs/todo.md` only if the evidence changes the intended scope.

Exit criteria:

- the end-to-end reporting path has deterministic or live evaluation coverage;
- warning provenance and deduplication are demonstrated;
- no known high-frequency false positive remains in the supported manifest
  scope; and
- no new manifest, registry, constraint, or blocking behavior is added without
  separate evidence.

## Phase 2: Establish a representative live release baseline

Complete a bounded live-evaluation matrix. The purpose is to verify distinct
workflow behavior, not to collect every provider/toolchain combination.

Required evidence:

- one initial successful React/Vite frontend baseline;
- one current static-frontend baseline;
- the existing stateful API baselines, extended only to a materially different
  available provider environment;
- one additional deployable-API baseline when it adds distinct provider or
  deployment evidence; and
- the existing completed Rust, Go, C, and C++ profile baseline.

Use these runs to calibrate the remaining quality-warning thresholds, especially
sessions per closed task, same-task rework, and integrator finding warnings.
Record both passing and failing outcomes. A failed external grader is evaluation
evidence only: it must not create target findings or corrective tasks, reopen
workflow state, or cause repairs to a temporary generated target.

Exit criteria:

- each materially distinct 1.0 workflow family has at least one current live
  result or a documented reason it is not a release claim;
- warning thresholds are either supported by labeled evidence or explicitly
  retained as provisional advisory signals;
- generated targets finish cleanly with expected workflow provenance; and
- no uncovered correctness failure requires a public-contract change.

## Phase 3: Define and freeze the 1.0 compatibility contract

Turn the compatibility-surface list in `docs/release-policy.md` into explicit
support decisions. For every public surface, document what is stable in 1.x,
what may evolve compatibly, and how unsupported input fails.

Decisions required:

### CLI

- stable command and option names;
- exit-status semantics, including successful stops and operator-action stops;
- stability expectations for normal text output;
- versioned or otherwise documented structured JSON output; and
- deprecation and removal policy.

### Python package

- identify intentionally public importable APIs, if any;
- otherwise state that the console command is the supported interface and
  internal modules are not a stable API; and
- preserve thin CLI adapters over reusable workflow operations where already
  established without promising speculative server APIs.

### Configuration

- `.devlab/config/agents.toml` provider and role-resolution semantics;
- profile inheritance, lifecycle, validation, and missing-tool behavior;
- executable-configuration fingerprint and authorization semantics; and
- rules for compatible additions versus migrations.

### Durable workspace formats

- tasks, milestones, findings, clarifications, research, workflow state,
  workflow events, generations, session metadata, handoffs, and structured
  result envelopes;
- which fields are required, optional, extensible, or versioned;
- unknown-field and unknown-version behavior;
- minimum supported pre-1.0 representations; and
- repair or migration behavior for unsupported states.

### Workspace layout and Git behavior

- stable `.devlab/` layout expectations;
- reporting paths that must remain non-mutating;
- Git repository and cleanliness requirements;
- workflow-owned commits and milestone tags; and
- spec-reconciliation and generation replacement guarantees.

Where a decision is surprising, hard to reverse, or trade-off based, record it
in an ADR. Put agent-critical terminology in `CONTEXT.md`, not only in prose
documentation.

Exit criteria:

- `docs/release-policy.md` describes the concrete 1.x contract rather than only
  listing surfaces;
- public versus internal Python APIs are explicit;
- schema evolution and unsupported-version behavior are defined;
- all known intentional pre-1.0 breaks have migration guidance; and
- correctness-critical policy remains enforced in code and tests rather than
  being delegated to prompts.

## Phase 4: Add compatibility and upgrade fixtures

Create representative archived target-workspace fixtures for every historical
representation that the 1.0 contract promises to support. Keep the fixtures
small and focused on compatibility boundaries rather than copying complete live
evaluation repositories.

For each supported fixture, verify as applicable that current DevLab can:

- run `doctor`, `status`, `diagnostics`, and `workflow-state` without mutation;
- report the same state on repeated reads;
- parse historical handoffs and session metadata;
- resume supported interrupted clarification or research routes;
- continue eligible task and milestone work;
- reconcile changed specifications and archive generations safely; and
- produce precise repair guidance instead of silently guessing when the state
  is unsupported.

Add explicit negative fixtures for newer unknown schema versions, malformed
authoritative state, stale resume pointers, and incompatible executable
configuration. Do not implement broad best-effort migration that obscures an
unsupported state.

Exit criteria:

- the minimum supported workspace version has executable test evidence;
- all read-only compatibility checks assert that no files changed;
- resume and mutation tests pass through `Workspace` and its domain handles;
- unsupported formats fail with actionable diagnostics; and
- adding a future breaking format change will cause a focused compatibility
  test to fail.

## Phase 5: Make release verification repeatable

Implement a repository-owned release verification path for the mechanical parts
of `docs/release-policy.md`. This is release correctness, not full publication
automation.

The verification must:

- build both the source distribution and wheel;
- verify package name, version, Python requirement, classifiers, project URLs,
  and Apache license metadata;
- verify that packaged prompts and required documentation/resources are present;
- install the wheel into a clean temporary environment;
- smoke-test `devlab --version` and `devlab --help` from that installation;
- confirm that the installed version matches `pyproject.toml` and `uv.lock`; and
- leave repository state clean or place disposable output only in an explicit
  ignored/temporary location.

Keep tag creation and publication as deliberate operator actions. Do not add
automatic PyPI publishing unless publication itself becomes an approved release
goal.

Exit criteria:

- one documented command performs the repeatable mechanical verification;
- the check runs independently of an editable checkout;
- missing packaged resources or version disagreement cause clear failures; and
- the release procedure refers to the implemented verification path.

## Phase 6: Reconcile operator documentation with behavior

Audit the README, operator guide, design overview, release policy, command help,
and initialization output against current implementation and the frozen 1.0
contract.

At minimum:

- remove stale maturity statements, including any claim that configured
  orchestrator-owned task validation is still deferred when current behavior
  executes and records it;
- state the supported workflow families and evidence without implying broader
  guarantees than the evaluation baseline supports;
- document the trust boundary around target-owned executable configuration and
  dependency warnings consistently;
- document supported upgrade and repair paths;
- distinguish stable CLI/file contracts from changeable packaged prompt prose;
  and
- provide installation examples using immutable release tags rather than
  relying on `main`.

Exit criteria:

- documented commands and examples pass when followed from a clean environment;
- the maturity section matches current evaluation evidence;
- current limits are explicit; and
- no known documentation statement contradicts code, tests, or the compatibility
  contract.

## Phase 7: Rehearse pre-1.0 releases

Do not move directly from an untagged `0.1.0` development state to `1.0.0`.
Exercise the release and installation contract through immutable pre-1.0 tags.

Recommended sequence:

1. `0.2.0`: package the existing stabilized feature set, complete release
   verification, and install it from the immutable tag in at least one clean
   environment.
2. `0.3.0` or `1.0.0-rc.1`: freeze the proposed compatibility contract, run the
   compatibility fixtures, and solicit real use without accepting casual format
   changes.
3. `1.0.0`: release only when candidate use has exposed no unresolved issue that
   requires breaking a promised contract.

For each rehearsal:

- follow `docs/release-policy.md` completely;
- run `make check`;
- run the scripted evaluations and risk-relevant live evaluations;
- retain the release verification and evaluation results;
- install from the immutable tag, not from the development checkout;
- exercise a representative plan/implement/reporting workflow; and
- document notable changes and migrations.

The exact version sequence may change if the first rehearsal reveals a breaking
contract correction. The important requirement is at least one externally
installable immutable candidate before 1.0.0.

Exit criteria:

- an immutable candidate tag installs and operates successfully;
- at least one representative existing workspace is opened and continued by the
  installed candidate;
- release artifacts and retained evidence support the documented claims; and
- candidate feedback has no unresolved contract-breaking issue.

## Phase 8: Release 1.0.0

Prepare 1.0.0 only after all preceding gates pass.

Release checklist:

1. Review changes since the last candidate and classify compatibility impact.
2. Resolve or explicitly defer all release-blocking defects.
3. Set `pyproject.toml` and `uv.lock` to `1.0.0`.
4. Complete release notes and migration guidance.
5. Run `make check`.
6. Run compatibility fixtures and scripted workflow evaluations.
7. Run the bounded live release baseline justified by changed behavior.
8. Run the repeatable package verification from a clean environment.
9. Verify documentation and immutable-tag installation instructions.
10. Commit the release preparation and create annotated tag `v1.0.0`.
11. Verify the tagged commit is clean and installation from the tag succeeds.
12. Push only when the release is ready to share.

## 1.0 release gates

DevLab 1.0.0 is ready when all of the following are true:

- the public compatibility surfaces and their evolution rules are explicit;
- supported historical workspaces have automated compatibility fixtures;
- unsupported durable formats fail safely with actionable guidance;
- representative scripted and live workflows pass with calibrated diagnostics;
- reporting and validation paths remain demonstrably non-mutating;
- package artifacts build, contain required resources, and install cleanly;
- at least one immutable pre-1.0 candidate has been used outside an editable
  development checkout;
- README, operator documentation, command help, and release policy agree with
  implemented behavior;
- no known correctness or safety issue requires changing a promised 1.x
  contract; and
- the full development validation passes on the release commit.

## Work that does not block 1.0 by default

The following remain useful roadmap items but should not delay 1.0 without
concrete evidence that they are required for the promised contract:

- multi-session architecture planning;
- workflow attention notifications;
- a server or web operator interface;
- editor-mode clarification answering;
- narrower clarification blocking scopes;
- administrator-managed trust policy or OS sandboxing;
- registry verification or blocking dependency policy;
- additional manifest and compiled-toolchain variants;
- model-specific tokenizers;
- full release/deployment automation;
- concurrent role sessions; and
- extraction of a domain-neutral workflow kernel.

Prompt-context reduction becomes release-critical only if measurements from
representative 1.0 workflows approach configured limits or cause observed role
failures. Otherwise it remains post-1.0 compatible improvement work.

## Roadmap maintenance

This document defines the ordered stabilization path. `docs/todo.md` remains the
inventory of open and partially complete capabilities. Update this roadmap when
evidence changes a release gate, the supported compatibility boundary, or the
bounded evaluation matrix; do not add unrelated feature ideas here.

Record dated live evidence in focused baseline documents. Record durable,
hard-to-reverse compatibility decisions in ADRs. Remove completed implementation
detail from the active roadmap when it no longer affects the remaining route to
1.0.0.
