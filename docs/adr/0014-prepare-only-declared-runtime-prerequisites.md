# ADR 0014: Prepare Only Declared Runtime Prerequisites

## Status

Accepted.

## Context

Stopping for every absent prerequisite makes routine test setup unnecessarily
interactive. Automatically repairing arbitrary failures would let repository
configuration install host software, obtain credentials, or make poorly owned
external changes under the vague label of prerequisite resolution.

## Decision

DevLab may automatically prepare a prerequisite only when an authorized profile
declares a command check, prepare command, finite timeout, and one supported
preparation kind. It checks first, prepares an unsatisfied condition once, and
checks again. It never prepares attestations, environment-variable requirements,
errored checks, or checks that exit 127 because a host executable is missing.

`workspace_local` preparation is limited to declared ignored and untracked
runtime paths. `owned_service` preparation requires an applicable service whose
identity and lifecycle DevLab already manages under ADR 0013. New Git-visible
workspace state is a contract violation. Tracked generated artifacts remain
agent-owned product work.

Only mutating workflow operations prepare. Explicit prerequisite inspection and
all reporting remain observational. Attempts are recorded with outcome,
duration, and log path, without exposing sensitive output.

## Consequences

- Routine runtime setup can proceed unattended after executable configuration is
  authorized.
- Host tools, container images, credentials, authority, shared infrastructure,
  and undeclared conditions still require the operator.
- Target commands must be repeatable and honor the declared boundary. Trust and
  Git-state checks reduce accidental scope but are not a sandbox.
- Further preparation kinds require an explicit ownership and recovery contract,
  rather than broadening the existing command into a generic repair hook.
