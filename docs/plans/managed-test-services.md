# Managed Test Services

Status: planned; not implemented.

## Problem and intended outcome

During the system-evolution comparison, operator setup of a disposable test
database unblocked work that DevLab could reasonably prepare itself. Support
declared local test services so an authorized `devlab continue` can establish
them, verify readiness, and reuse them across bounded sessions and CLI restarts.

Keep the completed comparison and its recorded operator interventions unchanged.
Validate this capability in fresh disposable workspaces, never in scored targets
or against preserved evaluator resources. This plan is independent of the
[session inactivity monitor](session-inactivity-monitor.md).

Current code provides useful foundations but does not provide this contract:

- `profiles.py` loads profile prerequisites and session lifecycle commands.
- `orchestrator.py` checks applicable session, setup, and validation prerequisites
  before invoking profile setup. A missing database can therefore block the
  command intended to start it.
- `environment.py` runs pre-session, setup, and post-session commands. These are
  session-scoped; exporting variables in a subprocess cannot configure later
  agent or validation processes.
- `agents.py` already accepts an invocation environment mapping.
- Executable configuration is frozen and authorized under ADR 0010.

## Scope and architectural boundary

Introduce **managed test services**: target-declared local resources, such as a
disposable PostgreSQL server, with workspace lifetime and explicit cleanup.
DevLab owns orchestration, operation identities, records, and environment
propagation. Target-owned commands implement provisioning, readiness, and
ownership-aware removal. DevLab contains no PostgreSQL or Docker-specific
orchestration logic.

Do not install host tools, obtain external credentials, adopt existing services,
infer provisioning from failed commands, or let role sessions authorize new
commands. Preserve existing profile lifecycle and prerequisite semantics for
profiles without managed test services. Provisioning failure is infrastructure
failure, not a product defect or permission to accept an incomplete handoff.

Authorization, durable operation identity, bounded execution, interruption, and
resume are reusable mechanics. Selecting services for developer/reviewer work
and milestone validation, and leaving task transitions unchanged on failure,
are software-workflow policy. Implement these in existing owners; do not create
a generic resource framework or extract a workflow kernel.

## Proposed configuration

Declare services once in `.devlab/config/test-services.toml`; profiles reference
service IDs. A shared declaration avoids creating duplicate servers when several
profiles or milestone tasks require the same service.

Illustrative service declaration (new syntax):

```toml
[services.postgres]
summary = "Disposable PostgreSQL server for project tests"
host_checks = ["docker info >/dev/null 2>&1"]
ensure = "./scripts/test-db ensure"
check = "./scripts/test-db check"
destroy = "./scripts/test-db destroy"
exports = ["TEST_DATABASE_URL"]
ensure_timeout_seconds = 180
check_timeout_seconds = 30
destroy_timeout_seconds = 60
```

Illustrative profile reference:

```toml
[[test_services]]
id = "postgres"
required_for = ["session", "setup", "validation"]
```

All timeouts must be finite positive integers; reject booleans. Give host checks
the check timeout. Require ensure/check/destroy commands, unique IDs and export
names, valid references, and nonempty operation scopes. Reject unknown keys.
Do not introduce service-to-service dependencies in this slice. Use one
target-owned aggregate service when several containers must be managed together.

Include service declarations, references, commands, limits, and allowed export
names in the frozen executable snapshot and trust display. Existing authorization
mechanisms apply; matching trust does not require repeated session approval.
Configuration edits during a run follow existing frozen-configuration rules.
Authorization covers configured entry points, not transitive script contents or
proof that a script is safe, as stated in ADR 0010.

## Preparation and prerequisite ordering

For an applicable mutation operation:

1. Resolve the route, profiles, effective validation, and required service set
   from the frozen snapshot. Preserve existing eligibility and recovery gates.
2. Authorize before executing any target command. Acquire exclusive workspace
   use of managed test services before checking or changing their state.
3. Run declared service host checks. Missing tools, access, or host capabilities
   stop with actionable prerequisite guidance; do not attempt installation.
4. Ensure required services in stable ID order and verify readiness. Reuse a
   matching ready instance only after a fresh successful readiness check.
5. Load validated exports and evaluate existing operation prerequisites with
   that environment. Checks and attestations retain their current meaning.
6. Run existing session setup, role invocation, and validation as applicable.
   Recheck readiness before each later dependent validation operation.

Managed services are prepared before ordinary operation prerequisites because
those prerequisites can describe the service's outputs. Service host checks
provide the separate pre-provisioning gate. This can start an explicitly required
service before an unrelated ordinary prerequisite blocks; retain it for reuse
and report it. Do not guess dependencies from shell commands.

