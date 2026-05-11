# DevLab TODOs / Features to be implemented

## Prompt Context Size Monitoring

Current state: packaged prompt resources are modest in size. Approximate current fixed system prompt sizes are architect ~1.4k tokens, planner ~2.4k, developer ~1.8k, reviewer ~1.8k, and integrator ~1.5k. This is acceptable for current models, but context growth should be monitored because DevLab intentionally runs bounded, role-specific sessions.

Open feature: add prompt size reporting and guardrails so role context remains small as target repositories grow.

Risks:

- Shared `conventions.md` is injected into every role, including sections not every role needs.
- Planner context includes profile information and may grow as target repositories add profiles.
- Integrator context may grow with milestone tasks, handoffs, and findings.
- Long handoffs, large task files, or verbose role prompts can erode bounded-session benefits and increase context drift.

Possible implementation:

- Add a reusable prompt size estimator for system prompt, session prompt, and selected repository context per role.
- Surface the report through `devlab status --verbose` or a future `devlab doctor` command.
- Warn when a role's initial context exceeds configurable thresholds.
- Consider splitting shared conventions into smaller prompt resources, e.g. core, tasks, findings, reviews, and handoffs, then include only role-relevant sections.
- Consider summarizing profile listings for planner prompts instead of embedding full profile TOML by default.
- Keep role prompts procedural and minimal; prefer enforcing workflow rules in code where practical.

## Integration Findings and Corrective Planning

Current state: the integrator runs at completed milestone boundaries selected from `.devlab/milestones/` state. If integration passes, the orchestrator marks the milestone integrated. If integration reports Open Issues, the orchestrator creates a file-backed finding in `.devlab/findings/`, records the finding on the milestone, marks integration failed, and routes the workflow back to the planner.

Current state: planner handoffs include `## Addressed Findings`; the orchestrator marks listed findings as `planned`. When the milestone later integrates successfully, related planned findings are marked `resolved`.

Open features:

- Improve finding titles/bodies generated from integrator handoffs.
- Add stronger validation that planner-created tasks actually reference addressed findings.
- Add reporting for open/planned/resolved findings.
- Consider allowing reviewer/developer/architect roles to create findings, not only the integrator.

## Starting workflow on an existing project

DevLab shall support operation on an already existing project which was developed outside DevLab.

IN that case, the system spec would be more of a feature spec, and DevLab adds the features from the system spec to the existing project with the same workflow it used to develop a system from scratch.

## Sync project status periodically with design plan and system spec

Davlab shall guard the project progress so that it doesn't drift away from the design plan or from the system spec.

One possible way to implement this:
- At the start of the DevLab run or after a mileston has been reached, the architect role (or planner? or a new role?) evaluates the current system status (from the code, and possibly from git and devlab artifacts?) and verifies that it is still aligned with the project plan, the design plan and the system spec.
- If DevLab decides that the current project status drifts away from the plan or the spec, it will initiate a correction. One idea on how to do that would be to perform a git rollback to the previous milestone, describe the concern about the project drift as a finding (and / or as a hint in the session handoff?), and invoke the next seesion with the planner role. Since the project plan has also rolled back to the previous milestone, the current milestone will be planned (and ultimately implemented) again, but now the planner has the additional knowledge (from findings) of the project drift introduced by the previous try.

To support clean milestone version rollbacks, we should think about the best branching strategy for the workflow. Maybe a feature branch for each milestone, which gets merged into main after the integrator approved the milestone?

## Architect Re-invocation

Current state: the orchestrator calls the architect when the design plan is empty, then never again. Design plans evolve — after implementing milestones, interfaces may need revision or new components may emerge.

Planned feature: after a milestone integrates successfully, invoke the architect once to review whether the design plan still matches the implemented system and future project direction.

Likely implementation:

- Use `.devlab/milestones/<milestone-id>.toml` state instead of architecture-review marker files.
- Select architect when a milestone is integrated but not architecture-reviewed.
- Build an architect prompt focused on milestone-boundary design review, not greenfield design.
- After architecture review, route to planner if the design/project plan may need adjustment.

## Milestone State

