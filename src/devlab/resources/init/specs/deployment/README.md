<!-- devlab:placeholder -->
<!-- This optional overlay is inactive while the marker above is present.
     Remove the marker when this file contains project-specific deployment
     requirements. -->

# Optional Deployment Requirements Overlay

Use this file when the project must produce or verify deployment, packaging,
runtime, or operations artifacts. DevLab adds deployment-specific planning
guidance and diagnostics after the placeholder marker is removed. For larger
projects, keep this file as an overview and add more Markdown files in this
directory.

DevLab can generate and verify deployment artifacts, but it does not deploy to
production by default.

## Deployment Targets

List required artifact or runtime families, for example:

- RPM package plus systemd service
- Container image runnable with Docker or Podman
- Compose stack for local or demo use
- Kubernetes manifests verified with kind

## Deployment Environments

List where artifacts should be deployable or testable, for example:

- local Podman or Docker
- local Compose
- kind cluster
- disposable staging VM
- disposable staging Kubernetes namespace

## Required Project Commands

List expected project-owned commands or scripts, for example:

- `make deployment-artifacts`
- `make deployment-verify`
- `make deploy-local`
- `make undeploy-local`
- `make deploy-kind`
- `make undeploy-kind`

## Verification Expectations

Describe what DevLab must be able to verify during the workflow:

- artifact builds succeed
- manifests or package metadata validate
- local or disposable deployment starts successfully
- smoke tests pass
- teardown works

## Configuration and Secrets

Describe required runtime configuration and secret sources. Do not commit real
secrets. Provide example files or templates instead.

## Production Scope

State whether production deployment is out of scope, documentation-only, or
requires explicit future configuration. DevLab should not execute production
deployment by default.
