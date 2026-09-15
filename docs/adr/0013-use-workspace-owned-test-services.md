# ADR 0013: Use Workspace-Owned Test Services

## Status

Accepted.

## Context

A declared disposable database can unblock several developer, reviewer, and
validation operations. Session-level setup/teardown cannot provide reliable
ownership, restart recovery, or connection settings shared across those
operations. Prerequisite checks should continue to observe conditions without
provisioning resources.

## Decision

Targets declare managed test services and profile operation scopes. DevLab
prepares the required services before checking ordinary operation prerequisites,
using the authorized frozen executable configuration. Target commands implement
ensure, readiness, and destroy; DevLab provides a random instance identity,
durable state, private result paths, bounded execution, and environment transport.
Host tools and locally required images remain operator prerequisites.

Service lifetime belongs to the workspace, not a session or planning generation.
An OS-backed lock prevents cleanup while dependent work uses services. Explicit
cleanup is the only automatic resource-removal entry point. Services cannot be
adopted based on names, copied state, or changed definitions.

Non-secret records live in `.devlab/test-services/`. Ownership transitions and
workflow events are committed separately from product edits before continuing.
Private exports and raw service logs live in ignored `.devlab/local/test-services/`.
Exports are data, never shell code, and enter explicit invocation environments.

A saved definition supports cleanup after removal or change, but cannot authorize
itself. Matching trust for an unchanged current executable configuration covers
cleanup. Otherwise operators authorize the exact saved cleanup definition using
its separate digest. Trust does not freeze script contents or certify ownership
checks inside target-owned commands.

## Consequences

- Authorized continuation can provision and reuse declared test services without
  an approval prompt for every role session.
- Partial setup retains its original identity; repeatable ensure reconciles it.
  Failed cleanup requires explicit cleanup retry.
- Containers can outlive failed or interrupted runs. Operators must clean them up.
- Resource creation can precede an unrelated ordinary prerequisite blocker.
- Service records survive generation replacement; moving a workspace requires
  resolving ownership in its original location.
- The initial process-group and file-lock implementation requires POSIX. This is
  not a cross-workspace sharing or parallel workflow facility.
- Arbitrary target/provider commands can still disclose environment variables.
  Private service artifacts do not promise redaction of all agent output.

Authorization, identity, persistence, interruption, and locking are reusable
mechanics. Required service selection and task/validation failure policy remain
software-workflow responsibilities. No generic workflow kernel is extracted.