Current state: milestone completion is computed from task metadata, while integration workflow state is tracked explicitly in `.devlab/milestones/<milestone-id>.toml`. `src/devlab/milestones.py` defines the file-backed milestone tracker, and `devlab init` creates `.devlab/milestones/`.

Implemented phases 1-2:

- `Milestone` and `MilestoneStatus` model.
- `FileMilestoneTracker` abstraction.
- Creation of missing milestone files from task metadata, with project-plan headings used for titles when available.
- Preservation of existing milestone workflow state when adding newly discovered task IDs.
- State mutation helpers for marking tasks complete, integrated, integration failed, and architecture reviewed.
- Integration selection uses milestone state instead of `.devlab/history/integrated_<milestone>.md` marker files.
- Successful integration records `integrated = true`, `status = "integrated"`, and the archived integration handoff on the milestone.
- Failed integration records `status = "integration_failed"`, keeps `integrated = false`, and stores the created finding ID on the milestone.

Milestone file shape:

```toml
version = 1
id = "M1"
title = "Foundation"
status = "planned"
integration_required = true
integrated = false
architecture_reviewed = false
task_ids = ["T0001", "T0002"]
integration_handoff = ""
architecture_review_handoff = ""
findings = []
```

Remaining phase 3: architecture review at milestone boundaries.

- Select architect when a milestone is integrated and `architecture_reviewed = false`.
- Build a milestone-boundary architect prompt with the integrated milestone, relevant tasks, integration handoff, design plan, project plan, and system/deployment specs.
- After architect handoff, call `mark_architecture_reviewed(milestone_id, archived_handoff)`.
- If architect handoff reports open issues, create a finding and route to planner.

Remaining phase 4: status and doctor support.

- Show milestone state in `devlab status --verbose`, including task counts derived from task files and workflow flags from milestone files.
- Add `devlab doctor` checks for milestone/task consistency:
  - task references unknown or missing milestone file,
  - milestone references unknown task,
  - duplicate or malformed milestone IDs,
  - integrated milestone without integration handoff,
  - architecture-reviewed milestone without architecture handoff,
  - finding IDs listed on milestones but missing from `.devlab/findings/`.

Future extensions enabled by explicit milestone state:

- Design/spec sync reviews after milestone integration.
- Milestone branch/rollback metadata such as base ref, integration ref, rollback ref, and branch name.
- Richer reporting for integration failures and corrective planning.


## Deployment Specification and Verification

Current state: deployment requirements can be described informally in target specs, but DevLab has no dedicated deployment spec structure or deployment verification model.

Concrete implementation goal: support deployment requirements under `.devlab/specs/deployment/` and let the normal workflow plan, implement, review, and integrate deployment artifacts.

Required verification layers:

1. **Static/artifact validation**
   - Build and inspect deployment artifacts without touching external infrastructure.
   - Examples: `docker build`, image metadata inspection, RPM build, RPM content inspection, static systemd unit validation.
2. **Local ephemeral deployment**
   - Run deployment artifacts locally in disposable resources and smoke-test them.
   - Examples: `docker run`, Docker Compose smoke tests, local disposable databases/services, health checks, teardown through the environment lifecycle.
3. **Disposable test infrastructure**
   - Deploy to explicitly configured, isolated, non-production infrastructure and destroy it after verification.
   - Examples: temporary VM, disposable Kubernetes namespace, test registry, RPM install test in a disposable host/container.

Optional later layer:

4. **Shared staging / production-like deployment**
   - Possible but not a default implementation goal.
   - Requires explicit policy, approval, credentials handling, rollback/cleanup rules, and safeguards against state leakage.

Specification direction:

```text
.devlab/specs/deployment/
  targets.md
  container.md
  rpm.md
  runtime.md
  validation.md
  test-infrastructure.md
```

Example: .devlab/specs/deployment/targets.md

```md
# Deployment Targets

The project must support the following deployment targets:

## Container image

- Build a production container image.
- Image must run without development dependencies.
- Image must expose port 8080.
- Image must define a health check.
- Image must run as a non-root user.

## RPM package

- Build an RPM for RHEL-compatible systems.
- RPM must install the application under `/opt/example-app`.
- RPM must install a systemd service named `example-app.service`.
- RPM must not require internet access during installation.
```

