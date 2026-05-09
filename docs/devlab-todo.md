# DevLab TODOs / Features to be implemented

## Tooling and Environment Profiles

Current state: task files can specify concrete `validation` commands. If omitted, worker agents use defaults from `.devlab/config/tooling.md`; if `validation = []`, no validation commands are required. Shared environment lifecycle commands live in `.devlab/config/environment.toml` and are enforced by the orchestrator for developer/reviewer/integrator sessions.

Open feature: add reusable tooling and environment profiles so tasks and target projects can reference concise profile names instead of repeating command lists and lifecycle commands.

- Define DevLab-provided profiles for common stacks, e.g. Python CLI, Python FastAPI backend, Python Django backend, React frontend, Postgres service, Redis service, Docker Compose app.
- Let target workspaces define custom profiles at a discoverable location.
- Let tasks reference validation profiles and optionally add task-specific validation commands.
- Let environment configuration compose setup/teardown/service profiles for the target project's components.
- Keep profile use declarative; do not make the orchestrator execute arbitrary task validation commands yet.

## Target-specific DevLab Workflow Directory

Current state: target-project workflow artifacts have been migrated under a committed, project-local `.devlab/` directory. DevLab-owned role and convention files remain under `specs/development/` in this repository while the layout stabilizes.

Open feature: stabilize the `.devlab/` layout and add initialization/migration tooling.

Current target-project layout:

```text
.devlab/
  config/
    tooling.toml
    environment.toml
    profiles/
      python-cli.toml
      fastapi-postgres.toml

  specs/
    system/
    deployment/

  plans/
    design-plan.md
    project-plan.md

  tasks/
    T0001_...

  findings/
    F0001_...

  history/
    20260507T235700_developer_handoff.md
    integrated_M1.md

  logs/
    environment/
      20260507T235700_developer_pre_session_1.log
```

Rationale:

- Different target projects need different specs, tooling, validation, services, and environment lifecycles.
- `.devlab/` should be target-project-local and committed by default, including workflow history and logs, to preserve auditability and reproducibility.
- `specs/development/` should remain DevLab-owned role/prompt source, analogous to DevLab's `src/`, not target-project workflow state.
- Generated runtime logs/history are still workflow artifacts; keeping them under `.devlab/` makes cleanup, review, and migration easier.

Initialization command:

- Add a `devlab init` command, similar to `git init`, that creates the target-project-local `.devlab/` structure.
- Make initialization idempotent and non-destructive by default; never overwrite existing files unless an explicit `--force` option is used.
- Seed minimal starter files such as `.devlab/config/tooling.md`, `.devlab/config/environment.toml`, `.devlab/specs/system/README.md`, and `.devlab/specs/deployment/README.md`.
- Create empty workflow directories such as `.devlab/plans/`, `.devlab/tasks/`, `.devlab/findings/`, `.devlab/history/`, `.devlab/logs/environment/`, and `.devlab/logs/deployment/`.
- Consider `.devlab/manifest.toml` or `.devlab/VERSION` to record DevLab layout version and enabled templates.
- Add template options later, e.g. `devlab init --template python-cli` or `devlab init --template fastapi-postgres`.
- Add migration support later, e.g. `devlab init --migrate-existing`, for moving legacy `work/`, `.session-artifacts/`, `specs/system/`, and target-specific config into `.devlab/`.

Implementation concerns:

- Add redaction/size controls before committing logs by default in sensitive projects.
- Keep a migration path for older target repositories that still use `work/`, `.session-artifacts/`, and `specs/system/` paths.
- Keep reusable built-in profiles in DevLab package; let `.devlab/config/profiles/` define target-specific profiles.

## Target-specific Worker Agent Configuration

Current state: agent providers are configured through DevLab code and runtime options, while target-project-specific role/provider/model policy is not represented as a committed workflow artifact.

Open feature: add `.devlab/config/agents.toml` so each target project can configure worker agent behavior per role.

Goals:

- Configure provider, model, effort, timeout, and similar options per role.
- Support defaults plus per-role overrides.
- Let reviewer use a different provider/model from developer to reduce shared blind spots.
- Keep known provider integrations in DevLab package, e.g. `pi`, `codex`, `claude`, `mock`, `scripted`.
- Avoid arbitrary command execution by default; custom provider commands require an explicit trust model or advanced mode.
- Allow CLI overrides for temporary experiments without editing committed config.
- Log the resolved agent configuration for each session for auditability.

Example role configuration:

```toml
[defaults]
provider = "pi"
model = "gpt-5-codex"
effort = "medium"
timeout_seconds = 3600

[roles.architect]
model = "gpt-5"
effort = "high"

[roles.planner]
model = "gpt-5"
effort = "medium"

[roles.developer]
provider = "codex"
model = "gpt-5-codex"
effort = "medium"

[roles.reviewer]
provider = "claude"
model = "claude-sonnet-4.5"
effort = "high"

[roles.integrator]
provider = "pi"
model = "gpt-5-codex"
effort = "high"
timeout_seconds = 7200
```

Possible provider-specific configuration:

```toml
[providers.pi]
command = "pi"
args = ["--model", "{model}", "--effort", "{effort}"]

[providers.codex]
command = "codex"
args = ["exec", "-", "--model", "{model}"]

[providers.claude]
command = "claude"
args = ["--model", "{model}"]
```

Risk note: provider-specific command configuration is executable target-project configuration. The safe default should be known provider names with DevLab-owned invocation code. Arbitrary custom commands should require explicit opt-in, review, and logging.

Suggested precedence:

1. CLI override for the current run.
2. `.devlab/config/agents.toml`.
3. DevLab defaults.

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
