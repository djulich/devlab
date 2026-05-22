# Deployment Specification and Verification

## Goal

Make DevLab able to plan, implement, review, and integrate deployment support for target projects. A DevLab-created or DevLab-modified project should contain project-owned commands and documentation for generating deployment artifacts and deploying them to local or disposable/staging environments.

`devlab run` does not need to leave the target system running. It must, however, be able to generate and test the deployment artifacts it claims to support so deployment tasks and milestones can be verified by the normal role workflow.

## Non-goals

- Do not deploy to production by default.
- Do not require production credentials in DevLab configuration.
- Do not implement Kubernetes operators, Konflux-specific release pipelines, Terraform/cloud provisioning, or GitOps controllers in the initial feature.
- Do not make DevLab own long-lived runtime state after a workflow completes.

## Design principles

1. **Deployment is target-owned product behavior**
   - Deployment artifacts live in the target project, not in DevLab internals.
   - DevLab provides prompts, validation structure, and workflow expectations.

2. **Deployment targets are separate from environments**
   - Target: RPM/systemd, container runtime, Compose, Kubernetes manifests.
   - Environment: local Podman/Docker, local Compose, kind, staging VM, staging namespace.

3. **Verification is mandatory for claimed support**
   - If the deployment spec says a target is supported, the project should include commands to build/validate it.
   - Reviewers/integrators should reject unverified deployment support unless explicitly scoped as future/documentation-only.

4. **Project-owned entry points are the product interface**
   - Prefer Make targets or scripts that users and CI can run after DevLab finishes.
   - DevLab may call those commands during validation, but users should not need DevLab to deploy the project later.

5. **Production execution remains explicit future work**
   - Production deployment paths may be documented or scaffolded.
   - Executing production deployment needs explicit environment config, credentials policy, approval, rollback, and observability.

6. **Domains specialize roles without changing workflow roles**
   - Keep existing roles as workflow responsibilities: architect, planner, developer, reviewer, integrator.
   - Add task/project domains, initially `general` and `deployment`, as additive prompt overlays.
   - Domain prompts add expertise; they do not replace base role prompts or redefine workflow rules.

## Initial supported deployment families

### 1. RPM/systemd

Artifacts may include:

```text
packaging/rpm/<app>.spec
systemd/<app>.service
docs/deployment-rpm.md
```

Verification examples:

```bash
rpmbuild -ba packaging/rpm/<app>.spec
rpmlint <built-rpm>
systemd-analyze verify systemd/<app>.service
```

### 2. Container runtime: Docker/Podman

Artifacts may include:

```text
Containerfile
Dockerfile
.dockerignore
docs/deployment-container.md
```

Verification examples:

```bash
podman build -t <app>:dev .
podman run --rm <app>:dev <smoke command>
docker build -t <app>:dev .
```

### 3. Compose

Artifacts may include:

```text
compose.yaml
.env.example
scripts/smoke-test.sh
```

Verification examples:

```bash
docker compose config
docker compose up -d
scripts/smoke-test.sh
docker compose down -v
```

### 4. Kubernetes manifests with kind verification

Artifacts may include:

```text
deploy/kubernetes/deployment.yaml
deploy/kubernetes/service.yaml
deploy/kubernetes/configmap.yaml
scripts/deploy-kind.sh
scripts/smoke-test.sh
```

Verification examples:

```bash
kubectl apply --dry-run=client -f deploy/kubernetes/
kubeconform deploy/kubernetes/
kind create cluster --name <app>-test
kind load docker-image <app>:dev --name <app>-test
kubectl apply -f deploy/kubernetes/
kubectl rollout status deployment/<app>
scripts/smoke-test.sh
kind delete cluster --name <app>-test
```

## Proposed user-facing contract

The deployment spec under `.devlab/specs/deployment/` should describe:

```text
- required deployment targets
- required verification level for each target
- supported local/disposable/staging environments
- required tools
- smoke-test expectations
- teardown expectations
- production scope: out-of-scope, documented-only, or explicitly configured future work
```

The target project should expose documented commands such as:

```text
make deployment-artifacts
make deployment-verify
make deploy-local
make undeploy-local
make deploy-kind
make undeploy-kind
```

The exact command names can vary, but the project documentation must identify them.

## Implementation plan

### 1. Document the deployment spec contract

Add a deployment spec template under DevLab init resources:

```text
src/devlab/resources/init/specs/deployment/README.md
```

The template should explain:

- target vs environment
- supported initial target families
- required verification commands
- local/disposable/staging boundary
- production deployment boundary
- secrets and credential expectations

Update user docs to point to `docs/deployment-feature-overview.md`.

### 2. Add task domains

Add a primary task domain to task metadata:

```toml
domain = "deployment"
```

Initial domain values:

- `general` — default for existing tasks and non-specialized work.
- `deployment` — tasks whose primary acceptance criteria concern packaging, deployment artifacts, runtime environment commands, smoke tests, teardown, or deployment documentation.

Implementation notes:

- Store and parse the domain through `task_tracker.py`; do not parse task files elsewhere.
- Default missing domains to `general` so existing task files remain readable during development.
- Validate domain names with a conservative path-safe pattern such as `^[a-z][a-z0-9-]*$`.
- Prefer one primary domain per task. If a task crosses domains, the planner should choose the domain that owns the acceptance criteria or split the work when separation improves reviewability.

### 3. Add role-specific domain prompt overlays

Keep base role prompts as the source of workflow responsibilities. Add domain prompts as optional, role-specific overlays:

```text
src/devlab/resources/prompts/domains/deployment/architect.md
src/devlab/resources/prompts/domains/deployment/planner.md
src/devlab/resources/prompts/domains/deployment/developer.md
src/devlab/resources/prompts/domains/deployment/reviewer.md
src/devlab/resources/prompts/domains/deployment/integrator.md
```

Prompt assembly should include:

```text
conventions
base role prompt
domain role prompt, if applicable
project knowledge
workflow/task context
```

Missing domain prompt files should be ignored; not every domain needs every role overlay.

Selection rules:

- Developer/reviewer sessions: include `domains/<task.domain>/<role>.md` when it exists.
- Architect/planner sessions: include deployment domain overlays when `.devlab/specs/deployment/` has substantive requirements.
- Integrator sessions: include deployment domain overlay when the integrated milestone contains deployment-domain tasks; if milestone-domain detection is not available initially, include it when the deployment spec has substantive requirements.

Each domain prompt should explicitly say that it specializes the current role and does not replace the base role rules.

Deployment overlays should cover:

Architect:

- identify deployment targets and environments
- include deployment architecture in design plan
- call out production boundary and required tools

Planner:

- assign `domain = "deployment"` to deployment tasks
- create tasks for deployment artifacts, commands, verification, documentation, and teardown
- avoid claiming deployment support without verification tasks

Developer:

- implement project-owned commands/scripts
- maintain `.gitignore` for generated artifacts
- prefer local/disposable verification commands where configured

Reviewer:

- verify deployment commands exist and run where practical
- reject unsupported/unverified claims
- check teardown behavior for local/disposable environments

Integrator:

- require deployment milestone evidence before integration
- ensure docs identify how users deploy after DevLab finishes

### 4. Add profile guidance for deployment tooling

Keep execution behind target-owned profile commands rather than hardcoding deployment tools in the orchestrator.

A profile may define commands such as:

```toml
[validation]
commands = [
  "make test",
  "make deployment-artifacts",
  "make deployment-verify",
]
```

If richer validation command modeling does not exist yet, start by documenting expected commands and letting developer/reviewer roles run them manually through the normal agent workflow.

### 5. Add doctor/status observability checks

Add non-mutating checks where practical:

- deployment spec exists but is empty or placeholder-only
- deployment spec claims production execution without an explicit warning/configuration
- obvious missing documentation references after init templates change

Do not make `doctor` run deployment tools or mutate state.

### 6. Add deterministic evaluation scenarios

Add workflow evaluations that require DevLab to produce deployment artifacts for small target systems.

Start with black-box checks that inspect files and run safe commands only when tools are available or simulated.

Possible scripted scenarios:

1. **Containerized CLI or web app**
   - Requires Containerfile/`.dockerignore`/Make targets/docs.
   - Scripted agent creates artifacts.
   - Harness checks file presence and command names.

2. **Compose deployment**
   - Requires `compose.yaml`, `.env.example`, smoke-test script, teardown command.
   - Harness checks static content and docs.

3. **Kubernetes manifest deployment**
   - Requires `deploy/kubernetes/*.yaml`, kind command documentation/scripts.
   - Harness can run YAML/static checks if available, otherwise inspect artifacts.

4. **RPM/systemd packaging**
   - Requires spec file, systemd unit, RPM docs/Make target.
   - Harness can run `systemd-analyze verify`/`rpmbuild` only when available, otherwise keep checks structural.

Live-agent evaluations should remain opt-in and should initially focus on one deployment family at a time.

### 7. Add optional tool availability diagnostics

Deployment tools are environment-dependent. Provide diagnostics, not mandatory global requirements, for tools such as:

```text
podman
docker
docker compose
kind
kubectl
kubeconform
rpmbuild
rpmlint
systemd-analyze
```

This can be part of `doctor` or a future `devlab doctor --deployment` mode. Avoid making all tools mandatory for every project.

### 8. Preserve workflow boundaries

Do not add deployment-specific orchestration branches initially. Deployment support should flow through:

- deployment specs
- task domains
- role-specific domain prompt overlays
- tasks/milestones
- target-owned profile commands
- normal reviewer/integrator validation

The orchestrator should continue to select workflow roles. Prompt assembly and task metadata should select domain expertise. Only add specialized orchestration later if evaluations show that prompt/profile-driven behavior is insufficient.

## Acceptance criteria

- Init deployment spec template describes supported deployment targets, environments, verification expectations, and production boundary.
- Task metadata supports a primary `domain`, defaulting to `general`.
- Prompt assembly supports optional role-specific domain overlays under `prompts/domains/<domain>/<role>.md`.
- Deployment domain prompts require deployment artifacts to be verified when deployment support is claimed.
- At least one deterministic evaluation proves a target can become deployment-ready with deployment-domain tasks, project-owned commands, and documentation.
- `devlab doctor` remains non-mutating and does not require deployment tools globally.
- Documentation explains that `devlab run` need not leave software running, but supported deployment artifacts must be generatable and testable during the workflow.

## Open questions

- Should DevLab define canonical Make target names, or only require documented project-owned commands?
- Should profile validation commands become structured first-class data before deployment support, or is prompt guidance enough initially?
- Should `doctor` warn about unknown task domains immediately, or should unknown domains simply omit prompt overlays until a domain registry exists?
- Which deployment family should be the first live-agent evaluation target: container runtime, Compose, Kubernetes/kind, or RPM/systemd?
- How much static validation should deterministic tests perform without making host tool availability a hard requirement?
