# Deployment Specification — Stock Trading Strategy Backtester (Web)

The backtester web application is a client-server system: a FastAPI backend and a React frontend served behind an nginx reverse proxy. Deployment means packaging both components into container images and running them together.

## Deployment Targets

### 1. Container image (multi-stage build)

A single container image bundles both the backend and the built frontend, with nginx serving static files and proxying API requests to uvicorn.

Generated artifacts:

```
Containerfile
.dockerignore
```

The multi-stage build:

1. **Frontend stage** — `node:22-slim` base, runs `npm ci && npm run build`, produces `dist/` static assets.
2. **Backend stage** — `python:3.12-slim` base, installs the Python package and uvicorn.
3. **Runtime stage** — `python:3.12-slim` base with nginx installed, copies the built frontend into nginx's document root, copies the backend Python package, and runs both nginx and uvicorn via a simple entrypoint script.

The runtime stage runs:
- nginx on port 80, serving `/` from the frontend build and proxying `/api/*` to `127.0.0.1:8000`.
- uvicorn on port 8000 (internal only), running the FastAPI application.

The entrypoint script starts both processes and exits if either one dies.

Image name convention: `backtester-web:<version>`.

### 2. Docker Compose stack (local and demo)

For local development with hot reload and for demo deployments.

Generated artifacts:

```
compose.yaml
compose.dev.yaml
.env.example
```

**`compose.yaml`** (production-like):

```yaml
services:
  app:
    build:
      context: .
      dockerfile: Containerfile
    image: ${IMAGE:-backtester-web:local}
    ports:
      - "${PORT:-8080}:80"
    restart: unless-stopped
```

Single service — the combined image handles both frontend and backend.

**`compose.dev.yaml`** (development override):

```yaml
services:
  backend:
    build:
      context: ./backend
      dockerfile: Containerfile.dev
    ports:
      - "8000:8000"
    volumes:
      - ./backend/src:/app/src:ro
    command: uv run uvicorn backtester.api.app:app --reload --host 0.0.0.0 --port 8000

  frontend:
    build:
      context: ./frontend
      dockerfile: Containerfile.dev
    ports:
      - "5173:5173"
    volumes:
      - ./frontend/src:/app/src:ro
    environment:
      - VITE_API_URL=http://localhost:8000/api
    command: npm run dev -- --host 0.0.0.0
```

Two services with source-mounted volumes for hot reload. No nginx in dev mode — the browser connects to the Vite dev server directly and the dev server proxies API requests.

**`Containerfile.dev`** files are minimal single-stage images for each component with dev dependencies installed.

### 3. Kubernetes manifests (verified with kind)

Plain YAML manifests for deploying to a Kubernetes cluster. No Helm or Kustomize.

Generated artifacts:

```
deploy/kubernetes/
  namespace.yaml
  deployment.yaml
  service.yaml
  configmap.yaml
  ingress.yaml
```

The deployment runs the combined container image. The service exposes port 80. The ingress routes external traffic to the service.

ConfigMap holds environment variables (none required for basic operation, but provides the extension point for `BACKTESTER_CACHE_DIR` or future configuration).

The namespace is `backtester` to isolate resources during kind testing.

## Deployment Environments

| Environment | How to run | Purpose |
|-------------|-----------|---------|
| Local dev (no containers) | `make dev` | Backend and frontend dev servers with hot reload. |
| Local dev (Compose) | `docker compose -f compose.yaml -f compose.dev.yaml up` | Containerised dev with hot reload via volume mounts. |
| Local production-like | `docker compose up --build` | Single combined container, production nginx config. |
| kind cluster | `make deploy-kind` | Kubernetes manifests verified in a local kind cluster. |

## Required Project Commands

```makefile
# Start backend and frontend dev servers (no containers)
make dev

# Run backend tests
make test-backend

# Run frontend type check and build
make test-frontend

# Run all tests
make test

# Lint backend (ruff + type check) and frontend (tsc --noEmit)
make lint

# Build the production container image
make image

# Start the production-like Compose stack
make deploy-local

# Run smoke tests against the running stack
make smoke-test

# Stop and remove the Compose stack
make undeploy-local

# Deploy to a kind cluster
make deploy-kind

# Run smoke tests against the kind cluster
make smoke-test-kind

# Tear down the kind cluster
make undeploy-kind

# Build all deployment artifacts and run verification
make deployment-verify

# Clean build artifacts
make clean
```

### Command details

**`make dev`** — starts `uv run uvicorn` (port 8000) and `npm run dev` (port 5173) concurrently. Stops both on Ctrl-C.

**`make test-backend`** — runs `cd backend && uv run pytest`.

**`make test-frontend`** — runs `cd frontend && npm run build` (TypeScript compilation catches type errors; the build output verifies the app compiles).

**`make test`** — runs `make test-backend` and `make test-frontend`.

**`make lint`** — runs `cd backend && uv run ruff check && uv run ty check` and `cd frontend && npx tsc --noEmit`.

**`make image`** — runs `podman build -t backtester-web:local -f Containerfile .` (or `docker build`). The Makefile uses `$(CONTAINER_ENGINE)` defaulting to `podman`, falling back to `docker`.

**`make deploy-local`** — runs `$(CONTAINER_ENGINE) compose up -d --build`. Waits for the health endpoint.

