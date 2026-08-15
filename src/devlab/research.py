from __future__ import annotations

import dataclasses
import json
import re
import tomllib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from devlab._files import atomic_write_text
from devlab._toml import format_toml_value

RESEARCH_DIR = ".devlab/research"
RESEARCH_ID_RE = re.compile(r"(?<![A-Z0-9])RS\d{4,5}(?!\d)")
_RESEARCH_FILENAME_RE = re.compile(r"^(RS\d{4,5})_[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
_TASK_RE = re.compile(r"T\d{3,5}")
_MILESTONE_RE = re.compile(r"M\d{1,5}")
_SCOPE_RE = re.compile(r"(?:workspace|planning|milestone:M\d{1,5}|task:T\d{3,5})")
_SOURCE_ID_RE = re.compile(r"S[1-9]\d*")
_FRONT_MATTER_RE = re.compile(r"\A\+\+\+\n([\s\S]*?)\n\+\+\+\n?", re.MULTILINE)
_EVIDENCE_RE = re.compile(r"^- (.+) \[([A-Z0-9, ]+)\]$")
_REQUEST_HEADINGS = ("Question", "Context", "Desired Outcome", "Acceptance Criteria")
_RESULT_HEADINGS = (
    "Summary",
    "Evidence",
    "Sources",
    "Recommendation",
    "Confidence",
    "Unresolved Questions",
)
_METADATA_KEYS = (
    "id",
    "title",
    "status",
    "asking_role",
    "asking_session_id",
    "command",
    "scope",
    "task",
    "milestone",
    "created_at",
    "researcher_session_id",
    "researcher_provider",
    "researcher_model",
    "completed_at",
)
_PROVENANCE_KEYS = (
    "researcher_session_id",
    "researcher_provider",
    "researcher_model",
    "completed_at",
)


class ResearchStatus(StrEnum):
    REQUESTED = "requested"
    COMPLETED = "completed"


class ResearchConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclasses.dataclass(frozen=True)
class ResearchSource:
    id: str
    title: str
    location: str
    source_type: str


@dataclasses.dataclass(frozen=True)
class ResearchEvidence:
    claim: str
    source_ids: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ResearchResult:
    summary: str
    evidence: tuple[ResearchEvidence, ...]
    sources: tuple[ResearchSource, ...]
    recommendation: str
    confidence: ResearchConfidence
    unresolved_questions: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
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


def parse_research_result_candidate(path: Path, *, research_id: str) -> ResearchResult:
    """Parse one strict staged researcher result for the expected request."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ValueError(f"researcher did not write {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("researcher result.json is invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("researcher result.json must contain an object")
    expected = {
        "schema_version",
        "research_id",
        "summary",
        "evidence",
        "sources",
        "recommendation",
        "confidence",
        "unresolved_questions",
    }
    unexpected = sorted(set(data) - expected)
    missing = sorted(expected - set(data))
    if unexpected:
        raise ValueError(
            "researcher result.json has unexpected field(s): " + ", ".join(unexpected)
        )
    if missing:
        raise ValueError("researcher result.json is missing field(s): " + ", ".join(missing))
    if data["schema_version"] != 1:
        raise ValueError("researcher result.json schema_version must be 1")
    if data["research_id"] != research_id:
        raise ValueError(f"researcher result.json research_id must be {research_id!r}")
    sources_value = data["sources"]
    if not isinstance(sources_value, list) or not sources_value:
        raise ValueError("researcher result.json sources must be a non-empty array")
    sources: list[ResearchSource] = []
    for index, value in enumerate(sources_value):
        if not isinstance(value, dict) or set(value) != {"id", "title", "location", "source_type"}:
            raise ValueError(
                f"researcher result.json sources[{index}] must contain exactly "
                "id, title, location, and source_type"
            )
        value = cast("dict[str, Any]", value)
        sources.append(
            ResearchSource(
                id=_json_required_string(value, "id", f"sources[{index}]"),
                title=_json_required_string(value, "title", f"sources[{index}]"),
                location=_json_required_string(value, "location", f"sources[{index}]"),
                source_type=_json_required_string(value, "source_type", f"sources[{index}]"),
            )
        )
    evidence_value = data["evidence"]
    if not isinstance(evidence_value, list) or not evidence_value:
        raise ValueError("researcher result.json evidence must be a non-empty array")
    evidence: list[ResearchEvidence] = []
    for index, value in enumerate(evidence_value):
        if not isinstance(value, dict) or set(value) != {"claim", "source_ids"}:
            raise ValueError(
                f"researcher result.json evidence[{index}] must contain exactly "
                "claim and source_ids"
            )
        value = cast("dict[str, Any]", value)
        source_ids = value["source_ids"]
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or any(not isinstance(item, str) or not item.strip() for item in source_ids)
        ):
            raise ValueError(
                f"researcher result.json evidence[{index}].source_ids must be a "
                "non-empty string array"
            )
        source_ids = cast("list[str]", source_ids)
        evidence.append(
            ResearchEvidence(
                claim=_json_required_string(value, "claim", f"evidence[{index}]"),
                source_ids=tuple(item.strip() for item in source_ids),
            )
        )
    unresolved = data["unresolved_questions"]
    if not isinstance(unresolved, list) or any(
        not isinstance(item, str) or not item.strip() for item in unresolved
    ):
        raise ValueError("researcher result.json unresolved_questions must be a string array")
    try:
        confidence = ResearchConfidence(data["confidence"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "researcher result.json confidence must be high, medium, or low"
        ) from exc
    return _validate_result(
        ResearchResult(
            summary=_json_required_string(data, "summary", "result"),
            evidence=tuple(evidence),
            sources=tuple(sources),
            recommendation=_json_required_string(data, "recommendation", "result"),
            confidence=confidence,
            unresolved_questions=tuple(item.strip() for item in unresolved),
        )
    )


def _json_required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"researcher result.json {context}.{key} must be a non-empty string")
    return value.strip()


class FileResearchTracker:
    """File-backed durable research request and result tracker."""

    def __init__(self, root: Path, research_dir: str = RESEARCH_DIR) -> None:
        self.root = root
        self.research_path = root / research_dir

    def list_research(self) -> list[Research]:
        research = sorted(
            (self._read_research(path) for path in self.research_path.glob("RS*.md")),
            key=lambda item: (_research_sort_key(item.id), item.path.name),
        )
        duplicate_ids = sorted(
            research_id
            for research_id in {item.id for item in research}
            if sum(item.id == research_id for item in research) > 1
        )
        if duplicate_ids:
            raise ValueError("duplicate research id(s): " + ", ".join(duplicate_ids))
        return research

    def get(self, research_id: str) -> Research:
        matches = [item for item in self.list_research() if item.id == research_id]
        if not matches:
            raise KeyError(f"unknown research id: {research_id}")
        return matches[0]

    def requested(self) -> list[Research]:
        return [
            item for item in self.list_research() if item.status == ResearchStatus.REQUESTED
        ]

    def create(
        self,
        *,
        title: str,
        asking_role: str,
        asking_session_id: str,
        command: str,
        scope: str,
        question: str,
        context: str,
        desired_outcome: str,
        acceptance_criteria: tuple[str, ...] | list[str],
        task: str = "",
        milestone: str = "",
        created_at: str | None = None,
    ) -> Research:
        title = _single_line(title, "title", max_length=160)
        asking_role = _single_line(asking_role, "asking_role")
        asking_session_id = _single_line(asking_session_id, "asking_session_id")
        command, scope, task, milestone = _validate_route(command, scope, task, milestone)
        question = _required_text(question, "question")
        context = _required_text(context, "context")
        desired_outcome = _required_text(desired_outcome, "desired_outcome")
        criteria = _validate_string_items(acceptance_criteria, "acceptance_criteria")
        created_at = _validate_timestamp(created_at or _utc_now(), "created_at")

        research_id = self._next_research_id()
        metadata: dict[str, Any] = {
            "id": research_id,
            "title": title,
            "status": ResearchStatus.REQUESTED.value,
            "asking_role": asking_role,
            "asking_session_id": asking_session_id,
            "command": command,
            "scope": scope,
            "task": task,
            "milestone": milestone,
            "created_at": created_at,
        }
        path = self.research_path / f"{research_id}_{_slugify(title)}.md"
        body = _format_body(
            research_id=research_id,
            title=title,
            question=question,
            context=context,
            desired_outcome=desired_outcome,
            acceptance_criteria=criteria,
            result=None,
        )
        atomic_write_text(path, _format_research_file(metadata, body))
        return self._read_research(path)

    def complete(
        self,
        research_id: str,
        result: ResearchResult,
        *,
        researcher_session_id: str,
        researcher_provider: str,
        researcher_model: str = "",
        completed_at: str | None = None,
    ) -> Research:
        research = self.get(research_id)
        if research.status != ResearchStatus.REQUESTED:
            raise ValueError(f"research {research_id} is not requested")
        result = _validate_result(result)
        researcher_session_id = _single_line(
            researcher_session_id, "researcher_session_id"
        )
        researcher_provider = _single_line(researcher_provider, "researcher_provider")
        researcher_model = _optional_single_line(researcher_model, "researcher_model")
        completed_at = _validate_timestamp(completed_at or _utc_now(), "completed_at")
        if _parse_timestamp(completed_at) < _parse_timestamp(research.created_at):
            raise ValueError("completed_at must not be earlier than created_at")

        metadata = dict(research.metadata)
        metadata.update(
            {
                "status": ResearchStatus.COMPLETED.value,
                "researcher_session_id": researcher_session_id,
                "researcher_provider": researcher_provider,
                "researcher_model": researcher_model,
                "completed_at": completed_at,
            }
        )
        body = _format_body(
            research_id=research.id,
            title=research.title,
            question=research.question,
            context=research.context,
            desired_outcome=research.desired_outcome,
            acceptance_criteria=research.acceptance_criteria,
            result=result,
        )
        atomic_write_text(research.path, _format_research_file(metadata, body))
        return self._read_research(research.path)

    def _next_research_id(self) -> str:
        maximum = max((_research_sort_key(item.id) for item in self.list_research()), default=0)
        if maximum >= 99999:
            raise ValueError("research id space is exhausted after RS99999")
        return f"RS{maximum + 1:04d}"

    def _read_research(self, path: Path) -> Research:
        try:
            metadata, body = _split_front_matter(path.read_text(), path)
            research_id = _required_metadata_string(metadata, "id", path)
            if RESEARCH_ID_RE.fullmatch(research_id) is None:
                raise ValueError(f"research file {path} has invalid field 'id': {research_id!r}")
            _validate_filename(path, research_id)
            title = _single_line(
                _required_metadata_string(metadata, "title", path),
                "title",
                max_length=160,
            )
            status = _parse_status(metadata.get("status"), path)
            asking_role = _required_metadata_string(metadata, "asking_role", path)
            asking_session_id = _required_metadata_string(metadata, "asking_session_id", path)
            command = _required_metadata_string(metadata, "command", path)
            scope = _required_metadata_string(metadata, "scope", path)
            task = _metadata_string(metadata, "task", path)
            milestone = _metadata_string(metadata, "milestone", path)
            command, scope, task, milestone = _validate_route(
                command, scope, task, milestone, path=path
            )
            created_at = _validate_timestamp(
                _required_metadata_string(metadata, "created_at", path),
                "created_at",
                path=path,
            )
            sections = _parse_body(body, research_id, title, status, path)
            criteria = _parse_list_section(
                sections["Acceptance Criteria"], "Acceptance Criteria", path
            )
            _validate_string_items(criteria, "acceptance_criteria", path=path)
            result = _parse_result(sections, path) if status == ResearchStatus.COMPLETED else None
            provenance = _parse_provenance(metadata, status, created_at, path)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"research file {path} has invalid TOML front matter") from exc

        normalized = dict(metadata)
        normalized.update(
            {
                "id": research_id,
                "title": title,
                "status": status.value,
                "asking_role": asking_role,
                "asking_session_id": asking_session_id,
                "command": command,
                "scope": scope,
                "task": task,
                "milestone": milestone,
                "created_at": created_at,
            }
        )
        return Research(
            id=research_id,
            title=title,
            status=status,
            path=path,
            asking_role=asking_role,
            asking_session_id=asking_session_id,
            command=command,
            scope=scope,
            task=task,
            milestone=milestone,
            created_at=created_at,
            researcher_session_id=provenance[0],
            researcher_provider=provenance[1],
            researcher_model=provenance[2],
            completed_at=provenance[3],
            question=sections["Question"],
            context=sections["Context"],
            desired_outcome=sections["Desired Outcome"],
            acceptance_criteria=tuple(criteria),
            result=result,
            metadata=normalized,
        )


def _split_front_matter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        raise ValueError(f"research file {path} requires TOML front matter")
    metadata = tomllib.loads(match.group(1))
    if not isinstance(metadata, dict):
        raise ValueError(f"research file {path} front matter must be a TOML table")
    return metadata, text[match.end() :]


def _parse_body(
    body: str,
    research_id: str,
    title: str,
    status: ResearchStatus,
    path: Path,
) -> dict[str, str]:
    lines = body.strip().splitlines()
    expected_h1 = f"# {research_id}: {title}"
    if not lines or lines[0] != expected_h1:
        raise ValueError(f"research file {path} requires exact heading {expected_h1!r}")
    if any(line.startswith("# ") for line in lines[1:]):
        raise ValueError(f"research file {path} contains an unexpected H1 heading")
    heading_indexes = [index for index, line in enumerate(lines) if line.startswith("## ")]
    headings = [lines[index][3:].strip() for index in heading_indexes]
    expected = list(_REQUEST_HEADINGS)
    if status == ResearchStatus.COMPLETED:
        expected.extend(_RESULT_HEADINGS)
    if headings != expected:
        raise ValueError(
            f"research file {path} requires H2 sections in order: {', '.join(expected)}"
        )
    if any(line.strip() for line in lines[1 : heading_indexes[0]]):
        raise ValueError(f"research file {path} contains text before ## Question")
    sections: dict[str, str] = {}
    for position, start in enumerate(heading_indexes):
        end = heading_indexes[position + 1] if position + 1 < len(heading_indexes) else len(lines)
        value = "\n".join(lines[start + 1 : end]).strip()
        heading = headings[position]
        if not value:
            raise ValueError(f"research file {path} has empty section ## {heading}")
        sections[heading] = value
    return sections


def _parse_result(sections: dict[str, str], path: Path) -> ResearchResult:
    evidence: list[ResearchEvidence] = []
    for line in _list_lines(sections["Evidence"], "Evidence", path):
        match = _EVIDENCE_RE.fullmatch(line)
        if match is None:
            raise ValueError(
                f"research file {path} has malformed ## Evidence entry: {line!r}"
            )
        source_ids = tuple(item.strip() for item in match.group(2).split(","))
        evidence.append(ResearchEvidence(claim=match.group(1).strip(), source_ids=source_ids))

    sources: list[ResearchSource] = []
    for line in _list_lines(sections["Sources"], "Sources", path):
        parts = [part.strip() for part in line[2:].split("|")]
        if len(parts) != 4:
            raise ValueError(f"research file {path} has malformed ## Sources entry: {line!r}")
        sources.append(
            ResearchSource(id=parts[0], source_type=parts[1], title=parts[2], location=parts[3])
        )

    confidence_text = sections["Confidence"].strip()
    try:
        confidence = ResearchConfidence(confidence_text)
    except ValueError as exc:
        raise ValueError(
            f"research file {path} has invalid ## Confidence: {confidence_text!r}"
        ) from exc

    unresolved_lines = _parse_list_section(
        sections["Unresolved Questions"], "Unresolved Questions", path
    )
    unresolved = () if unresolved_lines == ["None"] else tuple(unresolved_lines)
    result = ResearchResult(
        summary=sections["Summary"],
        evidence=tuple(evidence),
        sources=tuple(sources),
        recommendation=sections["Recommendation"],
        confidence=confidence,
        unresolved_questions=unresolved,
    )
    return _validate_result(result, path=path)


def _parse_provenance(
    metadata: dict[str, Any],
    status: ResearchStatus,
    created_at: str,
    path: Path,
) -> tuple[str, str, str, str | None]:
    if status == ResearchStatus.REQUESTED:
        present = [key for key in _PROVENANCE_KEYS if key in metadata]
        if present:
            raise ValueError(
                f"research file {path} requested status forbids provenance field(s): "
                + ", ".join(present)
            )
        return "", "", "", None

    session_id = _required_metadata_string(metadata, "researcher_session_id", path)
    provider = _required_metadata_string(metadata, "researcher_provider", path)
    model = _metadata_string(metadata, "researcher_model", path, required=True)
    completed_at = _validate_timestamp(
        _required_metadata_string(metadata, "completed_at", path), "completed_at", path=path
    )
    if _parse_timestamp(completed_at) < _parse_timestamp(created_at):
        raise ValueError(f"research file {path} completed_at is earlier than created_at")
    return session_id, provider, model, completed_at


def _validate_result(result: ResearchResult, *, path: Path | None = None) -> ResearchResult:
    location = f"research file {path} " if path is not None else "research result "
    if not isinstance(result, ResearchResult):
        raise ValueError(f"{location}must be a ResearchResult")
    summary = _required_text(result.summary, "summary", path=path)
    recommendation = _required_text(result.recommendation, "recommendation", path=path)
    try:
        confidence = ResearchConfidence(result.confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{location}has invalid confidence {result.confidence!r}") from exc
    if not result.sources:
        raise ValueError(f"{location}requires at least one source")
    sources: list[ResearchSource] = []
    source_ids: set[str] = set()
    for source in result.sources:
        if not isinstance(source, ResearchSource):
            raise ValueError(f"{location}sources must contain ResearchSource values")
        source_id = _single_line(source.id, "source id", path=path)
        if _SOURCE_ID_RE.fullmatch(source_id) is None:
            raise ValueError(f"{location}has invalid source id {source_id!r}")
        if source_id in source_ids:
            raise ValueError(f"{location}has duplicate source id {source_id!r}")
        source_ids.add(source_id)
        source_type = _delimited_value(source.source_type, "source_type", path)
        title = _delimited_value(source.title, "source title", path)
        location_value = _delimited_value(source.location, "source location", path)
        sources.append(ResearchSource(source_id, title, location_value, source_type))
    if not result.evidence:
        raise ValueError(f"{location}requires at least one evidence entry")
    evidence: list[ResearchEvidence] = []
    for item in result.evidence:
        if not isinstance(item, ResearchEvidence):
            raise ValueError(f"{location}evidence must contain ResearchEvidence values")
        claim = _single_line(item.claim, "evidence claim", path=path)
        cited = tuple(
            _single_line(value, "evidence source id", path=path)
            for value in item.source_ids
        )
        if not cited:
            raise ValueError(f"{location}evidence claim {claim!r} requires a source")
        if len(cited) != len(set(cited)):
            raise ValueError(f"{location}evidence claim {claim!r} has duplicate source ids")
        unknown = sorted(set(cited) - source_ids)
        if unknown:
            raise ValueError(
                f"{location}evidence claim {claim!r} cites unknown source(s): "
                + ", ".join(unknown)
            )
        evidence.append(ResearchEvidence(claim, cited))
    unresolved = _validate_string_items(
        result.unresolved_questions,
        "unresolved_questions",
        allow_empty=True,
        path=path,
    )
    if "None" in unresolved:
        raise ValueError(f"{location}unresolved_questions reserves the value 'None'")
    return ResearchResult(
        summary=summary,
        evidence=tuple(evidence),
        sources=tuple(sources),
        recommendation=recommendation,
        confidence=confidence,
        unresolved_questions=tuple(unresolved),
    )


def _format_research_file(metadata: dict[str, Any], body: str) -> str:
    lines = ["+++"]
    for key in _METADATA_KEYS:
        if key in metadata:
            lines.append(f"{key} = {format_toml_value(metadata[key])}")
    known = set(_METADATA_KEYS)
    for key in sorted(key for key in metadata if key not in known):
        lines.append(f"{key} = {format_toml_value(metadata[key])}")
    lines.append("+++")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


def _format_body(
    *,
    research_id: str,
    title: str,
    question: str,
    context: str,
    desired_outcome: str,
    acceptance_criteria: tuple[str, ...],
    result: ResearchResult | None,
) -> str:
    sections = [
        f"# {research_id}: {title}",
        f"## Question\n{_safe_markdown(question)}",
        f"## Context\n{_safe_markdown(context)}",
        f"## Desired Outcome\n{_safe_markdown(desired_outcome)}",
        "## Acceptance Criteria\n" + _format_list(acceptance_criteria),
    ]
    if result is not None:
        sections.extend(
            (
                f"## Summary\n{_safe_markdown(result.summary)}",
                "## Evidence\n"
                + "\n".join(
                    f"- {item.claim} [{', '.join(item.source_ids)}]"
                    for item in result.evidence
                ),
                "## Sources\n"
                + "\n".join(
                    f"- {source.id} | {source.source_type} | {source.title} | {source.location}"
                    for source in result.sources
                ),
                f"## Recommendation\n{_safe_markdown(result.recommendation)}",
                f"## Confidence\n{result.confidence.value}",
                "## Unresolved Questions\n"
                + _format_list(result.unresolved_questions or ("None",)),
            )
        )
    return "\n\n".join(sections)


def _validate_route(
    command: str,
    scope: str,
    task: str,
    milestone: str,
    *,
    path: Path | None = None,
) -> tuple[str, str, str, str]:
    command = _single_line(command, "command", path=path)
    scope = _single_line(scope, "scope", path=path)
    task = _optional_single_line(task, "task", path=path)
    milestone = _optional_single_line(milestone, "milestone", path=path)
    prefix = f"research file {path} " if path is not None else "research "
    if command not in {"plan", "implement"}:
        raise ValueError(f"{prefix}has invalid command {command!r}")
    if _SCOPE_RE.fullmatch(scope) is None:
        raise ValueError(f"{prefix}has invalid scope {scope!r}")
    if task and _TASK_RE.fullmatch(task) is None:
        raise ValueError(f"{prefix}has invalid task {task!r}")
    if milestone and _MILESTONE_RE.fullmatch(milestone) is None:
        raise ValueError(f"{prefix}has invalid milestone {milestone!r}")
    if scope.startswith("task:") and (
        scope.removeprefix("task:") != task or command != "implement"
    ):
        raise ValueError(f"{prefix}task scope must match task and use command 'implement'")
    if scope.startswith("milestone:") and scope.removeprefix("milestone:") != milestone:
        raise ValueError(f"{prefix}milestone scope must match milestone")
    if scope == "planning" and (command != "plan" or task):
        raise ValueError(f"{prefix}planning scope must use command 'plan' and no task")
    return command, scope, task, milestone


def _required_metadata_string(metadata: dict[str, Any], key: str, path: Path) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"research file {path} requires non-empty string field {key!r}")
    return value


def _metadata_string(
    metadata: dict[str, Any], key: str, path: Path, *, required: bool = False
) -> str:
    if key not in metadata:
        if required:
            raise ValueError(f"research file {path} requires string field {key!r}")
        return ""
    value = metadata[key]
    if not isinstance(value, str):
        raise ValueError(f"research file {path} field {key!r} must be a string")
    return value


def _parse_status(value: Any, path: Path) -> ResearchStatus:
    if not isinstance(value, str):
        raise ValueError(f"research file {path} requires string field 'status'")
    try:
        return ResearchStatus(value)
    except ValueError as exc:
        raise ValueError(f"research file {path} has invalid status {value!r}") from exc


def _validate_filename(path: Path, research_id: str) -> None:
    match = _RESEARCH_FILENAME_RE.fullmatch(path.name)
    if match is None or match.group(1) != research_id:
        raise ValueError(
            f"research file {path} filename must start with {research_id}_ and use a slug"
        )


def _validate_timestamp(value: str, field: str, *, path: Path | None = None) -> str:
    value = _single_line(value, field, path=path)
    try:
        parsed = _parse_timestamp(value)
    except ValueError as exc:
        prefix = f"research file {path} " if path is not None else "research "
        raise ValueError(
            f"{prefix}field {field!r} must be a timezone-aware ISO timestamp"
        ) from exc
    if parsed.utcoffset() is None:
        prefix = f"research file {path} " if path is not None else "research "
        raise ValueError(f"{prefix}field {field!r} must be a timezone-aware ISO timestamp")
    return value


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _single_line(
    value: object,
    field: str,
    *,
    max_length: int | None = None,
    path: Path | None = None,
) -> str:
    prefix = f"research file {path} " if path is not None else "research "
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix}field {field!r} must be a non-empty string")
    normalized = value.strip()
    if "\n" in normalized or "\r" in normalized:
        raise ValueError(f"{prefix}field {field!r} must be a single line")
    if max_length is not None and len(normalized) > max_length:
        raise ValueError(f"{prefix}field {field!r} must be at most {max_length} characters")
    return normalized


def _optional_single_line(value: object, field: str, *, path: Path | None = None) -> str:
    if not isinstance(value, str):
        prefix = f"research file {path} " if path is not None else "research "
        raise ValueError(f"{prefix}field {field!r} must be a string")
    if not value:
        return ""
    return _single_line(value, field, path=path)


def _required_text(value: object, field: str, *, path: Path | None = None) -> str:
    prefix = f"research file {path} " if path is not None else "research "
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix}field {field!r} must be a non-empty string")
    return value.strip()


def _validate_string_items(
    values: object,
    field: str,
    *,
    allow_empty: bool = False,
    path: Path | None = None,
) -> tuple[str, ...]:
    prefix = f"research file {path} " if path is not None else "research "
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{prefix}field {field!r} must be a list or tuple")
    normalized = tuple(_single_line(value, field, path=path) for value in values)
    if not normalized and not allow_empty:
        raise ValueError(f"{prefix}field {field!r} must contain at least one item")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{prefix}field {field!r} must not contain duplicates")
    return normalized


def _parse_list_section(section: str, heading: str, path: Path) -> list[str]:
    lines = _list_lines(section, heading, path)
    return [line[2:].strip() for line in lines]


def _list_lines(section: str, heading: str, path: Path) -> list[str]:
    lines = section.splitlines()
    if not lines or any(not line.startswith("- ") or not line[2:].strip() for line in lines):
        raise ValueError(f"research file {path} section ## {heading} requires '- ' list items")
    return lines


def _delimited_value(value: object, field: str, path: Path | None) -> str:
    normalized = _single_line(value, field, path=path)
    if "|" in normalized:
        prefix = f"research file {path} " if path is not None else "research "
        raise ValueError(f"{prefix}field {field!r} must not contain '|'")
    return normalized


def _safe_markdown(value: str) -> str:
    return re.sub(r"^#{1,2}(?=\s)", "###", value.strip(), flags=re.MULTILINE)


def _format_list(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _research_sort_key(research_id: str) -> int:
    return int(research_id.removeprefix("RS"))


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "research"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
