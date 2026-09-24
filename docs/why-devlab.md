# Why DevLab?

If you are evaluating DevLab or considering contributing to it, this document explains the ideas behind its architecture and the trade-offs they imply. It focuses on **why DevLab is designed the way it is**; the linked design, configuration, and operator documentation describes how those choices are implemented and used.

DevLab is built around a particular view of agentic software development: AI agents are powerful but nondeterministic workers, while the development process itself should remain durable, inspectable, recoverable, and under the project's control.

Many tools can ask an AI agent to plan or implement from a specification. DevLab focuses on what happens when the work becomes too large, long-lived, or important for one agent session: how intent survives between sessions, how different responsibilities are separated, how work is reviewed, how uncertainty is surfaced, how interrupted work resumes, and how changing an AI provider affects the development process.

The individual mechanisms below are not necessarily unique to DevLab. The distinction is the architecture they form together: **provider-independent agents operating inside a repository-backed workflow whose control plane is implemented and validated by deterministic software.**

## The DevLab model

DevLab's architecture follows from a simple chain of reasoning.

**What is DevLab?**
Auditable workflow orchestration for substantial agentic software development.

**What problem does it address?**
Substantial software projects span decisions, implementation work, review, research, failures, and changes that should not depend on the lifetime or context of any single AI agent session.

**What is the fundamental design principle?**
**Agent sessions are temporary; project state is durable.**

**What follows from that principle?**

* **The workflow belongs to the project.** AI providers participate in the workflow; they do not own it.
* **Project memory must survive agent sessions.** Specifications, decisions, plans, evidence, and progress therefore become durable repository state.
* **Agent work should be bounded.** Explicit roles and handoffs allow separate sessions to cooperate without sharing one ever-growing conversation.
* **Control should not depend on model judgment.** DevLab uses deterministic software for workflow transitions, validation, recovery, and trust decisions while using AI where judgment and reasoning are valuable.
* **Verification should be separable from creation.** Implementation, validation, review, and integration form distinct responsibilities and can use different sessions, models, or providers. This creates opportunities for another perspective; it does not guarantee independent judgment.
* **Decision authority and provenance should remain explicit.** Agents can surface unresolved decisions as durable clarifications. By default, DevLab stops for an operator answer; unattended mode can explicitly delegate resolution to a separate agent session while recording who supplied the answer.
* **Interruption must be recoverable.** Because authoritative workflow state survives outside agent sessions, DevLab can derive what should happen next after a provider failure, process restart, or deliberate pause.

The mechanisms described below—provider independence, repository-backed state, bounded roles, structured handoffs, validation, review, configuration trust, and recovery—are consequences of this model rather than independent features.

For the implementation of these concepts, see the [design overview](design.md). Operational behavior is documented in the [operator guide](operator-guide.md), and provider and role configuration in [agent configuration](agent-configuration.md).

## The core ideas

### DevLab owns the workflow, not the AI provider

DevLab runs as a standalone orchestrator. Coding-agent CLIs are external workers invoked by DevLab; they are not the environment in which the DevLab workflow itself exists.

Conceptually, the relationship is:

```text
Project
  └── DevLab workflow
       ├── Architect   → provider/model A
       ├── Planner     → provider/model B
       ├── Developer   → provider/model C
       ├── Reviewer    → provider/model D
       ├── Integrator  → provider/model E
       └── Researcher  → provider/model F
```

rather than:

```text
AI provider/client
  └── development workflow
       └── project
```

This inversion matters. The provider is a replaceable participant in the development process rather than the owner of that process.

A project can use different providers or models for different roles. A model selected for architectural reasoning need not be the model used for implementation, and the reviewer need not be the model that produced the code. Providers can be changed without replacing the project's workflow model or abandoning its durable state.

The architecture also creates a useful responsibility boundary: DevLab is responsible for orchestration, while providers remain responsible for model execution and their own permission or sandboxing mechanisms.

**The workflow belongs to the project; AI providers participate in it.**

See [Agent configuration](agent-configuration.md) for role-specific provider configuration and the security implications of provider commands.

### Agent sessions are temporary; project state is durable

Agent conversations are useful execution contexts, but they are a poor place to keep the authoritative state of a substantial software project.