Prepare services for actual operations, including direct validation/resume
paths, rather than only when `managed_roles` selects session setup. Do not
provision for planner, architect, researcher, smoke tests, or read-only commands
merely because a profile declares a service. Preserve current role/profile
selection policy.

`prerequisite check` may evaluate its declared check but never provisions.
`status`, `doctor`, prompt assembly, and prompt-context reporting inspect stored
state only; label readiness as last observed, not current health.

## Lifecycle, identity, and recovery

Use a random DevLab-created instance identity bound to canonical workspace,
service ID, and service-definition digest. Persist it atomically **before** the
first ensure invocation. Pass identity and private state paths as reserved
environment variables, never as unescaped command interpolation.

| Recorded state | Next permitted behavior |
|---|---|
| Absent or destroyed | Persist a new identity, then ensure |
| Preparing or failed preparation | Retry ensure once per CLI operation with the same identity, then check |
| Ready | Check; if unhealthy, run idempotent ensure once, then check |
| Destroying or failed cleanup | Require explicit cleanup retry; do not ensure |
| Changed definition, wrong workspace, or invalid record | Stop with recovery guidance; do not adopt or overwrite |

Ensure must be repeatable, preserve existing owned test data, and reconcile
partial creation using the supplied identity. It must refuse resources whose
ownership does not match. A target may fail safely instead of repairing an
unhealthy instance; DevLab does not fall back to destruction and recreation.
Write ready only after exports validate and readiness succeeds. A failed command
may already have created resources: retain the identity and failure record.

Services outlive sessions, command failure, and planning-generation replacement.
Do not automatically destroy them at session teardown, task completion, or CLI
exit. Existing profile cleanup scripts must not remove managed test services.

Add explicit `devlab test-service cleanup <id>` and read-only
`devlab test-service status` operator adapters. Cleanup persists destroying before
execution, supplies the original identity, and marks destroyed only after success.
Destroy must be idempotent, verify ownership before removal, and treat confirmed
absence as success. Never prune globally or delete resources selected only by a
name prefix. Existing failed-session artifact cleanup must not erase service
records or remove services.

Persist the original executable service definition with its digest so cleanup
can still be presented and authorized after configuration removal or change.
Treat this record as untrusted input: authorize the exact saved definition using
the existing operator-local/expected-digest/explicit-acceptance mechanisms.
Trust for a different current definition does not authorize historical cleanup.
Block replacement until old ownership has been resolved. Do not silently run old
commands, and do not assume a saved command freezes the script it references.

Hold an OS-backed workspace lock throughout preparation and all dependent agent
or validation execution; cleanup takes the same lock. Contention fails clearly
rather than allowing cleanup during use. This introduces no parallel workflow
support. After process death, the lock is released and durable state drives
recovery; do not break locks by guessing from a stored PID.

Bound command execution and owned child-process termination, including partial
setup and interruption. Killing a command does not roll back container side
effects. Record interrupted operations where possible; an abrupt kill leaves a
preparing/destroying record that the next invocation can reconcile.

## Durable records and connection settings

Keep non-secret service state in a versioned target-workspace record under
`.devlab/`, outside archived planning-generation bundles. Include workspace
binding, service/instance IDs, definition digest, saved definition, state,
operation timestamps, outcome, and private-artifact references. Integrate record
changes with existing workflow Git commit boundaries. Do not store live state in
conversation memory or infer it from provider transcripts.

Store credentials and raw command output under a dedicated ignored
`.devlab/local/test-services/` directory, with private directory/file permissions.
Before writing, verify that it is ignored and untracked; refuse unsafe existing
paths or symlinks. Initialization and an explicit migration path establish this
layout; reporting never repairs it. Non-secret ownership remains available even
if private files disappear, so same-identity ensure can recover them or fail with
clear guidance. Copying or relocating a workspace must not silently claim an old
instance; canonical-workspace mismatch blocks reuse and cleanup.

The ensure command writes a bounded, versioned JSON result to a DevLab-specified
private path. Require an exact instance ID and an `environment` mapping of string
values with exactly the configured export keys. Reject malformed, oversized,
unexpected, or missing output. Use atomic publication and prevent stale output
from being accepted after a failed/retried invocation. Do not parse stdout as
connection data or source an arbitrary shell file.

Pass the mapping explicitly to applicable prerequisite checks, profile lifecycle
commands, provider invocations, and orchestrator validation. Never mutate global
`os.environ`. Managed export values override inherited values for their declared
keys, preventing an inherited production URL from replacing the managed test URL.
Reject exports for DevLab control variables and process-control keys such as
`PATH`, `HOME`, and loader/Python injection settings; centralize and document this
restriction. This is not a sandbox against arbitrary authorized scripts.

