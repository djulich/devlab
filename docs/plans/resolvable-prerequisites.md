# Resolvable Prerequisites

Status: implemented (2026-09-15).

## Problem

Profile prerequisites originally observed external conditions and stopped the
workflow when they were absent. Some conditions are routine runtime preparation
that DevLab can perform safely when the target declares an exact action. Making
the operator create ignored test configuration or initialize an already-owned
test database adds interruption without adding useful judgment.

Host software installation, credentials, authority, and ambiguous external
resources remain operator concerns.

## Decision

A command-check prerequisite may declare one authorized `prepare` command.
During a mutating workflow operation DevLab checks the condition, prepares it
once only when the result is `unsatisfied`, then checks it again. A satisfied
condition runs no preparation. An errored check or exit 127 is not prepared;
exit 127 is reported as an unverified missing host executable.

Preparation has one explicit kind:

- `workspace_local` names one or more `prepare_outputs`. Every output must be a
  workspace-relative, ignored, untracked path. Git-visible changes stop the
  workflow rather than being silently accepted as preparation.
- `owned_service` requires an applicable managed test service in the profile.
  This is for initialization inside the service, such as migrations or fixtures;
  service provisioning and ownership remain under ADR 0013.

Preparation commands must be repeatable. They run from the workspace with the
applicable managed-service environment, a finite timeout, captured logs, and
owned-process cleanup. Sensitive output is redacted from the preparation log.
The command, kind, outputs, and timeout are part of executable-configuration
trust and the prerequisite semantic fingerprint.

`devlab prerequisite check` remains read-only and never prepares. Status,
doctor, prompt assembly, and other reporting paths remain non-mutating.
Preparation attempts append durable workflow events with outcome and duration.
Failures become ordinary prerequisite blockers and consume no agent session.

## Consequences

- DevLab can create ignored local test settings, temporary certificates and
  runtime fixtures, and initialize schemas or fixtures in owned test services.
- It does not install executables, package managers, SDKs, Docker, or container
  images; obtain credentials; satisfy attestations; or mutate tracked product
  artifacts.
- Trust authorizes the configured command but does not sandbox it. DevLab checks
  declared output policy and detects new Git-visible state, while target scripts
  remain responsible for their transitive effects.
- A preparation that exits successfully without satisfying its check still
  blocks, clearly reporting that the post-check remained unsatisfied.

These check/prepare/recheck, timeout, and provenance mechanics are reusable.
The eligible preparation kinds and their relationship to profiles and test
services are DevLab's software-workflow policy. No kernel interface is extracted.

## Validation

Focused tests cover success and idempotence, missing host executables, failure,
sensitive output, strict profile parsing, executable-config fingerprinting,
ignored-output enforcement, durable events, and workflow continuation.
