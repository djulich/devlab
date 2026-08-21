# Idea Greenhouse — Generation 1 Deployment Specification

## 1. Deployment goal

Run a local production-like Compose stack with exactly three long-running
services:

1. `db` — PostgreSQL 17;
2. `api` — FastAPI/Uvicorn; and
3. `frontend` — nginx serving the built React app and proxying `/api`.

This demonstrates local deployment behavior, not internet-facing production
readiness.

## 2. Required artifacts

### G1-DEP-01

Provide:

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

## 3. Topology

### G1-DEP-02: Service boundary

```text
host/browser -> frontend:8080 -> api:8000 -> db:5432
```

Only `frontend` publishes a host port, `${APP_PORT:-8080}:8080`. `api` and `db`
must not publish host ports. No admin UI, migration sidecar, cache, queue, or
other long-running service may be added. Disposable one-off verification
containers are allowed but are not part of ordinary startup.

## 4. Database service

### G1-DEP-03

- Use an official PostgreSQL image pinned to major version 17, never `latest`.
- Read database name, user, and password through Compose interpolation.
- Store data in the named volume `postgres-data`.
- Use `pg_isready` health checking for the configured database/user.
- Use `unless-stopped` or an equivalent local production-like restart policy.
- Do not commit a real `.env` file or bake credentials into images.

## 5. API service

### G1-DEP-04

- Build from `backend/Containerfile` using a pinned Python 3.12 slim base.
- Install locked project dependencies reproducibly.
- Run as non-root in the final image.
- Construct `DATABASE_URL` in the container environment using hostname `db`.
- Listen on `0.0.0.0:8000` without publishing that port.
- Depend on healthy `db` and tolerate its normal short readiness delay with a
  bounded retry.
- Health-check `http://127.0.0.1:8000/api/health` using an already available tool
  or Python's standard library.

The entrypoint runs `alembic upgrade head`, then execs Uvicorn so it receives
signals. Migration failure stops the container. Repeated startup against an
up-to-date database is safe.

## 6. Frontend service

### G1-DEP-05

- Multi-stage build from `frontend/Containerfile`.
- Pinned Node 22 build image; install with `npm ci`; run the production build.
- Unprivileged nginx runtime or an nginx configuration that runs without root.
- Final image contains built assets and nginx runtime configuration, not
  `node_modules` or unnecessary source.
- Listen on container port 8080 and publish `${APP_PORT:-8080}:8080`.
- Serve SPA routes with an `index.html` fallback.
- Proxy `/api/` to `http://api:8000/api/`, preserving methods, bodies, query
  strings, and statuses.
- Depend on healthy `api` and health-check the static root.

The browser bundle contains neither internal hostname `api` nor database
credentials. It uses same-origin `/api` paths.

## 7. Configuration

### G1-DEP-06

Commit `.env.example`:

```dotenv
APP_PORT=8080
POSTGRES_DB=idea_greenhouse
POSTGRES_USER=idea_greenhouse
POSTGRES_PASSWORD=change-me-for-nonlocal-use
```

Ignore `.env` while tracking `.env.example`. Documentation tells operators to
copy and adjust it. Never place `DATABASE_URL` in frontend build arguments.

## 8. Image hygiene

### G1-DEP-07

Build contexts exclude `.git`, `.devlab`, `.env`, caches, coverage, test output,
`node_modules`, `dist`, Python virtual environments, and bytecode. Images contain
no real secrets, agent configuration, or DevLab artifacts. Use explicit working
directories and exec-form runtime commands.

## 9. Persistence and lifecycle

### G1-DEP-08

- `make compose-up` builds, starts, and waits for all services to become healthy.
- `make compose-down` removes containers/network without deleting the volume.
- A later `make compose-up` retains ideas.
- `make compose-clean` clearly warns and then removes the named database volume.
- Verification cleanup never deletes the database volume.

## 10. Deployment commands

### G1-DEP-09

Provide:

```text
make compose-config
make compose-build
make compose-up
make compose-smoke
make compose-down
make compose-clean
make deployment-check
```

`make deployment-check` runs Compose config validation, backend tests, frontend
tests/build, image builds, healthy startup, smoke testing, and non-destructive
shutdown. A cleanup trap stops containers after failures while preserving data.
Missing container/Compose tools are unverified prerequisites, not packages to
install.

## 11. Smoke-test contract

### G1-DEP-10

Against `http://127.0.0.1:${APP_PORT:-8080}`, the project-owned smoke test:

1. waits for the three healthy services;
2. verifies `/` serves Idea Greenhouse HTML;
3. verifies `/api/health` reports API and database `ok` through nginx;
4. creates a uniquely titled seed and stores its returned integer ID;
5. lists it and verifies seed/total counts;
6. patches it to `sprout` and verifies filtered results and global counts;
7. restarts only `api`, waits for health, and verifies the idea still exists;
8. deletes it and verifies a later read returns `404`; and
9. prints bounded service diagnostics on failure without credentials.

Do not run the smoke test inside `api` in a way that bypasses nginx. A disposable
one-off verifier may join the Compose network but must not remain running.

## 12. Failure behavior

### G1-DEP-11

Build, migration, health, and smoke failures return nonzero. Timeout failures
print service status and bounded logs. Logs and errors omit passwords and the
complete database URL. Frontend health with API/database failure is not success.

## 13. Documentation

### G1-DEP-12

README instructions cover prerequisites, `.env`, service responsibilities,
build/start/status/logs/smoke/shutdown/restart/cleanup, public and health URLs,
migrations, persistence, and the destructive effect of `compose-clean`.

## 14. Non-goals

No Kubernetes, public ingress, TLS, registry publication, high availability,
replication, automated backups, external secrets manager, or fourth long-running
service is required.