Sessions end. Context windows are finite. Providers change. Processes crash. Long conversations accumulate assumptions and irrelevant history. Even information that technically fits within a model's context window can become too extensive or weakly structured for reliable reasoning.

DevLab therefore treats agent sessions as bounded units of work and persists the authoritative information that must survive them in the target repository.

Specifications, plans, tasks, decisions, findings, research, handoffs, and workflow progress become durable project artifacts where appropriate. Accepted work is anchored in Git history. Local runtime artifacts that do not belong in project history remain separate from committed workflow state.

A later session does not depend on the previous agent's conversation for authoritative workflow state. It starts from the durable state left by earlier work.

This provides several properties:

* work can resume after interruption or process failure;
* a different model or provider can continue the project;
* humans can inspect the authoritative state used by the workflow;
* decisions and findings can survive the session that produced them;
* changes to project intent and workflow artifacts can be diffed and versioned; and
* long-running development does not depend on preserving one ever-growing conversation.

**Conversations are execution contexts; files and Git are project memory.**

See the [design overview](design.md) for the durable-state model and the [operator guide](operator-guide.md) for inspection, continuation, and recovery behavior.

### Use AI for judgment; deterministic software for control

LLMs are valuable precisely because they can perform work that is difficult to encode as deterministic rules: understanding requirements, designing systems, writing code, reviewing implementations, and synthesizing research.

That does not mean they should also be responsible for deciding whether the workflow itself has been followed correctly.

DevLab deliberately separates these concerns.

Agents perform reasoning and produce proposed results. DevLab owns deterministic responsibilities such as workflow transitions, handoff validation, configuration trust, validation execution, recovery behavior, and selection of the next valid action.

An implementing agent therefore cannot make an implementation authoritative merely by declaring that it is finished. Its output passes through workflow-controlled validation and review.

This creates a deterministic control plane around nondeterministic workers:

```text
                 DevLab
          deterministic control
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
   Architect    Developer    Reviewer
       │           │           │
       └──── AI reasoning ─────┘
                   │
                   ▼
          validated artifacts
                   │
                   ▼
             durable state
```

The goal is not to make AI deterministic. It is to make the **process surrounding AI behavior predictable, inspectable, and testable**.

See the [design overview](design.md) for the workflow state machine and orchestration boundaries.

## Why these choices matter

### Bounded roles

Role separation is more than assigning different prompts to agents.

A long-lived general-purpose agent can accumulate several kinds of coupling: it knows why it made an architectural choice, remembers compromises made while implementing it, and may subsequently review its own work in light of those same assumptions.

DevLab instead creates explicit boundaries between responsibilities.

An architect reasons about system structure. A planner translates design into executable work. A developer implements a bounded task. A reviewer evaluates that work. An integrator evaluates completed milestones, while architecture review can identify larger remaining gaps. Research can temporarily leave the main workflow to gather evidence and then return that evidence to the route that requested it.

Each boundary requires relevant information to become explicit enough to survive a handoff.

This has two benefits.

First, it controls context. A developer working on one task should not require every token generated during every previous project session.

Second, it creates opportunities for another perspective. A reviewer can approach an implementation from the recorded requirements, changes, and evidence rather than simply continuing the implementer's conversation. Different roles can also be assigned to different providers or models.

This separation improves the structure of review; it does not guarantee independent judgment. Different agents or models can still share assumptions and blind spots.

See [Agent configuration](agent-configuration.md) for the supported roles, role-specific overrides, and the limits of model diversity as a source of review independence.

### Durable specifications

A specification-driven workflow is valuable only if the specification remains authoritative after implementation begins.

Without durable intent, successive agent sessions can gradually substitute remembered interpretations for actual requirements. Small assumptions can become implicit decisions; those decisions influence later work; and eventually the implementation itself risks becoming the de facto specification.

DevLab keeps specifications and derived planning artifacts in the repository so later sessions can return to them.

This does not mean specifications are immutable. Requirements change. Designs evolve. Findings expose incorrect assumptions. DevLab's goal is instead to make those changes explicit and durable so that the project can distinguish:

* what was requested;
* what was planned;
* what was implemented;
* what review discovered;
* what evidence supports a decision; and
* what changed later.

That history becomes particularly important when a project spans many separate agent sessions.

