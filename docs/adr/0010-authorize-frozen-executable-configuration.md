# ADR 0010: Authorize Frozen Executable Configuration

## Status

Accepted.

## Context

DevLab executes target-owned provider and profile lifecycle configuration. It
must support unattended operation, but interpreting provider-specific permission
flags would require continuously tracking external provider behavior and would
still produce incomplete safety judgments.

A repository-local trust marker would allow a target to authorize itself.
Documentation alone would preserve unattended operation but would not detect
unreviewed executable-configuration changes.

## Decision

DevLab treats provider-native permission, approval, authentication, network, and
sandbox policy as opaque and operator-owned.

Operator-facing commands that start configured processes build a canonical,
versioned snapshot of effective provider invocation and profile lifecycle and
default-validation configuration. DevLab computes its digest before configured
version discovery or other target-owned execution, obtains authorization, and uses
the frozen parsed snapshot for the entire command.

Authorization is provided by exactly one of:

- matching operator-local trust scoped to canonical workspace, agent-config
  source, and digest;
- an independently supplied expected digest;
- explicit acceptance of the current snapshot for one invocation.

Persistent trust lives in user-local DevLab state, not the target repository.
Explicit current-snapshot acceptance does not create persistent trust and is
intended for externally contained or disposable environments. Runs record the
digest and authorization source.

## Consequences

- DevLab does not maintain provider-specific lists of dangerous options.
- Formatting-only configuration changes do not require renewed trust.
- Executable-value or invocation-override changes require renewed authorization.
- Configuration changes made during a run cannot take effect in that run.
- A task that changes executable configuration may finish its bounded
  developer/reviewer cycle using the frozen snapshot. DevLab then stops successfully
  before preparing a session outside that task cycle, leaving a clean worktree and
  requiring a fresh authorized invocation.
- A newly referenced profile absent from the frozen snapshot fails before DevLab
  creates session artifacts.
- Invalid replacement executable configuration stops cleanly before another session
  is prepared and must be corrected before it can be authorized.
- Expected digests support verification-oriented ephemeral CI without allowing
  the repository to approve an arbitrary current value.
- Explicit current-snapshot acceptance supports contained environments but
  deliberately provides a weaker authorization guarantee.
- Trust authorizes configured process entry points only. It does not certify
  repository scripts, external binaries, transitive command behavior, or contain
  processes after launch.
- Library callers that inject provider objects directly remain responsible for
  authorizing those objects because they bypass target configuration loading.
