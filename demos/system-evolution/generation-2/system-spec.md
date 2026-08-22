# Idea Greenhouse — Generation 2 System Specification

## 1. Product purpose

Idea Greenhouse is a single-user web application for developing rough ideas.
Ideas move through `seed`, `sprout`, and `bloom` stages and are stored in
PostgreSQL behind a REST API and React browser interface.

Generation 2 must upgrade an existing generation 1 installation without losing
data. It adds:

- an optional next action;
- reversible archiving instead of relying only on deletion; and
- optimistic concurrency so stale browser state cannot silently overwrite a
  newer change.

This file is the complete desired-state system specification. The change summary
does not replace any later requirement.

## 2. Changes from generation 1

- Existing ideas gain `next_action = null`, `archived_at = null`, and
  `version = 1` during migration.
- Updates, archive, restore, and delete require the client's expected version.
- Stale mutations return `409 Conflict` and the current stored idea.
- Active lists exclude archived ideas by default; explicit filtering can show
  archived or all ideas.
- The UI exposes archive/restore and visible conflict recovery.

## 3. Scope and technology

The implicit local user can create, view, filter, edit, change stage, archive,
restore, and permanently delete ideas. The application displays stage and
archive counts.

Required technologies remain:

- Python 3.12+, FastAPI, Uvicorn, SQLAlchemy 2.x, Alembic, Pydantic, PostgreSQL,
  and pytest;
- TypeScript, React, Vite, browser `fetch`, semantic HTML, and CSS; and
- the separate generation 2 deployment specification.

Dependencies are project-owned and reproducibly locked. There are no accounts,
permissions, collaboration, tags, attachments, search, notifications,
background jobs, WebSockets, offline support, or multiple database engines.

## 4. Domain model

### G2-DATA-01: Idea fields

| Field | Type | Contract |
|---|---|---|
| `id` | integer | Database-generated positive ID. |
| `title` | string | Trimmed, required, 1–120 characters. |
| `notes` | string or null | Optional, at most 2,000 characters; blank becomes null. |
| `stage` | string enum | `seed`, `sprout`, or `bloom`; default `seed`. |
| `next_action` | string or null | Optional, at most 240 characters; blank becomes null. |
| `archived_at` | timestamp or null | Server-generated UTC archive time; null while active. |
| `version` | integer | Starts at 1 and increments on each successful mutation. |
| `created_at` | timestamp | Server-generated UTC timestamp. |
| `updated_at` | timestamp | Server-generated UTC timestamp changed on every successful mutation. |

Stage transitions are unrestricted. Ordering is `updated_at` descending, then
`id` descending. Archive and restore are mutations: they update `updated_at` and
increment `version`. Restoring retains the idea's prior stage.

### G2-DATA-02: PostgreSQL persistence and migration

- PostgreSQL remains the only supported application database.
- Add a forward Alembic migration from the generation 1 schema.
- Preserve every existing idea's ID, title, notes, stage, and timestamps.
- Set existing rows to `next_action = null`, `archived_at = null`, and
  `version = 1`.
- Fresh installation through the complete migration chain produces the same
  final schema as an upgraded installation.
- Migration is transactional where PostgreSQL permits and safe when startup is
  repeated against an already current database.
- The API never creates schema implicitly during import or requests.
- Failed mutations roll back.
- API restarts preserve data.
- Credentials never appear in browser assets, API errors, or logs.

Resetting, recreating, or deleting the generation 1 database/volume is not an
upgrade implementation.

## 5. REST API conventions

All endpoints are under `/api`. Success and error responses are JSON except a
successful delete. Idea responses always contain every field from G2-DATA-01.
Timestamps are UTC ISO 8601 strings using `Z` or an explicit `+00:00` offset.

### G2-API-01: Health

`GET /api/health` queries PostgreSQL. Return `200` with
`{"status":"ok","database":"ok"}` or `503` with
`{"status":"unavailable","database":"unavailable"}`.

### G2-API-02: Create

`POST /api/ideas` accepts required `title` plus optional `notes`, `stage`, and
`next_action`. Stage defaults to `seed`; nullable blank strings normalize to
null. Return `201` with `version = 1` and `archived_at = null`.

### G2-API-03: List and filter

`GET /api/ideas` accepts:

- optional `stage=seed|sprout|bloom`; and
- optional `archive=active|archived|all`, defaulting to `active`.

Return:

```json
{
  "ideas": [],
  "counts": {
    "seed": 0,
    "sprout": 0,
    "bloom": 0,
    "active": 0,
    "archived": 0,
    "total": 0
  }
}
```

`seed`, `sprout`, and `bloom` count active ideas in those stages. `active` is
their sum, `archived` counts archived ideas in all stages, and `total` is active
plus archived. Counts describe all stored ideas and do not change with list
filters. Unknown filter values return `422`.

### G2-API-04: Read one

`GET /api/ideas/{idea_id}` returns active or archived ideas by ID, or `404`.

### G2-API-05: Expected-version header

Every update, archive, restore, and delete request requires:

```text
If-Match: "<version>"
```

The quoted positive decimal integer is the version last read by the client.
Missing `If-Match` returns `428 Precondition Required`. Malformed, weak, zero, or
negative values return `400 Bad Request`.

Mutation error precedence is deterministic: first validate that `If-Match` is
present and syntactically valid, then return `404` for a missing idea, then
compare the stored version and return `version_conflict` when stale, and only
then apply mutation-specific state and body validation. A stale archive request
therefore returns `version_conflict` even if the current row is already archived.

### G2-API-06: Update

`PATCH /api/ideas/{idea_id}` accepts a non-empty subset of `title`, `notes`,
`stage`, and `next_action`, plus required `If-Match`. Successful update returns
`200`, increments version exactly once, and updates `updated_at`. Empty objects
return `422`; missing IDs return `404`.