Deduplicate a shared service across profiles. Reject conflicting export keys
from different services before running the dependent operation. Preserve profile
context when deduplicating milestone validation: commands with different service
bindings must not be collapsed into one invocation. Avoid exposing unrelated
services to a task; a milestone session receives only its resolved service union.

Treat all export values as sensitive. Keep them out of prompts, committed
metadata, events, trust displays, and command-line arguments. Reports contain
export names and instance IDs only. Keep raw provisioning logs private; sanitize
summaries. Extend logging tests with secret canaries. Downstream target/provider
commands can still print their environment; document that this mechanism does
not guarantee redaction of arbitrary agent output.

## Ownership and reporting

- `profiles.py`: declaration/reference loading and validation; keep closely
  coupled service configuration here initially.
- `environment.py`: service lifecycle types, bounded command execution, result
  validation, and the cohesive file-backed service tracker.
- `workspace.py`: service mutation handle and cached read-only service records.
- `executable_config.py`: frozen definitions and current/historical authorization.
- `orchestrator.py`: preparation ordering, route selection, blocker/recovery
  policy, and applying service environments to existing operations.
- `agents.py` and `session_logging.py`: provider environment transport and
  non-secret instance provenance; no provisioning policy.
- `workflow_events.py`, run summaries, and reporting adapters: provisioning
  attempts, readiness, reuse, cleanup, duration, outcome, and next-command advice.
- `init.py`, artifact hygiene, and generation handling: private-path setup and
  preservation of workspace-lifetime records.
- `cli.py`: thin explicit cleanup/status adapters.

Keep the service tracker and lifecycle together unless implementation establishes
a self-contained extraction. Do not bypass workspace handles for mutations.
Use structured infrastructure failure details distinguishing host prerequisites,
ensure, readiness, exports, ownership/configuration mismatch, and cleanup. Persist
enough context for `continue` guidance without changing task/handoff acceptance or
creating product findings. Record attempts even when no agent session starts.
Count provisioning duration in run accounting separately from provider duration.

## Implementation sequence

1. Add strict configuration, frozen snapshots, trust display, and compatibility
   tests. Finalize schema names and limits before documenting them as supported.
2. Implement tracker/handle, private-artifact layout, lock, identity, command
   protocol, state transitions, and explicit cleanup with fake target commands.
3. Integrate preparation and environment propagation across session, standalone
   validation, retry/resume, and milestone paths. Preserve validation provenance.
4. Add events, summaries, read-only status/doctor output, and recovery guidance.
5. Add a target-owned disposable PostgreSQL example in a fresh demo fixture;
   document repeatability, ownership checks, and explicit cleanup.
6. Update `CONTEXT.md`, `docs/design.md`, and an ADR for workspace lifetime and
   ownership after implementation confirms these contracts. Run full validation.

## Acceptance criteria

- Existing configurations retain their behavior; no service is inferred or
  provisioned without a declaration and executable authorization.
- Missing host prerequisites launch neither provisioning nor dependent sessions.
- A service supplied by provisioning can satisfy a session/validation prerequisite
  that would previously have stopped before setup.
- Developer, reviewer, and validation receive the same owned instance and valid
  connection settings across CLI restarts; shared profiles do not duplicate it.
- Read-only reporting performs no commands or state changes; explicit prerequisite
  checks never provision. Stored readiness is clearly labeled.
- Crashes before/after resource creation, missing result files, malformed exports,
  readiness failure, timeout, interruption, and failed cleanup retain recoverable
  ownership. Retries are bounded and use the original identity.
- Cleanup never targets unowned resources, waits for no unbounded command, and
  cannot overlap dependent work. Removed/changed definitions and moved workspaces
  stop safely; historical cleanup requires matching authorization.
- Test two independent workspaces, duplicate profile references, conflicting
  exports, inherited connection URLs, and milestone validation with distinct
  bindings. Preserve task validation precedence and failure classification.
- Secret canaries do not appear in DevLab-created public service artifacts;
  unsafe private paths fail before secret writes. Generation replacement and
  ordinary artifact cleanup preserve service ownership.
- Fresh optional Docker integration proves provision, readiness, preserved test
  data, resumed reuse, and removal of only the created resources. Missing Docker
  is an explicit skip/unverified prerequisite, never an installation request.
- Run `UV_CACHE_DIR=/tmp/uv-cache GOCACHE=/tmp/devlab-go-cache make check` for code
  changes and demo checks when changing demo fixtures. No paid agent session or
  existing evaluator resource is required by the automated tests.

## Deferred work

Automatic expiry, shared services across workspaces, external/cloud provisioning,
resource adoption, secret-manager integrations, service dependency graphs, and
parallel workflow execution are outside this slice. The initial limitation is
deliberate: resources may remain until explicit cleanup, and target-owned scripts
remain responsible for honoring the ownership protocol.