Example: .devlab/specs/deployment/container.md

```md
# Container Deployment

## Requirements

- Provide a `Dockerfile`.
- Provide `.dockerignore`.
- Use a minimal runtime image.
- Do not run as root.
- Application listens on port 8080.
- Runtime configuration is provided through environment variables.
- Container must support graceful shutdown.

## Required validation

- `docker build -t example-app:test .`
- `docker run --rm example-app:test --help`
- If the app exposes HTTP:
  - start the container,
  - call `/health`,
  - verify HTTP 200.
```

Example: .devlab/specs/deployment/rpm.md

```md
# RPM Deployment

## Requirements

- Provide RPM packaging for RHEL-compatible systems.
- Install application files under `/opt/example-app`.
- Install executable wrapper under `/usr/bin/example-app`.
- Install systemd unit `example-app.service`.
- Create dedicated system user `example-app`.
- Configuration lives under `/etc/example-app/`.
- Logs go to journald by default.

## Required validation

- RPM can be built in a clean build environment.
- RPM metadata includes name, version, license, summary, and dependencies.
- Package contents can be inspected without installing as root.
- systemd unit passes static validation where possible.
```

Example: .devlab/specs/deployment/runtime.md

```md
# Runtime Configuration

## Environment variables

- `EXAMPLE_APP_HOST`
- `EXAMPLE_APP_PORT`
- `EXAMPLE_APP_LOG_LEVEL`

## Secrets

Secrets must not be baked into images or packages.

Allowed secret sources:

- environment variables,
- mounted files,
- systemd environment files,
- orchestrator-specific secret managers added later.
```

How DevLab would use this

The architect reads system + deployment specs and updates the design plan.

The planner creates tasks like:

```text
  T0010: Add production Dockerfile
  T0011: Add Docker Compose smoke deployment
  T0012: Add RPM packaging skeleton
  T0013: Add systemd service unit
  T0014: Add deployment validation documentation/tests
```

The developer implements one task at a time.

The reviewer validates each task.

The integrator validates that the milestone deployability story works as a whole.


Design constraints:

- DevLab should make projects deployable and verify deployment behavior; it should not deploy to production by default.
- Test infrastructure use must be explicit, allowlisted, isolated, and aggressively cleaned up.
- Deployment logs should eventually be written under `.devlab/logs/deployment/` and committed by default subject to redaction/size controls.
- Deployment implementation should remain task-based: architect/planner derive deployment tasks, developer implements them, reviewer validates them, integrator verifies deployment coherence at milestone boundaries.

## DevLab Workflow Evaluations

Current state: normal tests use deterministic providers such as `MockProvider` and do not call live agents.

Open feature: add opt-in workflow evaluations that run DevLab on small target specifications and check observable behavior, not exact generated files.

- Keep live-agent evaluations separate from default tests because they consume tokens and are nondeterministic.
- Use small specs with objective acceptance checks, e.g. CLI calculator, tiny API, or frontend/backend smoke app.
- Grade generated systems with black-box checks such as commands, HTTP responses, package builds, and test suites.
- Record diagnostics such as sessions used, findings created, review rejections, runtime, and final artifacts.
- Add a deterministic scripted fake-agent provider/evaluation mode first or alongside live evals; it writes canned role outputs/files for known specs and tests the full DevLab loop without tokens.

## Automatic Version Control

DevLab should eventually be able to commit repository state after completed sessions or workflow gates.

Open questions:

- Commit after every valid session, after every task closure, or after milestone integration?
- Should failed integration findings be committed automatically?
- How should commit messages be generated and reviewed?
- How should dirty working tree state before a session be handled?

## Later / Non-goals for Now

- Automatic execution of task validation commands by the orchestrator, instead of just by the worker agent.
- Sandboxing or approval policy for executable environment lifecycle changes.
- Automatic generation of follow-up tasks directly by the orchestrator.
- Multi-agent concurrent sessions.
- External task tracker backends such as Jira or GitHub Issues.
- Full release/deployment automation.