Archived ideas may be edited; editing does not restore them.

### G2-API-07: Archive and restore

- `POST /api/ideas/{idea_id}/archive` with an empty body and required `If-Match`
  sets `archived_at`, updates `updated_at`, increments version, and returns the
  complete idea.
- `POST /api/ideas/{idea_id}/restore` with an empty body and required `If-Match`
  clears `archived_at`, updates `updated_at`, increments version, and returns the
  complete idea.
- Archiving an already archived idea or restoring an active idea returns `409`
  with code `invalid_archive_state` and the current idea.
- Missing IDs return `404`.

### G2-API-08: Permanent delete

`DELETE /api/ideas/{idea_id}` requires `If-Match` and returns `204` with an empty
body. It may delete active or archived ideas. Missing IDs return `404`.

### G2-API-09: Optimistic conflict

Mutation compares the expected version and writes atomically in one database
transaction. When it does not match, return `409 Conflict` without changing the
row:

```json
{
  "error": {
    "code": "version_conflict",
    "message": "Idea 42 has changed",
    "fields": null
  },
  "current": {
    "id": 42,
    "title": "Current title",
    "notes": null,
    "stage": "sprout",
    "next_action": null,
    "archived_at": null,
    "version": 3,
    "created_at": "2026-08-22T10:15:00Z",
    "updated_at": "2026-08-22T10:20:00Z"
  }
}
```

Two concurrent mutations using the same valid expected version cannot both
succeed. One succeeds and one receives `409`, regardless of API worker count.

### G2-API-10: Other errors

Other application errors retain this shape:

```json
{"error":{"code":"idea_not_found","message":"Idea 42 was not found","fields":null}}
```

Validation uses `validation_error`. Malformed JSON, wrong types, invalid stages,
blank titles, overlong values, invalid filters, and empty patches return `4xx`
without tracebacks or credentials.

## 6. Frontend contract

### G2-UI-01: Main view and counts

The **Idea Greenhouse** SPA shows seed, sprout, bloom, active, archived, and total
counts; stage filters; Active, Archived, and All archive filters; creation form;
and ordered idea cards or an appropriate empty state.

Cards show title, stage, optional notes, optional next action, archive state,
last-updated time, and controls appropriate to active/archived state.

### G2-UI-02: Create and edit

Forms expose title, notes, stage, and next action. Browser validation, server
field errors, duplicate-submission protection, preservation after failure, and
non-optimistic mutation behavior remain required. Successful responses replace
the client's stored idea including its new version.

### G2-UI-03: Archive, restore, and delete

- Active cards provide Archive; archived cards provide Restore.
- Permanent deletion requires confirmation naming the idea and clearly stating
  that deletion cannot be undone.
- Archive, restore, update, stage change, and delete send the displayed idea's
  quoted version in `If-Match`.
- Failed operations leave existing visible state intact and show an error.

### G2-UI-04: Conflict recovery

On `version_conflict`, show a visible message explaining that the idea changed
elsewhere. Do not automatically overwrite or silently retry the mutation. Offer
a **Reload current idea** action that replaces local card/form state with the
server's `current` representation. Preserve the user's unsaved form values until
they explicitly reload or cancel so they can copy their work.

### G2-UI-05: Loading, filtering, and accessibility

- Initial loading failure offers Retry.
- Filters expose selected state and counts remain global.
- Only the active mutation control is disabled.
- Fields have persistent accessible labels and all controls are keyboard
  operable.
- Errors/conflicts use appropriate alert/live regions without noisy unrelated
  announcements.
- Text or semantics, not color alone, identify stages, archive state, and errors.

## 7. Browser/API integration

### G2-INT-01

Browser code calls relative `/api/...` URLs. Vite proxies `/api` to
`API_BASE_URL`, defaulting to `http://127.0.0.1:8000`. Production routing follows
the deployment spec. Do not require permissive CORS or expose server secrets.

## 8. Configuration and commands

### G2-CFG-01

Backend `DATABASE_URL` is required; `HOST` defaults to `127.0.0.1`; `PORT`
defaults to `8000`. Invalid configuration fails safely without printing
passwords. Vite reads `API_BASE_URL` only in Node-side configuration.

### G2-CMD-01

Retain these root targets:

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

`make check` covers unit/component tests, builds, migration verification, and
Compose integration. Missing host tools are unverified prerequisites and are not
installed.

## 9. Verification

### G2-TEST-01: Backend and migration

Tests cover all generation 2 endpoints and errors, migration from a populated
generation 1 database, migration defaults and ID/timestamp preservation, clean
installation through the migration chain, expected-version parsing, exactly-once
version increments, stale update/archive/restore/delete conflicts, and two
concurrent same-version writers. PostgreSQL, not SQLite, is used for database
integration behavior.

### G2-TEST-02: Frontend

Component tests cover next-action create/edit, active/archive filters and counts,
archive/restore/delete, required `If-Match`, conflict display, preservation of
unsaved edits, explicit reload, loading/failure states, and accessibility.

### G2-TEST-03: Cross-boundary

`make compose-smoke` crosses frontend/nginx/API/PostgreSQL, verifies generation 1
data after migration, performs generation 2 mutations and conflicts, verifies
API-restart persistence, and cleans only its own fixture data as defined by the
deployment specification.

## 10. Documentation

### G2-DOC-01

README documents the full current API, `If-Match` and `409` behavior, archive
semantics, migration on startup, upgrade without volume deletion, local
development, validation, and Compose operation/data lifecycle.

## 11. Non-goals

Authentication, multiple users, merge UI, automatic conflict resolution,
soft-delete retention policy, audit history, public cloud deployment,
Kubernetes, production secrets management, and multiple databases remain out of
scope.
