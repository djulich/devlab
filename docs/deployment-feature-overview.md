# Deployment Feature Overview

This document is a reference for designing DevLab deployment support.

## Product Promise

DevLab should not own or mutate production environments by default. Deployment support means:

> DevLab makes a target project deployment-ready by generating, testing, documenting, and versioning the artifacts needed to deploy through common runtime models.

A finished project should answer:

- How do I build the deployable artifact?
- How do I run it locally?
- How do I package it for a VM?
- How do I deploy it to Kubernetes?
- How do I verify that deployment works?
- What configuration and secrets must I provide?
- How do I tear it down?

A finished project should expose project-owned commands, such as Make targets or scripts, for generating deployment artifacts and for deploying them to local, disposable, or staging environments. The project does not need to be left running by `devlab run`; however, the DevLab workflow must be able to generate and test the deployment artifacts it claims to support so developer/reviewer/integrator sessions can verify deployment tasks and milestones.

Production deployment should normally be performed by a human, CI/CD pipeline, GitOps system, platform team tool, or other explicitly configured release mechanism.

## Supported Deployment Families

Initial deployment support should focus on three common deployment families.

### 1. VM / Host Deployment: RPM + systemd

This path targets Linux VMs or bare-metal hosts.

Possible generated artifacts:

```text
packaging/rpm/<app>.spec
systemd/<app>.service
docs/deployment-rpm.md
config examples
```

Typical deployment flow:

```bash
rpmbuild -ba packaging/rpm/<app>.spec
scp ./dist/<app>.rpm user@vm:/tmp/
sudo dnf install /tmp/<app>.rpm
sudo editor /etc/<app>/config.toml
sudo systemctl enable --now <app>.service
systemctl status <app>.service
journalctl -u <app>.service
```

Verification examples:

```bash
rpmbuild -ba packaging/rpm/<app>.spec
rpmlint ./dist/<app>.rpm
systemd-analyze verify systemd/<app>.service
```

Use this when the target environment is VM-based, OS-managed, or expects RPM/systemd integration.

### 2. Single-Host Container Deployment: Docker / Podman / Compose

This path targets local machines, demo environments, simple server hosts, or CI smoke tests.

Possible generated artifacts:

```text
Containerfile
Dockerfile
.dockerignore
compose.yaml
.env.example
docs/deployment-container.md
scripts/smoke-test.sh
```

Typical direct container deployment:

```bash
podman build -t <app>:latest .
podman run --rm -p 8080:8080 <app>:latest
curl http://localhost:8080/health
```

Docker equivalents should also be possible where appropriate:

```bash
docker build -t <app>:latest .
docker run --rm -p 8080:8080 <app>:latest
```

Typical Compose deployment:

```bash
cp .env.example .env
editor .env
docker compose up -d
docker compose ps
curl http://localhost:8080/health
docker compose down
```

Compose is useful when the app needs local dependencies such as PostgreSQL, Redis, queues, workers, or multiple services.

### 3. Kubernetes Deployment

This path targets Kubernetes-compatible clusters.

Possible generated artifacts:

```text
Containerfile
deploy/kubernetes/deployment.yaml
deploy/kubernetes/service.yaml
deploy/kubernetes/configmap.yaml
deploy/kubernetes/ingress.yaml
docs/deployment-kubernetes.md
scripts/deploy-kind.sh
scripts/smoke-test.sh
```

Typical real-cluster deployment flow:

```bash
podman build -t registry.example.com/<app>:1.0.0 .
podman push registry.example.com/<app>:1.0.0
kubectl apply -f deploy/kubernetes/
kubectl rollout status deployment/<app>
kubectl get pods
kubectl logs deployment/<app>
kubectl port-forward service/<app> 8080:80
curl http://localhost:8080/health
```

Local Kubernetes verification can use kind:

```bash
kind create cluster --name <app>-test
podman build -t <app>:dev .
kind load docker-image <app>:dev --name <app>-test
kubectl apply -f deploy/kubernetes/
kubectl rollout status deployment/<app>
scripts/smoke-test.sh
kind delete cluster --name <app>-test
```

Kubernetes support should begin with plain manifests. Helm, Kustomize, GitOps, and operators can be added later when justified by target requirements.

## Deployment Specification

Users describe desired deployment support under:

```text
.devlab/specs/deployment/
```

Example:

