# Idea Greenhouse — System Specification

## Purpose

Idea Greenhouse is a small single-user web application for nurturing rough ideas
into actionable experiments. Each idea moves through three stages:

- `seed` — a newly captured thought;
- `sprout` — an idea currently being explored; and
- `bloom` — an idea that has produced a useful outcome.

The application is intentionally compact, but it must be a real persistent
three-tier system: a PostgreSQL database, a REST backend API, and a Vite/React
browser frontend. It should demonstrate reliable CRUD behavior, validation,
filtering, persistence across backend restarts, accessible UI behavior, and
cross-component testing without adding authentication, collaboration, or other
product breadth.

## Users and scope

The first version has one implicit local user. There are no accounts, login,
permissions, sharing, or multi-tenant behavior.

The user can:

- capture an idea with a title and optional notes;
- assign or change its stage;
- record one optional next action;
- browse all ideas or filter them by stage;
- edit an idea;
- delete an idea after confirmation; and
- see summary counts for each stage.

## Technology constraints

### Backend

- Python 3.12 or newer.
- FastAPI served by Uvicorn.
- SQLAlchemy 2.x for database access.
- Alembic for schema migrations.
- PostgreSQL as the only supported application database.
- Pydantic models for request and response validation.
- `pytest` for backend tests.
- Dependencies and commands are project-owned and reproducible; do not depend
  on packages inherited from DevLab or an agent environment.

### Frontend

- TypeScript.
- React with Vite.
- Use the browser `fetch` API for HTTP requests; a state-management or API-client
  framework is unnecessary for this scope.
- Use semantic HTML and ordinary CSS. A component library is not required.
- Frontend tests may use Vitest and React Testing Library.

### Repository layout

Use this top-level layout unless an equally clear equivalent is justified in the
design plan:

```text
backend/
  src/idea_greenhouse/
  tests/
  alembic/
  alembic.ini
  pyproject.toml
frontend/
  src/
  package.json
  package-lock.json
compose.yaml
Makefile
README.md
```

## Domain model

An idea has these fields:

| Field | Type | Rules |
|---|---|---|
| `id` | integer | Database-generated positive identifier. |
| `title` | string | Required after trimming; 1–120 characters. |
| `notes` | string or null | Optional; at most 2,000 characters. Empty or blank input is stored as `null`. |
| `stage` | enum string | Exactly `seed`, `sprout`, or `bloom`; defaults to `seed`. |
| `next_action` | string or null | Optional; at most 240 characters. Empty or blank input is stored as `null`. |
| `created_at` | timestamp | Server-generated UTC timestamp. |
| `updated_at` | timestamp | Server-generated UTC timestamp, changed on every successful update. |

Stage changes are deliberately unrestricted: an idea may move forward or
backward between any stages. Ordering in list results is `updated_at` descending,
then `id` descending for deterministic ties.

## REST API

All application endpoints are under `/api`. All success and error bodies are
JSON except responses with status `204`. JSON response content type must be
`application/json`.

### Health

#### `GET /api/health`

Checks both the API process and database connectivity.

Successful response: `200 OK`

```json
{
  "status": "ok",
  "database": "ok"
}
```

If the API is running but cannot query PostgreSQL, return `503 Service
Unavailable`:

```json
{
  "status": "unavailable",
  "database": "unavailable"
}
```

### Create an idea

#### `POST /api/ideas`

Request:

```json
{
  "title": "Try a walking retrospective",
  "notes": "Discuss the last iteration away from screens.",
  "stage": "seed",
  "next_action": "Ask the team on Friday"
}
```

Only `title` is required. Omitted `stage` defaults to `seed`. Successful response:
`201 Created` with the complete stored idea.

### List and filter ideas

#### `GET /api/ideas`

Returns all ideas:

```json
{
  "ideas": [
    {
      "id": 1,
      "title": "Try a walking retrospective",
      "notes": "Discuss the last iteration away from screens.",
      "stage": "seed",
      "next_action": "Ask the team on Friday",
      "created_at": "2026-08-22T10:15:00Z",
      "updated_at": "2026-08-22T10:15:00Z"
    }
  ],
  "counts": {
    "seed": 1,
    "sprout": 0,
    "bloom": 0,
    "total": 1
  }
}
```

Optional query parameter `stage=seed|sprout|bloom` filters the `ideas` array.
The `counts` object always summarizes all stored ideas, not only the filtered
array. An unknown stage returns `422 Unprocessable Entity`.

### Get one idea

#### `GET /api/ideas/{idea_id}`

Returns `200 OK` with the complete idea, or `404 Not Found` when the ID does not
exist.

### Update an idea

#### `PATCH /api/ideas/{idea_id}`

Accepts any non-empty subset of `title`, `notes`, `stage`, and `next_action`.
Validation and normalization are the same as for creation. An empty JSON object
returns `422 Unprocessable Entity`. Successful response: `200 OK` with the
complete updated idea. A missing ID returns `404 Not Found`.

### Delete an idea

#### `DELETE /api/ideas/{idea_id}`

Deletes the idea and returns `204 No Content` with an empty body. A missing ID
returns `404 Not Found`.

### Error contract

Application errors use this stable top-level shape:

```json
{
  "error": {
    "code": "idea_not_found",
    "message": "Idea 42 was not found",
    "fields": null
  }
}
```

Validation errors use code `validation_error` and may put field-specific
messages in `fields`, keyed by request field. Malformed JSON, invalid field
types, invalid stages, blank titles, overlong values, and empty patch bodies must
produce a `4xx` response without an unhandled server exception. Unexpected
errors must not expose tracebacks or database credentials to clients.

## Frontend behavior

The frontend is a single-page application called **Idea Greenhouse**.

### Main view

The main view contains:

- a heading with the application name;
- a summary showing seed, sprout, bloom, and total counts;
- filter controls for All, Seeds, Sprouts, and Blooms;
- an idea creation form;
- a list of idea cards; and
- an empty-state message when the active filter has no results.

Each idea card shows its title, stage, optional notes, optional next action, and
last-updated time. It provides controls to edit, change stage, and delete.

### Creation and editing

- Title is required and validated in the browser before submission.
- The form provides title, notes, stage, and next-action fields.
- Server validation errors are displayed beside the relevant field when
  possible, with a general error region for other failures.
- Successful creation inserts the returned idea into the correct ordering and
  updates counts without a full page reload.
- Editing uses the same validation rules and updates the displayed card from the
  server response.

### Stage changes

The user can change an idea directly between seed, sprout, and bloom. The UI
sends `PATCH /api/ideas/{id}` and does not optimistically show the new stage
until the API succeeds. Counts and the active filtered list update afterward.

### Deletion

Deletion requires an explicit confirmation. On success, the card disappears and
counts update. On failure, the idea remains visible and an error is shown.

### Loading and failure states

- Show a loading state during the initial request.
- Disable only the control whose mutation is currently in flight.
- Prevent duplicate submissions.
- If initial loading fails, display a visible error and a Retry control.
- Preserve typed form content after a failed create or update request.
- Do not silently ignore failed HTTP responses or invalid response bodies.

### Accessibility

- All form fields have persistent accessible labels.
- Controls are reachable and operable by keyboard.
- Stage filters expose their selected state.
- Mutation and validation messages use an appropriate live region or alert
  role without repeatedly announcing unrelated content.
- Delete confirmation identifies the idea being deleted.
- Color is not the only indication of stage or error state.

## Browser-to-API integration

Browser code must call same-origin relative `/api/...` URLs. Development Vite
configuration proxies `/api` to a backend target read from `API_BASE_URL`, with
`http://127.0.0.1:8000` as the documented local default. Production routing is
owned by the deployment specification. Do not require permissive CORS for the
supported development or deployed paths.

## Persistence and database behavior

