# Idea Greenhouse — Generation 2 Deployment Specification

## 1. Deployment goal

Upgrade and run Idea Greenhouse as exactly three long-running Compose services:

1. `db` — PostgreSQL 17;
2. `api` — FastAPI/Uvicorn; and
3. `frontend` — nginx serving React and proxying `/api`.

The existing generation 1 `postgres-data` volume must be upgraded in place.
Deleting, replacing, or silently switching away from that volume invalidates the
upgrade.

This file is the complete desired-state deployment specification.

## 2. Changes from generation 1

- API startup applies the generation 2 migration to existing data.
- Deployment verification checks preserved generation 1 rows and their new
  default fields.
- Smoke verification exercises archiving and stale-version conflicts.
- The service topology and persistent volume identity remain compatible.

## 3. Required artifacts

### G2-DEP-01

Retain or provide:

```text
compose.yaml
.env.example
.dockerignore
backend/Containerfile
backend/docker-entrypoint.sh
frontend/Containerfile
frontend/nginx.conf
scripts/compose-smoke.sh
Makefile
README.md
```

## 4. Topology and compatibility

### G2-DEP-02

```text
host/browser -> frontend:8080 -> api:8000 -> db:5432
```

- Exactly the `db`, `api`, and `frontend` services run long-term.
- Only `frontend` publishes `${APP_PORT:-8080}:8080`.
- `api` and `db` expose only Compose-network ports.
- The database named volume remains `postgres-data` so an ordinary generation 2
  startup sees generation 1 data.
- No admin, migration, test, cache, queue, or proxy sidecar is added.
- Disposable one-off verification containers are allowed.

Changing the Compose project name between generations changes the effective
volume namespace and must not be used during one evolution run.

## 5. Database service

### G2-DEP-03

Use an official image pinned to PostgreSQL major 17, interpolated name/user/
password, `postgres-data`, `pg_isready`, and a local production-like restart
policy. Never commit `.env`, bake credentials into images, or reset the data
directory during upgrade.

## 6. API service and migration

### G2-DEP-04

- Build from `backend/Containerfile` on a pinned Python 3.12 slim base.
- Install locked dependencies and run as non-root.
- Construct `DATABASE_URL` with hostname `db` only in the API environment.
- Listen on `0.0.0.0:8000` without a host port.
- Depend on healthy PostgreSQL and use bounded readiness retry.
- Health-check `/api/health` from inside the API container.
- The entrypoint runs `alembic upgrade head`, then execs Uvicorn.
- Migration failure stops startup with bounded diagnostics.

The migration must upgrade populated generation 1 data in place, be safe on
repeated startup, and also support applying the complete migration chain to an
empty database. It must not stamp the database current without applying schema
and data defaults.

## 7. Frontend service

### G2-DEP-05

- Multi-stage build with pinned Node 22, `npm ci`, and production Vite build.
- Unprivileged nginx runtime on container port 8080.
- Publish only `${APP_PORT:-8080}:8080`.
- Serve SPA fallback and proxy `/api/` to `http://api:8000/api/` while preserving
  methods, bodies, query strings, `If-Match`, statuses, and response bodies.
- Depend on healthy API and health-check the static root.
- Keep `node_modules`, unnecessary source, database credentials, internal
  hostname configuration, and DevLab artifacts out of the runtime image.

nginx must forward `If-Match` unchanged; it must not cache mutation or idea API
responses in a way that hides current versions.

## 8. Configuration and image hygiene

### G2-DEP-06