```md
# Deployment Specification

The service must support:

- local Podman deployment
- Compose deployment with PostgreSQL
- Kubernetes deployment verified with kind

Production deployment is out of scope. DevLab should provide verified artifacts and deployment instructions.
```

DevLab should use this specification during architecture, planning, implementation, review, and integration. The specification should distinguish deployment targets from deployment environments:

- **Deployment target**: the artifact/runtime family, such as RPM/systemd, container runtime, Compose, or Kubernetes manifests.
- **Deployment environment**: where the target is deployed or tested, such as local Podman, local Compose, kind, staging VM, or staging Kubernetes namespace.

Initial support should focus on local and disposable/staging environments. Production environments may be documented or scaffolded, but executing production deployment is deferred unless explicitly configured in a future feature.

## What DevLab Should Create

Depending on the deployment specification and target system, DevLab may create:

- package specs
- container build files
- Compose files
- Kubernetes manifests
- systemd unit files
- smoke-test scripts
- validation scripts
- project-owned Make targets or equivalent scripts
- documentation
- `.gitignore` updates
- profile validation commands

Common project-owned command names can include:

```text
make deployment-artifacts
make deployment-verify
make deploy-local
make deploy-kind
make undeploy-local
make undeploy-kind
```

Exact names may vary by target project, but generated documentation should identify the supported commands and their required tools.

Example finished project layout:

```text
src/
tests/
Containerfile
.dockerignore
compose.yaml
packaging/
  rpm/
    <app>.spec
systemd/
  <app>.service
deploy/
  kubernetes/
    deployment.yaml
    service.yaml
    configmap.yaml
scripts/
  smoke-test.sh
  deploy-kind.sh
docs/
  deployment.md
```

## What DevLab Should Verify

Deployment verification should be layered. DevLab does not have to leave the system running after `devlab run`, but it must be able to execute the artifact-generation and verification commands needed to prove deployment-related tasks are complete. Reviewers and integrators should treat unsupported or unverified deployment artifacts as incomplete work unless the deployment specification explicitly marks them as documentation-only or future scope.

### Layer 1: Static / Artifact Validation

No external infrastructure.

Examples:

```bash
podman build .
docker build .
rpmbuild -ba packaging/rpm/<app>.spec
rpmlint ./dist/<app>.rpm
systemd-analyze verify systemd/<app>.service
kubectl apply --dry-run=client -f deploy/kubernetes/
kubeconform deploy/kubernetes/
helm template chart/
```

This verifies that artifacts can be built and deployment files are structurally valid.

### Layer 2: Local Ephemeral Deployment

Run locally and tear down aggressively.

Examples:

```bash
podman run --rm ...
docker compose up -d
kind create cluster ...
kubectl apply -f deploy/kubernetes/
docker compose down -v
kind delete cluster ...
```

This verifies that the app starts, exposes expected endpoints, accepts configuration, and passes smoke tests.

### Layer 3: Disposable Test Infrastructure

Use real but explicitly configured non-production infrastructure.

Examples:

- temporary VM
- disposable Kubernetes namespace
- temporary OpenShift project
- test image registry

This verifies real platform behavior, permissions, networking, and image pulls. It must be explicit, allowlisted, isolated, and cleaned up.

## Boundary: DevLab vs User / CI

DevLab should create deployment readiness and project-owned deployment entry points. For local and disposable/staging environments, DevLab may also execute verification commands during the workflow. It should not require the target system to remain deployed after the workflow finishes.

DevLab should not, by default:

- deploy to production
- use production credentials
- create cloud resources implicitly
- mutate shared infrastructure
- push images to production registries unless explicitly configured

Actual deployment after DevLab finishes is usually done by:

- a human following `docs/deployment.md`
- project-owned Make targets or scripts generated by DevLab
- CI/CD pipeline
- GitOps system
- platform team release tooling

## Deferred or Future Scope

The initial feature should defer:

- Kubernetes operators
- Konflux-specific release pipelines
- Terraform or broad cloud infrastructure provisioning
- production deployment automation
- GitOps systems such as Argo CD or Flux
- cloud-specific targets such as ECS, Lambda, Cloud Run, or Azure Container Apps

These are valuable, but they expand scope and risk. DevLab should first make projects deployable through RPM/systemd, container runtime/Compose, and Kubernetes manifests with kind-based verification.
