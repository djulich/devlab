# Runtime Prerequisites and Managed Test Services

Target profiles declare conditions and workspace-owned services needed by agent
sessions, environment setup, or validation. DevLab may check or prepare only
what the target declares; it does not install host tools, obtain credentials,
pull missing images, or infer repairs from arbitrary command failures.

All commands in this document run from the target workspace.

## Profile Prerequisites

Profiles use `[[prerequisites]]` tables. `required_for` accepts `session`,
`setup`, and `validation`, naming workflow operations rather than roles.

Each prerequisite defines exactly one condition:

- `check`: a non-mutating shell command whose zero exit status means ready;
- `environment`: an environment variable that must be present and non-empty; or
- `attestation`: operator intent recorded outside the target workspace.

```toml
[[prerequisites]]
id = "docker-engine"
required_for = ["validation"]
check = "docker info"
summary = "Docker Engine must be reachable."
guide = ".devlab/config/prerequisites/docker-engine.md#docker-engine"

[[prerequisites]]
id = "test-database-authorized"
required_for = ["validation"]
attestation = "I am authorized to use the disposable integration database."
summary = "Database use requires operator authorization."
sensitive = true
```

Automatic checks run before a session that will use them and again at the
applicable setup or validation boundary. Failed checks consume no agent session
and write `.devlab/prerequisite-blocker.json`. Attestation approvals are bound
to the prerequisite's semantic fingerprint and remain valid until revoked or a
semantic field changes.

Use:

```bash
devlab prerequisite list
devlab prerequisite blocked
devlab prerequisite show PROFILE PREREQUISITE
devlab prerequisite check PROFILE PREREQUISITE
devlab prerequisite approve PROFILE PREREQUISITE
devlab prerequisite revoke PROFILE PREREQUISITE
```

The explicit `check` command observes only; it never prepares a prerequisite.

### Resolution guides

`guide` may name a focused file under `.devlab/config/prerequisites/` or a
Markdown section using `path.md#heading-slug`. DevLab renders the selected
section through the next heading of equal or higher level. A guide should state
the required capability, installation or provisioning boundary, configuration,
exact readiness check, common failures, and security or cleanup constraints.

`devlab doctor` reports missing files/headings and selected guide content over
8,000 characters. Guides are operator instructions and are never executed.

## Declared Runtime Preparation

A command-check prerequisite may declare one automatic preparation action:

```toml
[[prerequisites]]
id = "test-config"
required_for = ["session"]
check = "test -f .local/test.toml"
prepare = "./scripts/prepare-test-config"
prepare_kind = "workspace_local"
prepare_outputs = [".local/test.toml"]
prepare_timeout = 120
```

DevLab checks first, prepares once when the check is unsatisfied, and checks
again. `workspace_local` outputs must be relative, ignored, and untracked.
`owned_service` preparation may initialize fixtures or schemas inside an
applicable managed test service.

Preparation is available only to mutating workflow commands. It does not apply
to environment-variable or attestation prerequisites, checks that error, or a
missing host executable reported by exit 127. It may not create tracked product
artifacts. See [ADR 0014](adr/0014-prepare-only-declared-runtime-prerequisites.md).

## Managed Test Services

Targets declare workspace-lifetime local test resources in:

```text
.devlab/config/test-services.toml
```

Profiles reference each service where it is needed:

```toml
[[test_services]]
id = "postgres"
required_for = ["session", "setup", "validation"]
```

A service defines host checks, repeatable `ensure`, readiness `check`, explicit
`destroy`, exported environment names, and bounded command timeouts. DevLab
supplies a durable random instance identity and private result path. The ensure
command atomically publishes a JSON result containing schema version 1, the
matching instance identity, and string values for exactly the declared exports.

Non-secret ownership state is committed under `.devlab/test-services/`. Private
exports and raw logs live under ignored `.devlab/local/test-services/`. New
targets ignore `/local/`; existing targets must initialize that boundary and
commit the resulting `.devlab/.gitignore` change:

```bash
devlab test-service init
```

Inspect and clean up services explicitly:

```bash
devlab test-service status
devlab test-service cleanup SERVICE_ID
```

If a service definition changed or disappeared, inspect its saved cleanup with
`--show`, then use its displayed digest with `--require-exec-config-digest`,
record trust with `--trust`, or explicitly accept it for one externally
contained invocation. Cleanup must target the supplied ownership identity; it
must not prune resources by a global name or prefix.

Services survive sessions, failed runs, and planning-generation replacement.
Only explicit cleanup ends their lifetime. Failed cleanup blocks reuse until it
succeeds. The initial implementation requires POSIX process groups and file
locking. See [ADR 0013](adr/0013-use-workspace-owned-test-services.md) and the
[PostgreSQL example](../demos/managed-test-services/).

## Authorization and Safety

Prerequisite checks/preparation, profile service references, and managed-service
definitions are part of the executable-configuration snapshot. Review and
authorize changes before continuation:

```bash
devlab trust executable-config
devlab continue
```

The trust command displays the effective configuration and fingerprint before
asking for approval.

Trust authorizes configured entry points; it does not sandbox scripts, certify
their transitive behavior, or prove that a target command correctly enforces
resource ownership. Host tools, images, credentials, attestations, and shared
infrastructure remain operator or CI responsibilities.