See the [design overview](design.md) for how specifications and workflow artifacts participate in orchestration.

### Separate review

Agentic development can easily collapse implementation and verification into one reasoning process:

```text
Agent writes code
      ↓
Agent checks its own reasoning
      ↓
Agent declares success
```

DevLab deliberately introduces additional boundaries:

```text
Developer
    ↓
project validation
    ↓
Reviewer
    ├── request changes ──→ Developer
    │
    └── accept ───────────→ task complete

all milestone tasks complete
    ↓
Integrator
```

The objective is not to assume that one role, session, provider, or model is inherently more trustworthy than another. It is to avoid making one generation process the sole source of both the artifact and the evidence that the artifact is correct.

Because roles can use different sessions, providers, or models, users can introduce another perspective where appropriate. This remains a form of structured separation, not a guarantee of independent judgment: different models can share blind spots, and all agent-produced work still requires appropriate validation and human oversight for the project's risk level.

See [Agent configuration](agent-configuration.md) for role overrides and the limitations of reviewer-model diversity.

### Explicit decision authority

Autonomous execution is useful only while the workflow has sufficient authority and information to proceed.

Some uncertainties are technical and can be investigated. Others concern product intent, architecture, risk, or preferences that require an explicit resolution before work should continue.

DevLab provides a durable clarification mechanism for uncertainties that agents surface. A submitted clarification becomes workflow state rather than remaining only inside an agent conversation.

In normal interactive operation, DevLab stops and waits for an operator answer. For clarification requests encountered during an explicitly unattended workflow loop, resolution can instead be delegated to a separate bounded agent session. DevLab validates that response and records agent provenance so that the source of the answer remains visible. A clarification already pending when `continue` starts is displayed for an operator answer, even in unattended mode.

This preserves an important boundary:

**The source and authority of a surfaced decision should be explicit and durable.**

DevLab can enforce this boundary for clarifications that agents submit. It cannot guarantee that an agent will recognize every ambiguity or refrain from making an unstated assumption. Clarification handling therefore complements rather than replaces good specifications, review, validation, and appropriate human oversight.