**`make smoke-test`** — runs `scripts/smoke-test.sh` which:
1. Waits up to 30 seconds for `GET /api/health` to return `{"status": "ok"}`.
2. Calls `GET /api/strategies` and verifies at least 5 strategies are returned.
3. Calls `POST /api/backtest` with a known symbol (AAPL) and a short date range, verifies the response contains metrics and trades.
4. Verifies the frontend is served: `GET /` returns HTML containing the application title.

**`make undeploy-local`** — runs `$(CONTAINER_ENGINE) compose down -v`.

**`make deploy-kind`** — runs `scripts/deploy-kind.sh` which:
1. Creates a kind cluster named `backtester-test` if it does not exist.
2. Builds the container image.
3. Loads the image into kind.
4. Applies the Kubernetes manifests.
5. Waits for the deployment rollout to complete.
6. Port-forwards the service to a local port.

**`make smoke-test-kind`** — runs the same `scripts/smoke-test.sh` against the port-forwarded service.

**`make undeploy-kind`** — runs `kind delete cluster --name backtester-test`.

**`make deployment-verify`** — runs the following checks in order:
1. `make test` — all tests pass.
2. `make lint` — no lint or type errors.
3. `make image` — container image builds successfully.
4. `make deploy-local` — Compose stack starts.
5. `make smoke-test` — smoke tests pass against the running stack.
6. `make undeploy-local` — stack tears down cleanly.
7. If `kind` is available: `make deploy-kind`, `make smoke-test-kind`, `make undeploy-kind`. If not: print warning and skip.

**`make clean`** — removes `dist/`, `build/`, `node_modules/`, `__pycache__`, container images tagged `backtester-web:local`.

## Verification Expectations

### Layer 1: Artifact validation (no external runtime)

- `uv build` (in `backend/`) succeeds and produces a wheel.
- `npm run build` (in `frontend/`) succeeds and produces `dist/` with `index.html` and JS bundles.
- `Containerfile` passes `hadolint` (if available).
- Kubernetes manifests pass `kubectl apply --dry-run=client -f deploy/kubernetes/`.
- If `kubeconform` is available: manifests pass schema validation.

### Layer 2: Local container deployment

- `make image` builds the combined container image.
- `make deploy-local` starts the stack and the health endpoint responds within 30 seconds.
- `make smoke-test` passes all checks (health, strategies, backtest, frontend serving).
- `make undeploy-local` removes all containers and volumes.

### Layer 3: Kubernetes (kind)

- `make deploy-kind` creates a cluster, loads the image, and the deployment reaches Ready state.
- `make smoke-test-kind` passes the same smoke tests via port-forward.
- `make undeploy-kind` deletes the cluster cleanly.

Checks in layers 2 and 3 require container tooling (Podman or Docker) and kind respectively. If the required tools are not installed, DevLab reports the checks as unverified and does not attempt to install them.

## nginx Configuration

The production nginx config (`nginx/default.conf`):

```nginx
server {
    listen 80;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/sweep/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }
}
```

The `/api/sweep/` location block has WebSocket upgrade headers and a long read timeout for sweep progress streams.

## Configuration

The application requires no mandatory configuration for basic operation. yfinance uses public Yahoo Finance data.

Optional environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `BACKTESTER_WORKERS` | `1` | Number of uvicorn worker processes. |
| `BACKTESTER_CACHE_DIR` | in-memory only | Persistent data cache directory. |
| `PORT` | `8080` | Host port mapped in Compose. |
| `IMAGE` | `backtester-web:local` | Container image name for Compose. |

## Versioning

The backend version is defined in `backend/pyproject.toml`. The frontend version is in `frontend/package.json`. Both should be kept in sync. The container image is tagged with the version from `pyproject.toml`.

## Project Layout with Deployment Artifacts

```
backtester-web/
├── pyproject.toml               # workspace-level metadata (optional)
├── Makefile
├── Containerfile                # multi-stage production build
├── .dockerignore
├── compose.yaml                 # production-like single-container
├── compose.dev.yaml             # dev override with hot reload
├── .env.example
├── nginx/
│   └── default.conf
├── scripts/
│   ├── entrypoint.sh            # starts nginx + uvicorn in the container
│   ├── smoke-test.sh
│   └── deploy-kind.sh
├── deploy/
│   └── kubernetes/
│       ├── namespace.yaml
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── configmap.yaml
│       └── ingress.yaml
├── backend/
│   ├── pyproject.toml
│   ├── Containerfile.dev        # dev-only backend image
│   ├── src/
│   │   └── backtester/
│   │       └── ...
│   └── tests/
│       └── ...
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── Containerfile.dev         # dev-only frontend image
    ├── index.html
    └── src/
        └── ...
```

## Production Scope

Production deployment is not automated by DevLab. The deployment spec enables:

- Building a production-ready container image.
- Running it locally or in kind for verification.
- Providing Kubernetes manifests as a starting point for real cluster deployment.

Actual production concerns — TLS termination, domain configuration, image registry, CI/CD pipeline, persistent caching, horizontal scaling, monitoring — are out of scope. The generated artifacts and documentation should make it straightforward for a human or CI system to deploy, but DevLab does not execute production deployments.

## Future Scope

- Helm chart for parameterised Kubernetes deployment.
- GitHub Actions CI workflow for automated image builds and tests.
- Multi-worker uvicorn configuration with shared data cache (Redis or filesystem).
- Rate limiting on the API to prevent abuse of yfinance requests.
- User authentication and saved backtests (would require a database).
