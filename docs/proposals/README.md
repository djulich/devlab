# Design Proposals

Proposals are temporary review artifacts for substantial changes whose design is
not yet settled. GitHub Issues are sufficient for bugs, focused enhancements,
evaluation runs, and other work that does not need a repository-level design.

There are currently no active proposals.

## Lifecycle

1. Open a GitHub Issue describing the problem, outcome, and scope.
2. Add a proposal here only when the change has cross-cutting contracts or
   meaningful alternatives that need review before implementation.
3. Review the proposal through a pull request linked to the issue.
4. When accepted, record hard-to-reverse decisions in an ADR and update the
   relevant current design or reference documentation.
5. Track implementation in GitHub Issues or pull requests.
6. Remove the proposal after implementation. Git history preserves it.

Use these statuses in proposal front matter: `draft`, `accepted`, `rejected`, or
`superseded`. An accepted proposal must not remain the only source of a current
contract.

## Template

```markdown
---
status: draft
created: YYYY-MM-DD
issue: https://github.com/djulich/devlab/issues/NNN
---

# Proposal: Short title

## Problem

What concrete limitation or failure motivates this change?

## Outcome

What observable result should the change produce?

## Constraints

Which existing contracts and ownership boundaries must remain true?

## Options

What credible alternatives were considered?

## Decision

What approach is proposed, and why?

## Compatibility and migration

Which public or durable formats change, and how do existing users move forward?

## Validation

What tests or evaluation evidence will demonstrate the outcome?
```
