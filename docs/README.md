# DevLab Documentation

This directory documents the current DevLab product. Historical implementation
plans are available through Git history rather than being retained as current
documentation.

## Start Here

- [Tutorial: Your First Workflow](tutorial.md) takes a new user from installing
  DevLab to completing a small planned and reviewed Python project.
- [Vision](vision.md) explains why DevLab exists and which projects it targets.
- [Design](design.md) describes the current architecture and workflow model.
- [Operator guide](operator-guide.md) explains how to run and inspect DevLab.
- [How-to guides](how-to/README.md) provide task-oriented procedures.
- [Agent configuration](agent-configuration.md) is the provider and role
  configuration reference.

## Project Direction and Decisions

- [Roadmap](roadmap.md) records strategic outcomes and release gates. GitHub
  Issues and milestones are the source of truth for actionable work.
- [Architecture decision records](adr/) preserve decisions that are surprising,
  difficult to reverse, or based on important trade-offs.
- [Proposals](proposals/README.md) are temporary documents for substantial
  unresolved designs. Accepted decisions move into ADRs and current
  documentation; implementation work moves into issues.

## Evidence and Policy

- [Evaluations](evaluations/README.md) documents deterministic and live workflow
  evaluations. Dated results live under `evaluations/baselines/`.
- [Release policy](release-policy.md) defines versioning, compatibility, and
  release expectations.
- [Deployment feature overview](deployment-feature-overview.md) describes the
  current deployment-support promise and boundaries.

## Documentation Ownership

Each kind of information has one durable owner:

| Information | Owner |
| --- | --- |
| Agent-critical terminology | `CONTEXT.md` |
| Product motivation and scope | `docs/vision.md` |
| Current architecture and behavior | `docs/design.md` |
| Operator procedures | `docs/operator-guide.md` and `docs/how-to/` |
| Configuration contracts | Focused reference documents |
| Durable architectural decisions | `docs/adr/` |
| Strategic direction and release gates | `docs/roadmap.md` |
| Actionable work | GitHub Issues and milestones |
| Substantial unresolved designs | `docs/proposals/` |
| Historical implementation detail | Git history |

Documentation should describe implemented behavior in the present tense. Do not
keep a completed proposal or implementation plan merely as a status record.
Promote durable information to its owning document, then remove the temporary
document.
