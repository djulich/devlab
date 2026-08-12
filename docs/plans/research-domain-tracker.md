# Research Domain Tracker

Status: **implemented**.

Parent plan: [`durable-research-sessions.md`](durable-research-sessions.md),
Phase 1, item 1.

## Goal

Implement the authoritative file-backed domain model for durable research
requests and completed research results. This task establishes the record
format and transition invariants that later workspace, handoff, and
orchestration work will use.

The task is intentionally limited to:

- `src/devlab/research.py`;
- `tests/test_research.py`;
- the canonical `.devlab/research/RSXXXX_slug.md` format.

Do not integrate the tracker into `Workspace`, handoffs, prompts, workflow
state, orchestration, CLI commands, status, doctor, diagnostics, packaged
prompts, or initialization in this task.

## Domain Decisions

### Research is its own durable domain

A research record is neither a clarification nor a finding:

- clarification records operator intent;
- findings record repository work that must be planned or resolved;
- research records a discoverable question and the evidence-backed result of a
  bounded auxiliary session.

Store records under `.devlab/research/`. Keep all parsing and mutation in
`research.py`; later modules must consume the tracker API rather than parse the
Markdown files.

### One record owns request and result

Use one canonical record for the complete lifecycle. Creation writes a
`requested` record. Completion atomically rewrites that record as `completed`
and adds the validated result and researcher provenance.

Supported transitions:

```text
absent -> requested -> completed
```

There is no `failed`, `cancelled`, or reverse transition in this task.
Operational researcher failures will later leave the record `requested`.

### Strict new format

This is a new authoritative workflow format, so parsing should fail closed.
Do not silently derive missing IDs from filenames, default missing statuses, or
coerce scalar values to strings. Reject malformed records with errors that name
the file and violated field or section.

Preserve unknown front-matter keys when rewriting a valid record, following
the forward-compatible behavior of existing Markdown trackers. Reject unknown
H2 sections because they could hide a misspelled required field.

## Public Domain Types

Add these types to `src/devlab/research.py`:

```python
class ResearchStatus(StrEnum):
    REQUESTED = "requested"
    COMPLETED = "completed"


class ResearchConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ResearchSource:
    id: str
    title: str
    location: str
    source_type: str


@dataclass(frozen=True)
class ResearchEvidence:
    claim: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResearchResult:
    summary: str
    evidence: tuple[ResearchEvidence, ...]
    sources: tuple[ResearchSource, ...]
    recommendation: str
    confidence: ResearchConfidence
    unresolved_questions: tuple[str, ...]


@dataclass(frozen=True)
class Research:
    id: str
    title: str
    status: ResearchStatus
    path: Path
    asking_role: str
    asking_session_id: str
    command: str
    scope: str
    task: str
    milestone: str
    created_at: str
    researcher_session_id: str
    researcher_provider: str
    researcher_model: str
    completed_at: str | None
    question: str
    context: str
    desired_outcome: str
    acceptance_criteria: tuple[str, ...]
    result: ResearchResult | None
    metadata: dict[str, Any]
```

The exact internal helper types may vary, but keep the public representation
immutable and parsed rather than exposing raw result Markdown to callers.

Use empty strings for route/provenance fields that are structurally present but
not applicable or unavailable. Use `None` only for `completed_at` and `result`
while the record is requested. This matches the planned durable format and
keeps later serialization simple.

## Tracker API

Implement:

```python
RESEARCH_DIR = ".devlab/research"
RESEARCH_ID_RE = re.compile(r"(?<![A-Z0-9])RS\d{4,5}(?!\d)")


class FileResearchTracker:
    def __init__(self, root: Path, research_dir: str = RESEARCH_DIR) -> None: ...

    def list_research(self) -> list[Research]: ...
    def get(self, research_id: str) -> Research: ...
    def requested(self) -> list[Research]: ...

    def create(
        self,
        *,
        title: str,
        asking_role: str,
        asking_session_id: str,
        command: str,
        scope: str,
        task: str = "",
        milestone: str = "",
        question: str,
        context: str,
        desired_outcome: str,
        acceptance_criteria: tuple[str, ...] | list[str],
        created_at: str | None = None,
    ) -> Research: ...

    def complete(
        self,
        research_id: str,
        result: ResearchResult,
        *,
        researcher_session_id: str,
        researcher_provider: str,
        researcher_model: str = "",
        completed_at: str | None = None,
    ) -> Research: ...
```

Behavior:

- `list_research()` reads `RS*.md` records and sorts by numeric ID, then
  filename for deterministic handling of malformed duplicates;
- `get()` returns the unique matching record and raises `KeyError` for an
  unknown ID; duplicate IDs raise `ValueError` rather than choosing one;
