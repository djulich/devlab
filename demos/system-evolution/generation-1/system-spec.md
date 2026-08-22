# Idea Greenhouse — Generation 1 System Specification

## 1. Product purpose

Idea Greenhouse is a single-user web application for developing rough ideas.
Each idea moves through three stages:

- `seed` — newly captured;
- `sprout` — actively explored; and
- `bloom` — produced a useful outcome.

The product is a persistent three-tier system with PostgreSQL, a REST API, and a
React browser interface. Generation 1 deliberately stays small while requiring
real behavior across all three tiers.

## 2. Scope

The implicit local user can create, view, filter, edit, change the stage of, and
delete ideas. The application displays counts for each stage.

There are no accounts, permissions, collaboration, tags, attachments, search,
notifications, background jobs, WebSockets, or offline support.

## 3. Required technologies

- Backend: Python 3.12+, FastAPI, Uvicorn, SQLAlchemy 2.x, Alembic, Pydantic,
  PostgreSQL, and pytest.
- Frontend: TypeScript, React, Vite, browser `fetch`, semantic HTML, and CSS.
- Deployment: the separate generation 1 deployment specification.
- Dependencies must be project-owned and reproducibly locked. The product must
  not rely on packages inherited from DevLab or an agent environment.

Use a clear `backend/` and `frontend/` repository layout, a root `Makefile`, and
a root `README.md`.

## 4. Domain model

### G1-DATA-01: Idea fields

An idea contains:

| Field | Type | Contract |
|---|---|---|
| `id` | integer | Database-generated positive ID. |
| `title` | string | Trimmed, required, 1–120 characters. |
| `notes` | string or null | Optional, at most 2,000 characters; blank becomes null. |
| `stage` | string enum | `seed`, `sprout`, or `bloom`; default `seed`. |
| `created_at` | timestamp | Server-generated UTC timestamp. |
| `updated_at` | timestamp | Server-generated UTC timestamp changed on update. |

Stage transitions are unrestricted. List ordering is `updated_at` descending and
then `id` descending.

### G1-DATA-02: PostgreSQL persistence

- PostgreSQL is the only supported application database.
- Provide an Alembic migration that creates the schema from an empty database.
- The API must not create or mutate schema implicitly during import or request
  handling.
- Database transactions roll back after failed mutations.
- Restarting the API while retaining PostgreSQL data preserves ideas.
- Credentials come from environment variables and never appear in browser
  assets, API errors, or logs.

## 5. REST API contract

All endpoints are under `/api`. Success and error responses are JSON except a
successful delete, which has an empty body.

### G1-API-01: Health

`GET /api/health` queries PostgreSQL. On success return `200`:

```json
{"status":"ok","database":"ok"}
```

If the API process is available but PostgreSQL cannot be queried, return `503`:

```json
{"status":"unavailable","database":"unavailable"}
```

### G1-API-02: Create

`POST /api/ideas` accepts `title`, optional `notes`, and optional `stage`. Omitted
stage defaults to `seed`. Return `201` with the complete stored idea.

### G1-API-03: List and filter

`GET /api/ideas` returns:

```json
{
  "ideas": [],
  "counts": {"seed": 0, "sprout": 0, "bloom": 0, "total": 0}
}
```

Optional `stage=seed|sprout|bloom` filters `ideas`. Counts always summarize all
stored ideas, not only the filtered array. Unknown stages return `422`.

### G1-API-04: Read one

`GET /api/ideas/{idea_id}` returns the complete idea or `404`.

### G1-API-05: Update

`PATCH /api/ideas/{idea_id}` accepts a non-empty subset of `title`, `notes`, and
`stage`. It applies the same normalization and validation as create, updates
`updated_at`, and returns the complete idea. Empty objects return `422`; missing
IDs return `404`.

### G1-API-06: Delete

`DELETE /api/ideas/{idea_id}` returns `204` with an empty body. Missing IDs
return `404`.

### G1-API-07: Errors

Application errors have this top-level shape:

```json
{
  "error": {
    "code": "idea_not_found",
    "message": "Idea 42 was not found",
    "fields": null
  }
}
```

