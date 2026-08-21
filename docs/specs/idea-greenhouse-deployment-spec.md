# Idea Greenhouse — Deployment Specification

## Purpose

Package and run Idea Greenhouse as a local, production-like Docker Compose stack
containing exactly three long-running service containers:

1. `db` — PostgreSQL;
2. `api` — the FastAPI backend; and
3. `frontend` — nginx serving the built Vite/React application and reverse
   proxying `/api` to the backend.

The deployment must prove that browser/API routing, backend/database access,
migrations, persistence, health checks, startup ordering, and clean shutdown
work together. It is suitable for local evaluation and demos, not a claim of
internet-facing production readiness.

## Required artifacts

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

Equivalent script names are acceptable only when the documented Make targets
remain exactly as specified.

## Compose topology

`compose.yaml` must define exactly these application services:

```text
browser/host
    |
    | http://127.0.0.1:${APP_PORT}
    v
frontend (nginx :8080)
    |
    | /api/* -> http://api:8000/api/*
    v
api (FastAPI/Uvicorn :8000)
    |
    | PostgreSQL protocol
    v
db (PostgreSQL :5432)
```

No database administration UI, migration sidecar, test runner, cache, queue, or
other long-running service may be added. One-off `docker compose run` processes
used by explicit verification commands do not count as deployed services, but
ordinary startup must require only the three services above.

Only `frontend` publishes a host port. `api` and `db` use the Compose network and
must not publish host ports in the production-like Compose file.

## Service requirements

### `db`

- Use an official pinned PostgreSQL image with a major version of 17.
- Configure database name, user, and password from Compose interpolation.
- Store database data in one named volume, `postgres-data`.
- Define a health check using `pg_isready` for the configured database and user.
- Do not bake credentials into an image or commit a real `.env` file.
- Use a restart policy appropriate for a local production-like stack, such as
  `unless-stopped`.

### `api`

- Build from `backend/Containerfile`.
- Use a pinned Python 3.12 slim base image.
- Install backend dependencies reproducibly from the project lockfile.
- Run as a non-root user in the final image.
- Set `DATABASE_URL` from the Compose database variables using service hostname
  `db`; do not use `localhost` for container-to-container access.
- Listen on `0.0.0.0:8000` inside the container.
- Define an API health check against `http://127.0.0.1:8000/api/health` using a
  tool already present in the image or Python's standard library.
- Depend on `db` becoming healthy before startup.
- Do not publish port 8000 to the host.

The API entrypoint must run `alembic upgrade head` before starting Uvicorn. It
must use an exec-style final process so Uvicorn receives termination signals.
Migration failure must stop the container rather than starting against an
unknown schema. Running the entrypoint repeatedly against an up-to-date database
must be safe.

### `frontend`

- Build from `frontend/Containerfile`.
- Use a pinned Node 22 image for the build stage.
- Install dependencies with `npm ci` and run the production Vite build.
- Use an unprivileged nginx image or configure nginx to run without root in the
  final stage.
- Copy only built static assets and required nginx configuration into the final
  image; do not include `node_modules` or frontend source unnecessarily.
- Listen on container port 8080.
- Publish `${APP_PORT:-8080}:8080` to the host.
- Serve the SPA with `index.html` fallback for client-side routes.
- Reverse proxy `/api/` to `http://api:8000/api/`, preserving the method, body,
  query string, and response status.
- Define a health check that verifies the static root is served.
- Depend on `api` becoming healthy before startup.

The browser must use same-origin `/api/...` paths. Do not inject the internal
Compose hostname `api`, database credentials, or a host-specific API origin into
the generated JavaScript bundle.

## Image and build requirements

- Container build contexts must exclude `.git`, `.devlab`, local environment
  files, caches, test output, coverage output, `node_modules`, frontend `dist`,
  Python virtual environments, and bytecode.
- Use explicit working directories.
- Use exec-form `ENTRYPOINT` or `CMD` where applicable.
- Do not install container engines, Compose, or host tooling from project
  commands.
- Do not use `latest` image tags.
- Keep build-only tools and source out of final runtime stages where practical.
- Images must not contain real passwords, `.env`, agent configuration, or DevLab
  logs/session artifacts.

## Configuration and secrets

Commit `.env.example` containing non-secret local defaults:

```dotenv
APP_PORT=8080
POSTGRES_DB=idea_greenhouse
POSTGRES_USER=idea_greenhouse
POSTGRES_PASSWORD=change-me-for-nonlocal-use
```

The README must instruct operators to copy this to an ignored `.env` file and
change the password outside disposable local use. Commit a root `.gitignore`
entry for `.env` while keeping `.env.example` tracked.

Compose variable expansion must fail clearly when a required value has no
default. The effective database URL must be constructed only in the API
container environment. It must not appear in frontend build arguments or
browser-visible configuration.

## Health and readiness

Health is layered:

- `db` is healthy only when PostgreSQL accepts connections for the configured
  database/user.
- `api` is healthy only when `/api/health` can query PostgreSQL successfully.
- `frontend` is healthy only when nginx serves the built application.
- `make compose-smoke` verifies the public frontend origin plus the complete
  proxied API/database behavior.