See [Clarifications](operator-guide.md#clarifications) and
[Unattended operation](operator-guide.md#before-running-unattended) in the operator guide.

### Trusted executable configuration

An agentic development system routinely executes things: coding agents, validation commands, environment setup, tests, and project tooling.

If an agent can modify the configuration controlling those commands and the orchestrator automatically accepts the modification, generated code can indirectly change what the orchestrator will execute.

DevLab therefore treats executable configuration as a trust boundary. Relevant configuration is fingerprinted, and changes require authorization before they are adopted.

This does not make arbitrary command execution safe, nor does it replace sandboxing. It addresses a different problem: **whether the orchestrator should silently trust a changed instruction about what to execute.**

Provider permissions, containers, operating-system sandboxing, credentials, and execution isolation remain separate concerns.

See [Executable configuration authorization](operator-guide.md#executable-configuration-authorization)
for the trust workflow and [Agent configuration](agent-configuration.md)
for provider-command security considerations.

### Recoverable workflows

Failure and interruption are normal in a multi-session agentic workflow.

A provider can fail. A process can stop. A machine can reboot. A human may deliberately interrupt work for review. An agent may request clarification. Validation may fail.

A system designed around one persistent conversation tends to make such events expensive because important state can exist only inside the interrupted session.

DevLab instead persists the authoritative state needed to recover the workflow.

Commands such as `status`, `doctor`, `diagnostics`, and `history` expose that state, while continuation derives the next appropriate action from it.

Recovery is therefore not merely an operational convenience. It follows directly from the principle that **the project, rather than the agent session, owns the workflow state**.

See [Recovery](operator-guide.md#recovery) for recovery and continuation behavior.

## Architectural characteristics and their consequences

| Characteristic                                                 | DevLab approach                                                                                                                                                                                 | Why it matters                                                                                                                                                                                 |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Provider-independent orchestration**                         | DevLab runs outside the coding-agent clients it invokes, and roles can use different configured providers or models.                                                                            | Reduces provider lock-in. Providers can change while the project's workflow and durable state remain intact, and models can be selected according to the needs of different roles.             |
| **Durable, repository-backed state**                           | Specifications, plans, tasks, findings, research, handoffs, and workflow progress are persisted outside agent conversations.                                                                    | Authoritative workflow state can survive context loss, provider changes, restarts, and interrupted sessions while remaining inspectable and versionable.                                       |
| **Git-backed execution boundaries**                            | Accepted work is committed and sessions operate against controlled repository state.                                                                                                            | Provides durable checkpoints, understandable history, rollback points, and boundaries between successive units of agent work.                                                                  |
| **Bounded role sessions**                                      | Architecture, planning, development, review, integration, and research have distinct responsibilities and handoffs.                                                                             | Limits context growth and role confusion and avoids making one long-running agent responsible for every stage of development.                                                                  |
| **Separate review and integration**                            | Creation, review, and integration are distinct workflow responsibilities and can use different sessions, models, or providers.                                                                  | Work does not become accepted solely because its author considers it complete, and another session can bring a different perspective. |
| **Specification as durable authority**                         | Requirements and design intent are repository artifacts used across sessions.                                                                                                                   | Reduces dependence on remembered conversational context and lets later sessions return to durable sources of intended behavior.                                                                |
| **Deterministic orchestration around nondeterministic agents** | DevLab owns lifecycle transitions, validation, recovery, and state advancement.                                                                                                                 | Control-flow behavior can be implemented, tested, and inspected rather than delegated entirely to model judgment.                                                                              |
| **Structured, validated handoffs**                             | Agent results cross explicit role boundaries and are validated before becoming authoritative workflow state.                                                                                    | Creates a boundary between model output and accepted project state and prevents malformed or incomplete submitted output from silently advancing the workflow.                                 |
| **Explicit decision authority and provenance**                 | Agents can submit durable clarifications. Interactive operation waits for the operator; unattended operation can delegate resolution to a bounded resolver and records who supplied the answer. | Makes the handling and provenance of surfaced decisions explicit rather than leaving clarification state only inside an agent conversation.                                                    |
| **Executable-configuration trust boundary**                    | Executable project configuration is fingerprinted and changes require authorization before DevLab adopts them.                                                                                  | Helps prevent changed project configuration from silently altering what the orchestrator itself will execute.                                                                                  |
| **Orchestrator-owned validation**                              | Project-defined validation is executed and recorded by DevLab rather than relying solely on an agent's report.                                                                                  | "Done" can be supported by validation executed by the orchestrator instead of only an agent assertion.                                                                                                 |
| **Durable research with provenance**                           | Research results and their evidence survive the research session and return to the requesting workflow route.                                                                                   | Research becomes reviewable project evidence rather than ephemeral information embedded only in a conversation.                                                                                |
| **Inspectable and recoverable operation**                      | Read-only status, health, diagnostics, and history expose workflow state, while continuation derives the next action from persisted state.                                                      | Operators can inspect what the system believes, and interrupted work can resume without reconstructing the workflow from an AI conversation.                                                   |
| **Language-neutral target projects**                           | DevLab's workflow is independent of the implementation language of the software being developed.                                                                                                | The orchestration model applies to heterogeneous software projects rather than being coupled to one application stack.                                                                         |
| **Explicit execution-security boundary**                       | DevLab does not claim to sandbox provider or project commands; execution isolation remains the responsibility of the configured provider and environment.                                       | Avoids conflating workflow integrity with operating-system isolation and avoids providing a false security guarantee.                                                                          |

## What DevLab deliberately does not promise

These architectural choices have costs.

DevLab introduces more structure and setup than lightweight prompt collections or workflows embedded directly in a coding agent. Durable artifacts must be maintained. Roles and transitions impose process boundaries. Provider invocation and executable project configuration require explicit setup and trust.

For small changes, disposable prototypes, or work that comfortably fits into one interactive coding session, that overhead may provide little benefit.

DevLab is intended for the point where the opposite trade-off becomes attractive: projects where work spans many sessions, decisions must survive them, separate review matters, and developers want the development process to remain understandable even when the AI workers performing parts of it change.

DevLab also does not make coding agents intrinsically safe, correct, or independent. It cannot guarantee that agents identify every ambiguity, that different models do not share blind spots, or that review catches every defect. It does not replace provider sandboxing, operating-system isolation, human review, tests, or appropriate control of credentials.
