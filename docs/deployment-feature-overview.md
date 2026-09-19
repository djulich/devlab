# Deployment Support

DevLab treats deployment as a software-workflow domain, not as a built-in
deployment engine. A target specification states which artifacts, runtime
families, environments, and verification claims are required. Architect,
planner, developer, reviewer, and integrator sessions then use the same durable
task, profile, validation, and finding mechanics as other software work.

## Product Contract

When deployment is in scope, DevLab can help a target project create, test,
document, and version deployment artifacts. Examples include:

- OS packages and service definitions;
- container build files and Compose configurations;
- Kubernetes manifests;
- configuration examples and secret-input documentation;
- project-owned build, smoke-test, deployment, and teardown commands.

The target specification chooses the applicable outputs. DevLab does not imply
that every project must support RPM, containers, Compose, Kubernetes, or any
other particular platform.

Production deployment is outside the default workflow boundary. A human,
CI/CD pipeline, GitOps system, or platform-owned release tool normally performs
that action. Production execution must never be inferred merely because a
deployment requirements overlay or validation command exists.

## Specification and Verification

Deployment requirements are an optional overlay on the primary system
specification. Initialization provides an inactive checklist under:

```text
.devlab/specs/deployment/
```

Remove the checklist's `<!-- devlab:placeholder -->` marker after adding
project-specific requirements. That, or adding another non-empty Markdown file
in the directory, activates deployment-specific planning guidance and
diagnostics. Projects where deployment is out of scope can leave the scaffolded
checklist inactive.

Specifications should distinguish:

- the deployment target or artifact family, such as a system package,
  container, Compose application, or Kubernetes manifest; and
- the environment where it may be exercised, such as a local runtime,
  disposable cluster, staging namespace, or production platform.

Verification should cross the boundary of the claim. Depending on the target,
that may include static artifact validation, an ephemeral local deployment, or
explicitly configured disposable infrastructure. Project-owned commands belong
in task validation or profile defaults so the orchestrator can record their
outcomes during task and milestone verification.

DevLab deliberately has no deployment-specific validation schema. Existing
task acceptance criteria, task/profile validation commands, milestone
verification records, and documentation express deployment evidence. See
[ADR 0009](adr/0009-defer-structured-deployment-validation-metadata.md).

## Operator and CI Boundary

DevLab may invoke target-owned commands that use tools such as Podman, Docker,
kind, kubectl, rpmbuild, or systemd-analyze. It does not install missing host
tools, pull undeclared images, obtain credentials, or silently provision shared
infrastructure. Missing capabilities remain explicit operator or CI
prerequisites. See [ADR 0008](adr/0008-do-not-install-host-deployment-tools.md)
and [Runtime Prerequisites and Managed Test
Services](runtime-prerequisites.md).

By default DevLab must not:

- deploy to production;
- use production credentials;
- create cloud resources implicitly;
- mutate shared infrastructure; or
- push images to production registries.

Local or disposable resources may be used only through reviewed target-owned
commands and the configured profile, prerequisite, or managed-test-service
contracts. Their setup, ownership, verification, and cleanup boundaries should
be explicit in the target repository.

## Evidence

Deterministic and live deployment scenarios are described in
[Workflow Evaluations](evaluations/README.md). Dated results under
[`evaluations/baselines/`](evaluations/baselines/) record evidence for specific
targets and environments; they do not promise universal support for every
deployment platform.