Validation uses code `validation_error` and may put messages in `fields`, keyed
by request field. Malformed JSON, wrong types, invalid stages, blank titles,
overlong values, and empty patches return `4xx` without leaking tracebacks or
credentials.

## 6. Frontend contract

### G1-UI-01: Main view

The single-page application is titled **Idea Greenhouse** and shows:

- seed, sprout, bloom, and total counts;
- All, Seeds, Sprouts, and Blooms filters;
- a creation form; and
- ordered idea cards or a filter-specific empty state.

Each card displays title, stage, optional notes, and last-updated time, with
controls to edit, change stage, and delete.

### G1-UI-02: Create and edit

- Forms provide title, notes, and stage fields.
- The browser rejects blank titles before making a request.
- Server field errors appear beside the relevant field where possible.
- Successful mutations update cards and counts without a full-page reload.
- Failed mutations preserve typed form content and existing visible data.
- Prevent duplicate submissions and disable only the active mutation control.

### G1-UI-03: Stage and filter behavior

The user can move an idea directly between any stages. Do not display a new
stage optimistically before the API succeeds. After success, counts and the
active filtered list update.

### G1-UI-04: Delete behavior

Deletion requires confirmation identifying the idea. On failure the card
remains visible and an error is shown.

### G1-UI-05: Loading and errors

Show initial loading, empty, and failure states. Initial failure includes a
Retry control. Do not silently ignore failed HTTP responses or invalid bodies.

### G1-UI-06: Accessibility

- Persistent accessible labels for fields.
- Keyboard-operable controls.
- Selected state exposed by stage filters.
- Appropriate alert/live-region behavior for errors and mutation status.
- Text or semantics, not color alone, identify stage and errors.

## 7. Browser/API integration

### G1-INT-01: Same-origin routing

Browser code calls relative `/api/...` URLs. During development, Vite proxies
`/api` to `API_BASE_URL`, defaulting to `http://127.0.0.1:8000`. Production
routing is defined by the deployment specification. Supported paths must not
require permissive CORS.

## 8. Configuration

### G1-CFG-01: Backend

- `DATABASE_URL` is required.
- `HOST` defaults to `127.0.0.1` outside containers.
- `PORT` defaults to `8000`.
- Missing or invalid database configuration fails startup with an actionable
  message that does not print the password.

### G1-CFG-02: Frontend development

`API_BASE_URL` is read only by Vite's Node-side configuration. Database URLs and
server secrets must not become browser-visible environment variables.

## 9. Project-owned commands

### G1-CMD-01: Root Make targets

Provide:

```text
make test-backend
make test-frontend
make test
make dev-backend
make dev-frontend
make compose-up
make compose-smoke
make compose-down
make compose-clean
make check
```

`make check` runs unit/component tests, builds, and the Compose integration
verification required by the deployment specification. Missing host tools are
reported as unverified prerequisites and are not installed.

## 10. Verification

### G1-TEST-01: Backend

Project-owned tests cover create defaults/normalization, validation, list
ordering/filter/counts, read, update, stage change, delete, missing IDs, stable
errors, database-aware health, and transaction rollback. Database integration
tests use PostgreSQL rather than SQLite.

### G1-TEST-02: Frontend

Project-owned component tests cover loading/populated/empty/failure states,
creation validation and success, filtering/counts, editing, stage changes,
deletion confirmation, and failed-mutation preservation. Mocked API responses do
not replace deployment integration verification.

### G1-TEST-03: Cross-boundary

`make compose-smoke` must cross the public frontend origin, reverse proxy, API,
and real PostgreSQL database. It creates, lists, changes, persists across an API
restart, and deletes an idea as detailed in the deployment specification.

## 11. Documentation

### G1-DOC-01: README

Document prerequisites, local backend/frontend development, database
configuration, validation, REST endpoints, Compose startup/status/logs/smoke
test/shutdown, and the difference between preserving and deleting database data.

## 12. Non-goals

Authentication, multiple users, archiving, optimistic concurrency, next actions,
public cloud deployment, Kubernetes, production secrets management, multiple
database engines, and visual snapshot requirements are outside generation 1.