- `requested()` returns requested records in tracker order;
- `create()` validates all inputs before creating the directory or writing;
- ID allocation scans parsed existing records and chooses one greater than the
  greatest numeric ID, formatted to at least four digits; allocation fails
  explicitly after `RS99999` because the schema allows at most five digits;
- `complete()` accepts only a requested record, validates the complete result
  and provenance before writing, performs one atomic replacement, and returns
  the record parsed back from disk;
- completing an already completed record raises `ValueError`; idempotent retry
  semantics belong to the later orchestration transition, which can inspect
  the existing completed record before calling `complete()`.

Use `atomic_write_text` for creation and completion. Do not add tracker-specific
locking; DevLab does not support concurrent workflow sessions.

## Canonical Record Format

### Requested record

```md
+++
id = "RS0001"
title = "PostgreSQL advisory-lock semantics"
status = "requested"
asking_role = "planner"
asking_session_id = "20260812T101500_002_planner"
command = "plan"
scope = "milestone:M2"
task = ""
milestone = "M2"
created_at = "2026-08-12T10:15:00+00:00"
+++

# RS0001: PostgreSQL advisory-lock semantics

## Question
Can a session-scoped advisory lock safely serialize these workers?

## Context
The design needs one active scheduler across service replicas.

## Desired Outcome
Recommend a locking approach and explain cleanup behavior.

## Acceptance Criteria
- Compare session-level and transaction-level locks.
- Use PostgreSQL primary documentation.
```

### Completed record

Completion changes the status and adds these front-matter keys in canonical
order after `created_at`:

```toml
researcher_session_id = "20260812T102000_003_researcher"
researcher_provider = "codex"
researcher_model = "gpt-5"
completed_at = "2026-08-12T10:25:00+00:00"
```

It then appends:

```md
## Summary
Session-level advisory locks are released when the database session ends.

## Evidence
- Session locks persist until explicit release or session end. [S1]

## Sources
- S1 | primary | PostgreSQL advisory-lock documentation | https://example.invalid/docs

## Recommendation
Use a dedicated connection if connection affinity can be guaranteed.

## Confidence
medium

## Unresolved Questions
- Does the selected pool guarantee connection affinity?
```

Canonical formatting rules:

- front matter uses `format_toml_value` and a fixed known-key order, followed by
  preserved unknown keys sorted lexically;
- files end with one newline;
- H1 is exactly `# <id>: <title>`;
- required H2 sections occur exactly once and in canonical order;
- list values use one `- ` item per entry;
- evidence citations use trailing `[S1, S2]` source IDs;
- sources use `- <id> | <source_type> | <title> | <location>`;
- free-text scalar sections preserve internal Markdown but may not introduce an
  H1 or H2 heading; normalize such headings to H3 on writes, as clarification
  answers already do;
- list items are single logical lines; reject embedded newlines during API
  validation to keep parsing unambiguous;
- source IDs, types, titles, and locations may not contain the `|` delimiter.

Do not expose the Markdown source/source-evidence encoding as the later staged
researcher result schema. The tracker accepts typed values and owns canonical
Markdown serialization.

## Validation Rules

### Identity and filename

- IDs match `RS\d{4,5}`.
- The filename starts with the exact metadata ID followed by `_` and a slug,
  and ends in `.md`.
- Metadata ID and H1 ID/title match exactly.
- Titles are non-empty, single-line values after trimming.
- Duplicate IDs are invalid even when filenames differ.

Use the same lowercase ASCII slug strategy as findings and clarifications,
falling back to `research`.

### Request metadata

- `status` is exactly `requested` or `completed`.
- `asking_role` is non-empty. Do not enforce software-role eligibility here;
  that belongs to handoff/orchestration policy in a later task.
- `asking_session_id` is non-empty.
- `command` is `plan` or `implement`.
- `scope` is one of `workspace`, `planning`, `milestone:<id>`, or `task:TXXXX`.
- `task` is empty or matches `T\d{3,5}`.
- `milestone` is empty or matches `M\d{1,5}`.
- a `task:<id>` scope equals `task` and uses `command = "implement"`;
- a `milestone:<id>` scope equals `milestone`;
- `planning` scope uses `command = "plan"` and has an empty task;
- `created_at` is a valid timezone-aware ISO 8601 timestamp.
- question, context, and desired outcome are non-empty.
- acceptance criteria contain at least one non-empty, unique item.

Do not require a particular milestone for every task request in this tracker;
the later workspace/orchestrator layer will validate the task's actual route.

### Status consistency

For `requested`:

- result sections are absent;
- researcher provenance keys and `completed_at` are absent;
- parsed `result` is `None`.

For `completed`:

- every result section is present exactly once;
- `researcher_session_id`, `researcher_provider`, and `completed_at` are
  non-empty;
- `researcher_model` is present but may be empty;
- `completed_at` is a timezone-aware ISO 8601 timestamp no earlier than
  `created_at`;
- parsed `result` is non-`None`.

### Result consistency

- summary and recommendation are non-empty;
- confidence is `high`, `medium`, or `low`;
- at least one source and one evidence entry exist;
- source IDs match `S[1-9]\d*` and are unique;
- source title, location, and source type are non-empty;
- evidence claims are non-empty;
- every evidence entry cites at least one source;
- every cited source ID exists;
- duplicate source IDs within one evidence entry are rejected;
- unresolved questions may be empty; canonical Markdown then writes
  `- None` and parsing maps that sentinel back to an empty tuple;
- otherwise unresolved questions are non-empty and unique.

The tracker validates structure and referential integrity only. It does not
fetch sources, judge authority, verify claims, or restrict `source_type` to a
closed taxonomy.

## Error Behavior

Raise `ValueError` for malformed records and invalid transitions. Messages
should include the record path for read failures and a precise field or section
name. Preserve `tomllib.TOMLDecodeError` as the cause when front matter is
invalid.

Raise `KeyError("unknown research id: RSXXXX")` from `get()` and `complete()`
when no record exists.

Validation must happen before writes. A failed `create()` leaves no new record;
a failed `complete()` leaves the requested file byte-for-byte unchanged.

## Implementation Steps

1. Add enums and immutable request/result dataclasses.
2. Implement strict front-matter splitting, field validation, timestamp
   parsing, Markdown section parsing, and list/source/evidence codecs.
3. Implement canonical formatting for requested and completed records.
4. Implement tracker listing, duplicate detection, lookup, filtering, and ID
   allocation.
5. Implement validated atomic request creation.
6. Implement the single validated atomic completion transition.
7. Add focused tests covering the public API and malformed on-disk records.
8. Run formatting, focused tests, and complete repository validation.

Keep this in one well-organized module. The record schema, codecs, and tracker
are tightly coupled; splitting them would increase the import graph without
creating an independent domain.

## Required Tests

Cover at least:

- creating the first request and exact canonical round trip;
- slug fallback, transition from four- to five-digit ID allocation, and
  exhaustion after `RS99999`;
- deterministic listing and requested filtering;
- unknown and duplicate IDs;
- completion round trip with multiple evidence/source references;
- completion with empty researcher model and no unresolved questions;
- completing an unknown or already completed record;
- failed completion preserving original bytes;
- preservation and sorted rewriting of unknown front-matter keys;
- invalid TOML, missing front matter, missing/extra/duplicate sections, and
  wrong section order;
- filename/metadata/H1 identity or title mismatch;
- invalid status, command, scope, task, milestone, route consistency, and
  timestamps;
- missing or forbidden provenance for each status;
- empty or duplicate acceptance criteria;
- invalid confidence;
- absent/duplicate/malformed sources;
- evidence with no sources, duplicate citations, or unknown citations;
- multiline list items and heading normalization in free text;
- `- None` round trip for empty unresolved questions.

Prefer direct tracker tests using `tmp_path`. Assert exact file text for one
requested and one completed golden example; use targeted assertions elsewhere
to avoid brittle duplication.

## Validation Commands

During development:

```bash
uv --cache-dir /tmp/uv-cache run pytest tests/test_research.py
uv --cache-dir /tmp/uv-cache run ruff check src/devlab/research.py tests/test_research.py
uv --cache-dir /tmp/uv-cache run ty check
```

Before completion:

```bash
make check
```

## Acceptance Criteria

- `FileResearchTracker` can create, list, retrieve, filter, and complete strict
  durable research records.
- Requested and completed files have deterministic canonical representations.
- Invalid input and malformed disk state fail closed with actionable errors.
- Completion validates evidence/source referential integrity and performs one
  atomic replacement.
- Failed writes or transitions do not corrupt or partially update a record.
- The new module does not import workspace, orchestration, handoff, prompt, CLI,
  provider, or reporting modules.
- No existing production module changes are required by this task.
- Focused tests and `make check` pass.

## Explicitly Deferred

- `WorkspaceSnapshot` and `Workspace.research()` integration;
- session-result and handoff request parsing;
- eligible requesting-role enforcement;
- resume-state or workflow-event changes;
- researcher result-candidate JSON parsing;
- agent configuration, executable fingerprints, prompts, or invocation;
- workspace edit isolation;
- CLI, status, doctor, diagnostics, or documentation outside these plans;
- migrations or compatibility behavior for pre-existing research files;
- concurrency and file locking;
- cancellation, abandonment, deletion, or reopening transitions.