Use Compose health-conditioned dependencies where supported, but do not treat
startup ordering as a substitute for retry-safe application startup. The API
entrypoint should tolerate PostgreSQL's normal short readiness delay with a
bounded retry and an actionable failure message.

## Persistence contract

- `make compose-down` stops and removes service containers and the default
  network but preserves `postgres-data`.
- Starting the stack again with `make compose-up` must retain previously created
  ideas.
- `make compose-clean` is the explicit destructive local cleanup command. It
  removes the stack and its named database volume after printing that persisted
  data will be deleted.
- The smoke test may create and delete its own uniquely named idea, but must not
  delete the database volume or unrelated user data.

## Required Make targets

The root `Makefile` must expose:

### `make compose-config`

Run `docker compose config` (or the selected compatible Compose command) to
validate interpolation and syntax without starting services.

### `make compose-build`

Build the `api` and `frontend` images.

### `make compose-up`

Start the stack in detached mode with builds enabled, then wait for all three
services to report healthy. Exit nonzero with service status and recent logs if
the health deadline expires.

### `make compose-smoke`

Run `scripts/compose-smoke.sh` against
`http://127.0.0.1:${APP_PORT:-8080}`. It must exercise the public frontend origin
and the real database as defined below.

### `make compose-down`

Stop the stack without passing `--volumes` and without deleting persisted data.

### `make compose-clean`

Stop the stack and remove its named volume. This is the only ordinary project
command that deletes the local database volume.

### `make deployment-check`

Run, in order:

1. `make compose-config`;
2. backend tests;
3. frontend tests and production build;
4. `make compose-build`;
5. `make compose-up`;
6. `make compose-smoke`; and
7. `make compose-down` in a cleanup trap, including after smoke-test failure.

It must preserve the database volume. Missing container/Compose tooling is an
unverified operator or CI prerequisite; DevLab and project scripts must report
it and must not install it.

## Compose smoke-test contract

The smoke test must fail on any unexpected status or response body. It must:

1. choose a unique title containing the current process ID or timestamp;
2. request `/` from the frontend host port and verify that Idea Greenhouse HTML
   is served;
3. request `/api/health` through the same frontend origin and verify both API and
   database report `ok`;
4. create a seed through `POST /api/ideas` and retain its returned integer ID;
5. list ideas and verify the created item plus incremented seed and total counts;
6. patch the item to `sprout` with a next action and verify the response;
7. list with `?stage=sprout` and verify the item plus global counts;
8. restart only the `api` service, wait for it to become healthy, and verify the
   item still exists through the frontend proxy;
9. delete the item and verify a later get returns `404`; and
10. report concise frontend, API, and database logs on failure without printing
    credentials.

Use tools available on the operator host or a disposable one-off verification
container. If a one-off container is used, it must join the appropriate network
without becoming a fourth long-running service. Do not execute the smoke test
inside the API container in a way that bypasses nginx and the public routing
boundary.

## Failure behavior and diagnostics

- Build, migration, health, and smoke-test failures must return a nonzero status.
- Cleanup traps must stop processes/containers started by verification without
  deleting the persistent volume.
- `compose-up` and `deployment-check` failures should print `docker compose ps`
  and bounded recent logs for unhealthy services.
- Diagnostics must redact or omit the PostgreSQL password and complete
  `DATABASE_URL`.
- A frontend health success combined with an API health failure is still a
  deployment failure.

## DevLab profile expectations

Planning should create or reuse profiles that make validation proportional to
the claimed boundary:

- backend implementation tasks run backend unit and PostgreSQL integration
  tests;
- frontend tasks run component tests and a production build; and
- the milestone that claims a working deployed system includes
  `make deployment-check` through an aggregate deployment/integration profile or
  explicit task validation.

Component tests and successful image builds do not by themselves verify the
frontend/nginx/API/PostgreSQL path. Missing Docker/Compose support must be
recorded as an unverified prerequisite rather than silently treated as a pass.

## Verification expectations

Before the deployment milestone can be considered verified:

- `docker compose config` succeeds;
- both images build from a clean checkout;
- exactly three long-running services are present;
- only the frontend publishes a host port;
- all service health checks pass;
- migrations succeed from an empty database and are safe on restart;
- the full smoke-test contract passes through the frontend origin;
- API restart preserves stored data;
- ordinary shutdown preserves the named volume;
- teardown leaves no running project containers; and
- the repository remains free of credentials and generated runtime artifacts.

## Documentation requirements

The README must document:

- Docker Engine with Compose v2, or a demonstrably compatible engine/Compose
  implementation, as an operator-installed prerequisite;
- `.env` creation from `.env.example`;
- the exact three services and their responsibilities;
- build, startup, status, logs, smoke-test, shutdown, restart, and cleanup
  commands;
- the public URL and health URL;
- migration behavior;
- persistence and backup limitations; and
- the destructive effect of `make compose-clean`.

## Non-goals

- Kubernetes, Helm, cloud deployment, or public ingress.
- TLS termination or public DNS.
- High availability, replication, failover, or automated backups.
- External secrets managers.
- Horizontal scaling or multiple API replicas.
- A fourth reverse-proxy, migration, administration, or observability service.
- Automated publication to an image registry.

Do not imply production readiness beyond a local production-like Compose stack.
