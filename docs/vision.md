# Project Vision

## Motivation

Substantial projects cannot be created reliably in a single agent session. As
scope and complexity grow, the relevant intent, decisions, intermediate work,
feedback, and project history exceed what one bounded interaction can manage
consistently. Long sessions also accumulate hidden assumptions and context
drift, make independent review difficult, and leave progress hard to recover
when a session fails.

The practical boundary is not merely whether all input fits within a model's
context window. Information may fit while still being too extensive or too
weakly structured for an agent to reason about it reliably as one unit. Large
projects also require iteration, specialization, review, and decisions that
must remain available after the session that produced them ends.

DevLab addresses this problem by turning durable intent into reviewed software
artifacts through bounded, role-based sessions connected by explicit workflow
state. Specifications, plans, tasks, decisions, findings, and handoffs live in
the target workspace so that each session can start from authoritative project
state and leave an inspectable result for the next session.

## Meaningful target projects

This approach is most useful for projects that:

- produce durable artifacts;
- are large or complex enough that one-shot generation is unreliable;
- can be decomposed into bounded units of creation or revision;
- require consistency across those units;
- benefit from distinct creation and review perspectives; and
- contain decisions, feedback, or research that must survive individual
  sessions.

Small, disposable, or intrinsically conversational outputs generally do not
justify the workflow overhead.

## Current scope

DevLab applies this model specifically to software development. Its domain
language and workflow rules intentionally refer to software concepts such as
system specifications, design plans, implementation tasks, developers,
reviewers, integration, validation commands, and architecture review. These
are enforced workflow semantics, not merely configurable role labels.

The domain-specific focus is valuable: correctness-critical transitions and
artifact contracts can be implemented and tested in code instead of being left
to prompts. DevLab should not weaken those guarantees in pursuit of premature
generality.

## Possible future evolution

The same motivation may support other artifact-producing domains. A book
authoring workflow, for example, could turn a durable book brief into an
outline, research records, chapter drafts, editorial findings, revisions, and
publication artifacts through bounded author, researcher, and editor sessions.
Its lifecycle would differ materially from software development even though it
would need similar orchestration infrastructure.

A future architecture could therefore separate:

- a domain-neutral workflow kernel for bounded session invocation, durable
  state, handoff validation, clarification and resume handling, provenance,
  diagnostics, and safe transition execution; and
- domain-specific workflow packages that own artifact schemas, vocabulary,
  role-selection policy, state transitions, review rules, validation behavior,
  and prompts.

DevLab would remain the opinionated software-development workflow package. A
book-authoring system or another domain workflow could use the same kernel
without pretending that chapters are software tasks or that editorial review
is software integration.

This separation is a direction to investigate, not a current architectural
commitment. A concrete second workflow should demonstrate which abstractions
are genuinely shared before common infrastructure is extracted. Until then,
DevLab's software-domain boundaries should remain explicit.