Retain `.env.example` with `APP_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and a
clearly local placeholder `POSTGRES_PASSWORD`. Ignore `.env`. Never pass
`DATABASE_URL` or credentials into frontend builds.

Build contexts exclude `.git`, `.devlab`, `.env`, caches, coverage/test output,
`node_modules`, `dist`, virtual environments, and bytecode. Images contain no
real secrets, agent configuration, or DevLab session artifacts.

## 9. Persistence and lifecycle

### G2-DEP-07

- `make compose-up` builds, starts, migrates, and waits for all three services.
- `make compose-down` preserves `postgres-data`.
- Restart retains generation 1 and generation 2 ideas.
- `make compose-clean` explicitly warns and removes the volume.
- Deployment verification always tears down containers after failure without
  deleting the volume.

## 10. Deployment commands

### G2-DEP-08

Retain:

```text
make compose-config
make compose-build
make compose-up
make compose-smoke
make compose-down
make compose-clean
make deployment-check
```

`make deployment-check` runs config validation, backend and migration tests,
frontend tests/build, image builds, healthy in-place startup, smoke testing, and
non-destructive shutdown. Missing host container/Compose tooling is an
unverified prerequisite, not something project commands install.

## 11. Upgrade and smoke-test contract

### G2-DEP-09: Pre-upgrade fixture

For evolution verification, the independent experiment creates three generation
1 ideas through the public API before installing generation 2. The project-owned
smoke test must tolerate unrelated pre-existing rows and manipulate only
uniquely titled fixtures it creates itself.

### G2-DEP-10: Public-boundary smoke

Against `http://127.0.0.1:${APP_PORT:-8080}`, verification must:

1. wait for three healthy services;
2. verify `/` serves current Idea Greenhouse HTML;
3. verify `/api/health` reports API/database `ok` through nginx;
4. retrieve known generation 1 fixture IDs when provided to the script and
   verify their original data plus `next_action = null`, `archived_at = null`,
   and `version = 1`;
5. create a uniquely titled idea with a next action;
6. read two copies of its current version;
7. update one copy successfully using `If-Match` and verify version increments by
   exactly one;
8. attempt a different update with the stale version and verify `409`, the stable
   error code, and unchanged stored data;
9. archive using the current version and verify active/archive counts;
10. restore using the new current version;
11. restart only `api`, wait for health, and verify both preserved generation 1
    data and the new idea still exist;
12. delete only the smoke test's new idea with its current version; and
13. print bounded service diagnostics on failure without credentials.

All API requests go through nginx. Do not run verification inside `api` in a way
that bypasses the public routing boundary.

### G2-DEP-11: Independent concurrent-writer check

The project must also provide a PostgreSQL-backed integration test or script that
sends two mutations with the same expected version concurrently and proves that
exactly one succeeds while the other receives `409`. Sequential stale-write
coverage alone does not satisfy this requirement.

## 12. Failure behavior

### G2-DEP-12

Build, migration, health, preservation, conflict, and smoke failures return
nonzero. Timeout failures print Compose status and bounded logs. Diagnostics omit
passwords and complete database URLs. Frontend health alone is not deployment
success.

If migration fails, leave the existing volume available for diagnosis and
recovery; do not automatically delete or reinitialize it.

## 13. Documentation

### G2-DEP-13

README covers prerequisites, `.env`, exact services, build/start/status/logs/
smoke/shutdown/restart/cleanup, public URLs, automatic migrations, generation 1
upgrade without volume deletion, rollback limitations, persistence, conflict
headers through nginx, and the destructive effect of `compose-clean`.

## 14. Verification expectations

### G2-DEP-14

Before claiming deployment success:

- Compose config validates;
- exactly three long-running services exist and only frontend publishes a port;
- images build from a clean checkout;
- empty installation and populated generation 1 upgrade both migrate;
- preserved records retain identity/content and receive documented defaults;
- all health checks pass;
- public-boundary smoke and concurrent-writer checks pass;
- API restart preserves data;
- ordinary shutdown preserves the volume;
- cleanup leaves no running project containers; and
- no secrets or runtime artifacts enter Git or images.

## 15. Non-goals

No Kubernetes, public ingress, TLS, registry publication, high availability,
replication, automated backups, external secrets management, online zero-downtime
multi-version rollout, or fourth long-running service is required.
