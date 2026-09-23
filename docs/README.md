# DevLab Documentation

Start with the guide for what you want to do. The
[project README](../README.md) introduces DevLab and its current maturity.

## Learn and run DevLab

| Goal | Guide |
| --- | --- |
| Complete a first workflow | [Tutorial: Your First Workflow](tutorial.md) |
| Bring an existing repository into DevLab | [Adopt an existing project](how-to/adopt-existing-project.md) |
| Understand routine operation and workspace files | [Operator guide](operator-guide.md) |
| Fix a bug or change requirements | [How-to guides](how-to/README.md) |
| Continue after a stop or failed session | [Interruption and recovery](how-to/resume-interrupted-workflow.md) |
| Present a repeatable demonstration | [First-workflow demo](../demos/first-workflow/) |

The tutorial supplies a complete example. How-to guides address individual tasks;
the operator guide explains the lifecycle and serves as the workspace reference.

## Configure a target workspace

- [Agent configuration](agent-configuration.md): provider invocation, role
  overrides, timeouts, prompt size, and smoke tests.
- [Profiles and validation](operator-guide.md#profiles): tooling, session
  environments, command selection, and validation outcomes.
- [Executable configuration authorization](operator-guide.md#executable-configuration-authorization):
  workstation trust, CI digests, and configuration changes.
- [Runtime prerequisites and managed test services](runtime-prerequisites.md):
  readiness checks, bounded preparation, resource ownership, and cleanup.
- [Deployment support](deployment-feature-overview.md): deployment requirements,
  verification, and the operator/CI boundary.

## Understand and contribute to DevLab

- [Why DevLab?](why-devlab.md): architectural principles, differentiators, and their consequences.
- [Vision](vision.md): motivation, suitable projects, and potential evolution.
- [Design overview](design.md): current workflow mechanics and architecture.
- [Terminology](../CONTEXT.md) and [development constraints](../AGENTS.md):
  shared language, module ownership, and invariants for maintainers.
- [Contributing](../CONTRIBUTING.md): development setup and validation.
- [Roadmap](roadmap.md): strategic direction and release gates. Concrete work is
  tracked in linked GitHub Issues and the roadmap project.
- [Architecture decisions](adr/): durable decisions and their tradeoffs.
- [Release policy](release-policy.md): versioning, compatibility, and publication.
- [Workflow evaluations](evaluations/README.md): how to run and interpret
  evaluations, with [dated baselines](evaluations/baselines/README.md).
- [Demonstrations and experiments](../demos/README.md): repository-only fixtures,
  demos, and independent graders.

## Maintaining the documentation

Each document has a specific job. Keep commands and field semantics in the
operator/configuration references; link to them from the design overview and
procedures. Keep agent-critical terms in `CONTEXT.md`, architectural constraints
in `AGENTS.md` and ADRs, and current behavior in the relevant guide.

Describe implemented behavior in the present tense. Proposed changes belong in
issues or temporary [design proposals](proposals/README.md), with accepted
tradeoffs promoted to ADRs. Remove completed proposals after their contracts
have moved into current documentation; Git history retains implementation plans.

Dated baselines record the versions, environments, and outcomes actually tested.
They are historical evidence, not instructions for the latest release or a
promise that every current version has the same coverage. Keep them distinct
from current evaluation instructions.

Use repository-relative links in the guides. The root README also renders on
PyPI and uses absolute URLs. Check incoming links and heading anchors when
moving or renaming content, and verify command/configuration examples against
the owning implementation before publishing changes.