- Store ideas in PostgreSQL, not process memory or browser storage.
- Provide an Alembic migration that creates the required schema from an empty
  database.
- The API must not create or mutate schema implicitly at import or request time.
- Database transactions must roll back after failed mutations.
- Restarting the API while retaining the database must preserve ideas.
- Use parameterized ORM/database operations; do not construct SQL from request
  strings.
- Keep database credentials in environment variables and out of source,
  generated frontend assets, logs, and API responses.

## Configuration

The backend reads:

- `DATABASE_URL` — required PostgreSQL SQLAlchemy connection URL;
- `HOST` — optional bind host, default `127.0.0.1` outside containers; and
- `PORT` — optional port, default `8000`.

Fail startup with a concise actionable message when `DATABASE_URL` is missing or
invalid. Do not log its password.

The Vite development server reads `API_BASE_URL` only in its Node-side config;
it must not expose the database URL or other server secrets to browser code.

## Project-owned commands

Provide a root `Makefile` with these commands:

```text
make test-backend        Run backend unit and API tests.
make test-frontend       Run frontend component tests and a production build.
make test                Run backend and frontend test suites.
make dev-backend         Run the backend against an operator-supplied DATABASE_URL.
make dev-frontend        Run Vite with an operator-selectable API_BASE_URL.
make compose-up          Build and start the three-container stack.
make compose-smoke       Exercise the running frontend/API/database boundary.
make compose-down        Stop the stack without deleting persisted database data.
make compose-clean       Stop the stack and explicitly delete its local database volume.
make check               Run unit/component tests, builds, and Compose integration verification.
```

Commands must use project-owned environments and lockfiles. Missing PostgreSQL,
Node, container, or Compose tooling is an unverified operator/CI prerequisite;
the application and DevLab must not install missing host tools.

## Verification requirements

### Backend tests

Backend tests must cover:

- create defaults and normalization;
- create validation failures;
- list ordering, filtering, and global counts;
- get, update, stage change, and delete;
- missing IDs;
- malformed input and the stable error shape;
- health behavior with an available and unavailable database; and
- transaction rollback after a failed mutation.

Database integration tests must use PostgreSQL, not SQLite, because database
behavior is part of the product contract.

### Frontend tests

Frontend tests must cover:

- initial loading, populated, empty, and failure states;
- create validation and successful creation;
- filtering and count display;
- editing and stage changes;
- deletion confirmation; and
- failed mutations preserving visible data and typed input.

Mocked API responses are acceptable for component tests, but they do not replace
the Compose integration test.

### Cross-boundary verification

`make compose-smoke` must use the deployed frontend origin and exercise the real
frontend reverse proxy, API, and PostgreSQL database. It must at least:

1. wait for all services to become healthy;
2. load the frontend root and confirm it serves the Idea Greenhouse application;
3. call `GET /api/health` through the frontend origin;
4. create an idea through the proxied API;
5. list it and verify counts;
6. change its stage and verify the updated counts;
7. restart only the API container and verify the idea still exists;
8. delete the idea; and
9. verify it no longer appears.

An optional browser automation test may additionally exercise the visible UI,
but the HTTP-level Compose smoke test above is required and must not be replaced
by separate component checks.

## Documentation

The README must document:

- prerequisites without installation side effects;
- local backend and frontend development;
- database configuration;
- all project-owned validation commands;
- three-container Compose startup, health inspection, smoke testing, shutdown,
  and explicit data deletion;
- the REST endpoint summary; and
- the distinction between ordinary shutdown, which preserves data, and cleanup,
  which deletes the database volume.

## Non-goals

- Authentication or multiple users.
- Sharing, comments, attachments, tags, search, or notifications.
- Drag-and-drop behavior.
- Offline support or client-side persistence.
- WebSockets or background jobs.
- Public cloud deployment, Kubernetes, or production secrets management.
- Multiple database engines.
- Visual snapshot or pixel-perfect design requirements.

Keep the first version focused on a polished, reliable vertical slice rather
than adding more idea-management features.
