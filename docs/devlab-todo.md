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

## Agent Configuration Closure Plan

Current state: `.devlab/config/agents.toml` configures worker agent provider, command, model, effort, timeout, prompt arguments, and stdin prompt delivery. `devlab init` creates a documented starter file, CLI overrides are supported, resolved agent configuration is logged under `.devlab/logs/agents/`, and the reference lives in `docs/agent-configuration.md`.

Remaining work to close the feature:

### `devlab doctor`

Add a workspace validation command that reports configuration/layout problems without running agent sessions.

Agent-configuration checks:

- `.devlab/config/agents.toml` parses as TOML.
- `[defaults]`, `[roles]`, and `[providers]` are tables when present.
- Every configured role name is known: `architect`, `planner`, `developer`, `reviewer`, or `integrator`.
- Every resolved role references an existing provider.
- Every provider has a string `command`.
- `args` and `prompt_args` are lists of strings when present.
- `stdin_template` is a string when present.
- `timeout_seconds` is an integer when present.
- Provider templates only reference supported placeholders: `{role_name}`, `{provider}`, `{model}`, `{effort}`, `{system_prompt}`, and `{session_prompt}`.
- Each role can be resolved into an invokable provider configuration.

Suggested output:

```text
DevLab doctor: OK
```

or:

```text
DevLab doctor: 2 problem(s)
- .devlab/config/agents.toml: providers.review.command must be a string
- .devlab/config/agents.toml: roles.reviewer.provider references missing provider "review"
```

Implementation sketch:

- Add `src/devlab/doctor.py` with a small `DoctorProblem` dataclass and `check_workspace(root) -> list[DoctorProblem]`.
- Reuse `agent_config.py` parsing/resolution logic where practical, but make doctor collect multiple problems instead of failing fast on the first exception.
- Add `devlab doctor [--root PATH]` to `cli.py`.
- Return exit code `0` when no problems exist and `1` when problems are found.

### `devlab status --verbose`

Extend status reporting with resolved agent configuration, without printing prompts.

Verbose output should include:

- next selected role,
- selected provider for each role,
- model,
- effort,
- timeout,
- command shape,
- whether prompts are sent through stdin,
- path to `.devlab/config/agents.toml` or note that built-in fallback defaults are used.

Example:

```text
Next role: developer

Agent configuration:
- architect: default model="" effort="" timeout=3600 command=["claude", "-p"] stdin=false
- planner: default model="" effort="" timeout=3600 command=["claude", "-p"] stdin=false
- developer: codex model="gpt-5-codex" effort="medium" timeout=3600 command=["codex", "exec", "-", "--model", "gpt-5-codex"] stdin=true
- reviewer: claude model="claude-sonnet-4.5" effort="high" timeout=3600 command=["claude", "-p", "--model", "claude-sonnet-4.5"] stdin=false
- integrator: default model="" effort="" timeout=3600 command=["claude", "-p"] stdin=false
```

Implementation sketch:

- Add `status.py` if status output grows beyond simple CLI formatting.
- Reuse `load_agent_configuration()` and `format_resolved_agent_config()` or add a compact formatter.
- Keep prompt contents out of status output.

After these two items are implemented, consider target-specific worker agent configuration complete. Future provider examples can be added opportunistically when real usage requires them.

## Integration Findings and Corrective Planning

Current state: the integrator runs at completed milestone boundaries. If integration passes, the orchestrator writes an integration marker. If integration reports Open Issues, the orchestrator creates a file-backed finding in `.devlab/findings/` and routes the workflow back to the planner.

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

- Add architecture-review markers per milestone, e.g. in `.devlab/history/`.
- Select architect when a milestone is integrated but not architecture-reviewed.
- Build an architect prompt focused on milestone-boundary design review, not greenfield design.
- After architecture review, route to planner if the design/project plan may need adjustment.

## Milestone State

Current state: milestone completion is computed from task metadata and integration completion is tracked by marker files.

Open feature: introduce explicit milestone metadata/state if marker files and project-plan text become insufficient.

Possible state to track:

- milestone id/title
- integration required or skipped
- integrated status
- architecture-reviewed status
- current/planned/complete status

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
