from __future__ import annotations

import dataclasses
import json
import os
import re
import tomllib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from devlab.clarifications import expected_file_edit_paths

REQUIRED_HANDOFF_HEADINGS = (
    "Done",
    "Changed Artifacts",
    "Open Issues",
    "Addressed Findings",
    "Next Session Hint",
)
OPTIONAL_HANDOFF_HEADINGS = ("Planning State", "Commit Message", "Clarification Request")

_HEADING_RE = re.compile(r"^## (?P<heading>.+?)[ \t]*$", re.MULTILINE)
_NONE_LINES = {"none", "- none"}
_ADDRESSED_FINDING_LINE_RE = re.compile(
    r"^-\s+(?P<finding>F\d{4,5}):\s+"
    r"(?P<tasks>T\d{3,5}(?:\s*,\s*T\d{3,5})*)\s*$"
)

SESSION_RESULT_SCHEMA_VERSION = 1
SESSION_ENVELOPE_ENV = "DEVLAB_SESSION_ENVELOPE"
DEVLAB_PYTHON_ENV = "DEVLAB_PYTHON"
SESSION_ENVELOPE_FILE = "session.toml"
HANDOFF_CANDIDATE_FILE = "handoff-candidate.toml"
SESSION_RESULT_FILE = "result.toml"
HANDOFF_FILE = "handoff.md"
MAX_CANDIDATE_BYTES = 128 * 1024
MAX_SUBMISSION_ATTEMPTS = 3


class HandoffFailureReason(StrEnum):
    """Stable category for handoff contract and acceptance failures."""

    SYNTAX = "syntax"
    CONTRACT = "contract"
    REFERENCE = "reference"
    SEMANTIC_CONFLICT = "semantic_conflict"
    SAFETY_LIMIT = "safety_limit"
    SESSION_PROTOCOL = "session_protocol"


@dataclasses.dataclass(frozen=True)
class SessionEnvelope:
    schema_version: int
    session_id: str
    role: str
    task: str = ""
    milestone: str = ""
    protected_active_tasks: tuple[str, ...] = ()
    incremental_planning_required: bool = False
    allow_active_task_replacement: bool = False


@dataclasses.dataclass(frozen=True)
class HandoffCandidate:
    schema_version: int
    outcome: str
    commit_message: str
    done: tuple[str, ...]
    changed_artifacts: tuple[str, ...]
    open_issues: tuple[str, ...]
    addressed_findings: tuple[str, ...]
    next_session_hint: str
    planning_complete: bool | None = None
    clarification: ClarificationRequest | None = None

    def as_handoff(self, path: Path, role_name: str) -> Handoff:
        text = render_handoff(self, role_name)
        return Handoff(
            path=path,
            role_name=role_name,
            sections=_parse_sections(text, role_name),
        )


@dataclasses.dataclass(frozen=True)
class SessionResult:
    envelope: SessionEnvelope
    candidate: HandoffCandidate

    def as_handoff(self, path: Path) -> Handoff:
        return self.candidate.as_handoff(path, self.envelope.role)


@dataclasses.dataclass(frozen=True)
class ClarificationRequest:
    title: str
    scope: str
    blocks: str
    answer_shape: str
    recommended_option: str
    details: str


@dataclasses.dataclass(frozen=True)
class Handoff:
    """Parsed role handoff with validated required sections."""

    path: Path
    role_name: str
    sections: dict[str, str]

    def section(self, heading: str) -> str:
        return self.sections.get(heading, "")

    @property
    def open_issues(self) -> str:
        return self.section("Open Issues")

    @property
    def has_open_issues(self) -> bool:
        return not section_is_none(self.open_issues)

    @property
    def addressed_findings(self) -> str:
        return self.section("Addressed Findings")

    @property
    def commit_message(self) -> str:
        return first_commit_message_line(self.section("Commit Message"))

    @property
    def planning_complete(self) -> bool | None:
        section = self.section("Planning State")
        if not section:
            return None
        return parse_planning_state(section)

    @property
    def clarification_request(self) -> ClarificationRequest | None:
        section = self.section("Clarification Request")
        if not section:
            return None
        return parse_clarification_request(section)

    def addressed_finding_tasks(self) -> dict[str, tuple[str, ...]]:
        return addressed_finding_tasks(self.addressed_findings)


class HandoffError(ValueError):
    """Raised when a handoff does not satisfy DevLab's artifact contract."""

    def __init__(
        self,
        message: str,
        *,
        reason: HandoffFailureReason = HandoffFailureReason.CONTRACT,
    ) -> None:
        super().__init__(message)
        self.reason = reason


class HandoffSubmissionError(HandoffError):
    """Rejected candidate with all independently detectable issues."""

    def __init__(
        self,
        issues: tuple[str, ...],
        *,
        reason: HandoffFailureReason = HandoffFailureReason.CONTRACT,
    ) -> None:
        self.issues = issues
        super().__init__("; ".join(issues), reason=reason)


def write_session_envelope(path: Path, envelope: SessionEnvelope) -> None:
    """Create trusted identity and a role-aware disposable candidate."""
    _atomic_write(path, _render_envelope(envelope))
    candidate_path = path.with_name(HANDOFF_CANDIDATE_FILE)
    _atomic_write(candidate_path, render_candidate_template(envelope.role))


def load_session_envelope(path: Path) -> SessionEnvelope:
    data = _load_toml_file(path, "session envelope")
    expected = {
        "schema_version",
        "session_id",
        "role",
        "task",
        "milestone",
        "protected_active_tasks",
        "incremental_planning_required",
        "allow_active_task_replacement",
    }
    if set(data) != expected:
        raise HandoffError(
            "session envelope fields do not match the supported schema",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    envelope = SessionEnvelope(
        schema_version=_required_int(data, "schema_version", "session envelope"),
        session_id=_required_string(data, "session_id", "session envelope"),
        role=_required_string(data, "role", "session envelope"),
        task=_optional_string(data, "task", "session envelope"),
        milestone=_optional_string(data, "milestone", "session envelope"),
        protected_active_tasks=_required_string_tuple(
            data, "protected_active_tasks", "session envelope"
        ),
        incremental_planning_required=_required_bool(
            data, "incremental_planning_required", "session envelope"
        ),
        allow_active_task_replacement=_required_bool(
            data, "allow_active_task_replacement", "session envelope"
        ),
    )
    if envelope.schema_version != SESSION_RESULT_SCHEMA_VERSION:
        raise HandoffError(
            f"unsupported session envelope schema version {envelope.schema_version}",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    return envelope


def active_session_envelope(root: Path, explicit: Path | None = None) -> Path:
    """Resolve the envelope for an in-session command without candidate identity."""
    if explicit is not None:
        path = explicit if explicit.is_absolute() else root / explicit
        return path.resolve()
    configured = os.environ.get(SESSION_ENVELOPE_ENV, "").strip()
    if configured:
        path = Path(configured)
        return (path if path.is_absolute() else root / path).resolve()
    matches = sorted((root / ".devlab/session-artifacts").glob(f"*/{SESSION_ENVELOPE_FILE}"))
    if len(matches) != 1:
        raise HandoffError(
            "cannot identify one active session envelope; run this command inside "
            "a DevLab role session or pass --session-envelope",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    return matches[0].resolve()


def initialize_handoff_candidate(
    root: Path, explicit_envelope: Path | None = None
) -> Path:
    envelope_path = active_session_envelope(root.resolve(), explicit_envelope)
    envelope = load_session_envelope(envelope_path)
    candidate_path = envelope_path.with_name(HANDOFF_CANDIDATE_FILE)
    _atomic_write(candidate_path, render_candidate_template(envelope.role))
    return candidate_path


def parse_handoff_candidate(path: Path, role_name: str) -> HandoffCandidate:
    if not path.exists():
        raise HandoffSubmissionError((f"candidate file does not exist: {path}",))
    if path.stat().st_size > MAX_CANDIDATE_BYTES:
        raise HandoffSubmissionError(
            (f"candidate exceeds the {MAX_CANDIDATE_BYTES}-byte limit",),
            reason=HandoffFailureReason.SAFETY_LIMIT,
        )
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, UnicodeError) as exc:
        raise HandoffSubmissionError(
            (f"candidate cannot be read: {exc}",),
            reason=HandoffFailureReason.SYNTAX,
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise HandoffSubmissionError(
            (f"candidate is not valid TOML: {exc}",),
            reason=HandoffFailureReason.SYNTAX,
        ) from exc
    return _candidate_from_data(data, role_name)


def publish_session_result(
    envelope_path: Path,
    envelope: SessionEnvelope,
    candidate: HandoffCandidate,
) -> SessionResult:
    """Atomically publish validated structured and rendered session artifacts."""
    result = SessionResult(envelope=envelope, candidate=candidate)
    artifacts = envelope_path.parent
    _atomic_write(artifacts / HANDOFF_FILE, render_handoff(candidate, envelope.role))
    # Publish the structured acceptance marker last. The outer orchestrator can
    # reconstruct Markdown from it if publication is interrupted between files.
    _atomic_write(artifacts / SESSION_RESULT_FILE, _render_result(result))
    return result


def record_submission_attempt(
    envelope_path: Path,
    *,
    accepted: bool,
    issues: tuple[str, ...] = (),
) -> None:
    """Append compact per-session acceptance evidence for diagnostics."""
    path = envelope_path.with_name("submission-attempts.jsonl")
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "accepted": accepted,
        "issues": list(issues),
    }
    with path.open("a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def submission_attempt_count(envelope_path: Path) -> int:
    path = envelope_path.with_name("submission-attempts.jsonl")
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text().splitlines() if line.strip())
    except OSError as exc:
        raise HandoffError(
            f"cannot read submission attempt history: {exc}",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        ) from exc


def load_session_result(path: Path) -> SessionResult:
    data = _load_toml_file(path, "session result")
    identity_keys = {
        "session_id",
        "role",
        "task",
        "milestone",
        "protected_active_tasks",
        "incremental_planning_required",
        "allow_active_task_replacement",
    }
    missing = identity_keys - set(data)
    if missing:
        raise HandoffError(
            "session result is missing identity field(s): " + ", ".join(sorted(missing)),
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    envelope = SessionEnvelope(
        schema_version=_required_int(data, "schema_version", "session result"),
        session_id=_required_string(data, "session_id", "session result"),
        role=_required_string(data, "role", "session result"),
        task=_optional_string(data, "task", "session result"),
        milestone=_optional_string(data, "milestone", "session result"),
        protected_active_tasks=_required_string_tuple(
            data, "protected_active_tasks", "session result"
        ),
        incremental_planning_required=_required_bool(
            data, "incremental_planning_required", "session result"
        ),
        allow_active_task_replacement=_required_bool(
            data, "allow_active_task_replacement", "session result"
        ),
    )
    candidate_data = {key: value for key, value in data.items() if key not in identity_keys}
    candidate = _candidate_from_data(candidate_data, envelope.role)
    return SessionResult(envelope=envelope, candidate=candidate)


def render_candidate_template(role_name: str) -> str:
    lines = [
        f"schema_version = {SESSION_RESULT_SCHEMA_VERSION}",
        'outcome = "completed"',
        'commit_message = ""',
        "done = []",
        "changed_artifacts = []",
        "open_issues = []",
        "addressed_findings = []",
        'next_session_hint = ""',
    ]
    if role_name == "planner":
        lines.append("planning_complete = false")
    return "\n".join(lines) + "\n"


def render_handoff(candidate: HandoffCandidate, role_name: str) -> str:
    parts = [
        f"# Handoff: {role_name}",
        "## Done\n" + _markdown_list(candidate.done),
        "## Changed Artifacts\n" + _markdown_list(candidate.changed_artifacts),
        "## Open Issues\n" + _markdown_list(candidate.open_issues),
        "## Addressed Findings\n" + _markdown_list(candidate.addressed_findings),
        "## Next Session Hint\n" + candidate.next_session_hint.strip(),
        "## Commit Message\n" + (candidate.commit_message.strip() or "- None"),
    ]
    if role_name == "planner":
        value = "true" if candidate.planning_complete else "false"
        parts.append(f"## Planning State\nplanning_complete = {value}")
    if candidate.clarification is not None:
        clarification = candidate.clarification
        header = [
            "clarification_required = true",
            f"title = {_toml_string(clarification.title)}",
            f"scope = {_toml_string(clarification.scope)}",
            f"blocks = {_toml_string(clarification.blocks)}",
            f"answer_shape = {_toml_string(clarification.answer_shape)}",
        ]
        if clarification.recommended_option:
            header.append(
                f"recommended_option = {_toml_string(clarification.recommended_option)}"
            )
        parts.append(
            "## Clarification Request\n"
            + "\n".join(header)
            + "\n\n"
            + clarification.details.strip()
        )
    return "\n\n".join(parts) + "\n"


def candidate_from_handoff(handoff: Handoff) -> HandoffCandidate:
    """Adapt a parsed legacy handoff for test providers and migration tooling."""
    clarification = handoff.clarification_request
    return HandoffCandidate(
        schema_version=SESSION_RESULT_SCHEMA_VERSION,
        outcome="needs_clarification" if clarification is not None else "completed",
        commit_message=handoff.commit_message,
        done=_section_entries(handoff.section("Done")),
        changed_artifacts=_section_entries(handoff.section("Changed Artifacts")),
        open_issues=_section_entries(handoff.section("Open Issues")),
        addressed_findings=_section_entries(handoff.section("Addressed Findings")),
        next_session_hint=handoff.section("Next Session Hint").strip(),
        planning_complete=handoff.planning_complete,
        clarification=clarification,
    )


def parse_handoff(path: Path, role_name: str) -> Handoff:
    """Parse and validate a handoff file."""
    if not path.exists():
        raise HandoffError("handoff file does not exist")
    text = path.read_text()
    if not text.strip():
        raise HandoffError("handoff file is empty")
    return Handoff(path=path, role_name=role_name, sections=_parse_sections(text, role_name))


def validate_handoff_contract(path: Path, role_name: str) -> tuple[bool, str]:
    try:
        parse_handoff(path, role_name)
    except HandoffError as exc:
        return False, str(exc)
    return True, ""


def section_is_none(section: str) -> bool:
    lines = _meaningful_lines(section)
    return len(lines) == 1 and lines[0].lower() in _NONE_LINES


def first_commit_message_line(section: str) -> str:
    for line in _meaningful_lines(section):
        return line.removeprefix("- ").strip()
    return ""


def parse_planning_state(section: str) -> bool:
    try:
        data = tomllib.loads(section)
    except tomllib.TOMLDecodeError as exc:
        raise HandoffError("handoff section ## Planning State must be TOML") from exc
    if set(data) != {"planning_complete"}:
        raise HandoffError(
            "handoff section ## Planning State must contain only planning_complete"
        )
    planning_complete = data["planning_complete"]
    if not isinstance(planning_complete, bool):
        raise HandoffError(
            "handoff section ## Planning State planning_complete must be a boolean"
        )
    return planning_complete


def parse_clarification_request(section: str) -> ClarificationRequest:
    header, details = _split_clarification_request(section)
    try:
        data = tomllib.loads(header)
    except tomllib.TOMLDecodeError as exc:
        raise HandoffError(
            "handoff section ## Clarification Request must start with TOML"
        ) from exc
    required = {"clarification_required", "title", "scope", "blocks", "answer_shape"}
    missing = sorted(required - set(data))
    if missing:
        raise HandoffError(
            "handoff section ## Clarification Request is missing required key(s): "
            + ", ".join(missing)
        )
    if data.get("clarification_required") is not True:
        raise HandoffError(
            "handoff section ## Clarification Request clarification_required must be true"
        )
    title = _clarification_string(data, "title")
    scope = _clarification_string(data, "scope")
    blocks = _clarification_string(data, "blocks")
    answer_shape = _clarification_string(data, "answer_shape")
    recommended_option = str(data.get("recommended_option") or "")
    if answer_shape == "choice" and not recommended_option:
        raise HandoffError(
            "handoff section ## Clarification Request choice requires recommended_option"
        )
    _validate_clarification_scope(scope)
    _validate_clarification_blocks(blocks)
    if answer_shape not in {"choice", "text", "file-edit"}:
        raise HandoffError(
            "handoff section ## Clarification Request answer_shape must be one of: "
            "choice, text, file-edit"
        )
    _require_clarification_detail(details, "Context")
    _require_clarification_detail(details, "Question")
    if answer_shape == "choice":
        _require_clarification_detail(details, "Options")
        _validate_recommended_clarification_option(details, recommended_option)
    elif answer_shape == "file-edit":
        _require_clarification_detail(details, "Expected File Edits")
        normalized = re.sub(r"^### ", "## ", details, flags=re.MULTILINE)
        try:
            expected_file_edit_paths(normalized)
        except ValueError as exc:
            raise HandoffError(str(exc)) from exc
    else:
        _require_clarification_detail(details, "Expected Answer")
    return ClarificationRequest(
        title=title,
        scope=scope,
        blocks=blocks,
        answer_shape=answer_shape,
        recommended_option=recommended_option,
        details=details.strip(),
    )


def addressed_finding_tasks(section: str) -> dict[str, tuple[str, ...]]:
    lines = _meaningful_lines(section)
    if len(lines) == 1 and lines[0].lower() in _NONE_LINES:
        return {}
    mappings: dict[str, tuple[str, ...]] = {}
    for line in lines:
        match = _ADDRESSED_FINDING_LINE_RE.fullmatch(line)
        if match is None:
            continue
        mappings[match.group("finding")] = tuple(
            task.strip() for task in match.group("tasks").split(",")
        )
    return mappings


def _parse_sections(text: str, role_name: str) -> dict[str, str]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        raise HandoffError("handoff is missing required heading(s): " + ", ".join(
            f"## {heading}" for heading in REQUIRED_HANDOFF_HEADINGS
        ))

    headings = [match.group("heading").strip() for match in matches]
    recognized_headings = set(REQUIRED_HANDOFF_HEADINGS) | set(OPTIONAL_HANDOFF_HEADINGS)
    for heading in recognized_headings:
        if headings.count(heading) > 1:
            if heading in REQUIRED_HANDOFF_HEADINGS:
                raise HandoffError(
                    f"handoff has duplicate required heading: ## {heading}"
                )
            raise HandoffError(f"handoff has duplicate heading: ## {heading}")

    missing = [heading for heading in REQUIRED_HANDOFF_HEADINGS if heading not in headings]
    if missing:
        raise HandoffError(
            "handoff is missing required heading(s): "
            + ", ".join(f"## {heading}" for heading in missing)
        )

    required_positions = [headings.index(heading) for heading in REQUIRED_HANDOFF_HEADINGS]
    if required_positions != sorted(required_positions):
        raise HandoffError("handoff required headings are not in the required order")
    expected_positions = list(
        range(required_positions[0], required_positions[0] + len(REQUIRED_HANDOFF_HEADINGS))
    )
    if required_positions != expected_positions:
        raise HandoffError("handoff has unexpected ## section between required headings")

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = headings[index]
        if heading not in recognized_headings:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[match.end() : end].strip()
        if heading in REQUIRED_HANDOFF_HEADINGS and not content:
            raise HandoffError(f"handoff section ## {heading} is empty")
        sections[heading] = content

    _validate_none_section(sections["Open Issues"], "Open Issues")
    _validate_addressed_findings_section(sections["Addressed Findings"])
    _validate_planning_state_section(sections, role_name)
    if sections.get("Clarification Request"):
        parse_clarification_request(sections["Clarification Request"])
    return sections


def _validate_planning_state_section(sections: dict[str, str], role_name: str) -> None:
    section = sections.get("Planning State", "")
    if role_name == "planner":
        if not section:
            raise HandoffError(
                "planner handoff is missing required heading: ## Planning State"
            )
        parse_planning_state(section)
        return
    if section:
        raise HandoffError(
            "handoff section ## Planning State is only allowed for planner handoffs"
        )


def _validate_none_section(section: str, heading: str) -> None:
    lines = _meaningful_lines(section)
    none_lines = [line for line in lines if line.lower() in _NONE_LINES]
    if none_lines and not section_is_none(section):
        raise HandoffError(f"handoff section ## {heading} mixes None with real content")


def _validate_addressed_findings_section(section: str) -> None:
    lines = _meaningful_lines(section)
    if not lines:
        raise HandoffError("handoff section ## Addressed Findings is empty")
    if section_is_none(section):
        return
    if any(line.lower() in _NONE_LINES for line in lines):
        raise HandoffError(
            "handoff section ## Addressed Findings cannot mix '- None' with finding mappings"
        )
    seen_findings: set[str] = set()
    for line in lines:
        match = _ADDRESSED_FINDING_LINE_RE.fullmatch(line)
        if match is None:
            raise HandoffError(
                "Addressed Findings entries must use '- FXXXX: TXXXX[, TXXXX]'"
            )
        finding_id = match.group("finding")
        if finding_id in seen_findings:
            raise HandoffError(f"Addressed Findings lists {finding_id} more than once")
        seen_findings.add(finding_id)
        task_ids = [task.strip() for task in match.group("tasks").split(",")]
        if len(set(task_ids)) != len(task_ids):
            raise HandoffError(f"Addressed Findings lists duplicate task for {finding_id}")


def _meaningful_lines(section: str) -> list[str]:
    return [line.strip() for line in section.splitlines() if line.strip()]


def _split_clarification_request(section: str) -> tuple[str, str]:
    match = re.search(r"^###\s+", section, flags=re.MULTILINE)
    if match is None:
        raise HandoffError(
            "handoff section ## Clarification Request must contain Markdown details"
        )
    header = section[: match.start()].strip()
    details = section[match.start() :].strip()
    if not header:
        raise HandoffError("handoff section ## Clarification Request is missing TOML")
    return header, details


def _clarification_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(
            f"handoff section ## Clarification Request {key} must be a non-empty string"
        )
    value = value.strip()
    if key == "title" and ("\n" in value or "\r" in value):
        raise HandoffError(
            "handoff section ## Clarification Request title must be a single line"
        )
    if key == "title" and len(value) > 160:
        raise HandoffError(
            "handoff section ## Clarification Request title must be at most 160 characters"
        )
    return value


def _validate_clarification_scope(scope: str) -> None:
    if re.fullmatch(
        r"workspace|planning|milestone:[A-Za-z0-9_.-]+|task:T\d{3,5}|finding:F\d{4,5}",
        scope,
    ) is None:
        raise HandoffError(f"invalid clarification scope: {scope}")


def _validate_clarification_blocks(blocks: str) -> None:
    if re.fullmatch(
        r"planning|implementation|milestone:[A-Za-z0-9_.-]+|task:T\d{3,5}|none",
        blocks,
    ) is None:
        raise HandoffError(f"invalid clarification blocks: {blocks}")


def _require_clarification_detail(details: str, heading: str) -> None:
    pattern = rf"^### {re.escape(heading)}[ \t]*$([\s\S]*?)(?=^###\s|\Z)"
    match = re.search(pattern, details, flags=re.MULTILINE)
    if match is None or not match.group(1).strip():
        raise HandoffError(
            f"handoff section ## Clarification Request is missing ### {heading}"
        )


def _validate_recommended_clarification_option(
    details: str, recommended_option: str
) -> None:
    options = _clarification_detail(details, "Options")
    pattern = re.compile(
        rf"^\s*[-*]\s+{re.escape(recommended_option)}:\s+.+$", re.MULTILINE
    )
    if pattern.search(options) is None:
        raise HandoffError(
            "handoff section ## Clarification Request recommended_option "
            f"{recommended_option!r} must match one listed option"
        )


def _clarification_detail(details: str, heading: str) -> str:
    pattern = rf"^### {re.escape(heading)}[ \t]*$([\s\S]*?)(?=^###\s|\Z)"
    match = re.search(pattern, details, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _candidate_from_data(data: dict[str, object], role_name: str) -> HandoffCandidate:
    common = {
        "schema_version",
        "outcome",
        "commit_message",
        "done",
        "changed_artifacts",
        "open_issues",
        "addressed_findings",
        "next_session_hint",
        "clarification",
    }
    allowed = common | ({"planning_complete"} if role_name == "planner" else set())
    issues: list[str] = []
    unexpected = sorted(set(data) - allowed)
    if unexpected:
        issues.append("unexpected field(s): " + ", ".join(unexpected))

    schema_version = _candidate_int(data, "schema_version", issues)
    if schema_version is not None and schema_version != SESSION_RESULT_SCHEMA_VERSION:
        issues.append(f"unsupported schema_version: {schema_version}")
    outcome = _candidate_string(data, "outcome", issues)
    if outcome and outcome not in {"completed", "needs_clarification", "failed"}:
        issues.append("outcome must be one of: completed, needs_clarification, failed")
    commit_message = _candidate_string(data, "commit_message", issues, allow_empty=True)
    if "\n" in commit_message or "\r" in commit_message:
        issues.append("commit_message must be a single line")
    done = _candidate_string_list(data, "done", issues, allow_empty=False)
    changed_artifacts = _candidate_string_list(
        data, "changed_artifacts", issues, allow_empty=True
    )
    open_issues = _candidate_string_list(data, "open_issues", issues, allow_empty=True)
    addressed_findings = _candidate_string_list(
        data, "addressed_findings", issues, allow_empty=True
    )
    next_session_hint = _candidate_string(data, "next_session_hint", issues)

    planning_complete: bool | None = None
    if role_name == "planner":
        value = data.get("planning_complete")
        if not isinstance(value, bool):
            issues.append("planning_complete must be a boolean for planner sessions")
        else:
            planning_complete = value

    clarification = _candidate_clarification(data.get("clarification"), issues)
    if outcome == "needs_clarification" and clarification is None:
        issues.append("outcome needs_clarification requires [clarification]")
    if outcome != "needs_clarification" and clarification is not None:
        issues.append("[clarification] is only allowed for outcome needs_clarification")
    if outcome == "failed" and not open_issues:
        issues.append("outcome failed requires at least one open_issues entry")

    for entry in addressed_findings:
        if _ADDRESSED_FINDING_LINE_RE.fullmatch(f"- {entry}") is None:
            issues.append(
                "addressed_findings entries must use 'FXXXX: TXXXX[, TXXXX]'"
            )
            break
    if issues:
        raise HandoffSubmissionError(tuple(issues))
    return HandoffCandidate(
        schema_version=schema_version or SESSION_RESULT_SCHEMA_VERSION,
        outcome=outcome,
        commit_message=commit_message,
        done=done,
        changed_artifacts=changed_artifacts,
        open_issues=open_issues,
        addressed_findings=addressed_findings,
        next_session_hint=next_session_hint,
        planning_complete=planning_complete,
        clarification=clarification,
    )


def _candidate_clarification(
    value: object, issues: list[str]
) -> ClarificationRequest | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        issues.append("clarification must be a TOML table")
        return None
    value = cast(dict[str, object], value)
    expected = {
        "title",
        "scope",
        "blocks",
        "answer_shape",
        "recommended_option",
        "details",
    }
    unexpected = sorted(set(value) - expected)
    if unexpected:
        issues.append("clarification has unexpected field(s): " + ", ".join(unexpected))
    local: list[str] = []
    title = _candidate_string(value, "title", local)
    scope = _candidate_string(value, "scope", local)
    blocks = _candidate_string(value, "blocks", local)
    answer_shape = _candidate_string(value, "answer_shape", local)
    recommended = _candidate_string(
        value, "recommended_option", local, allow_empty=True
    )
    details = _candidate_string(value, "details", local)
    if local:
        issues.extend(f"clarification.{issue}" for issue in local)
        return None
    request = ClarificationRequest(
        title=title,
        scope=scope,
        blocks=blocks,
        answer_shape=answer_shape,
        recommended_option=recommended,
        details=details,
    )
    header = [
        "clarification_required = true",
        f"title = {_toml_string(title)}",
        f"scope = {_toml_string(scope)}",
        f"blocks = {_toml_string(blocks)}",
        f"answer_shape = {_toml_string(answer_shape)}",
    ]
    if recommended:
        header.append(f"recommended_option = {_toml_string(recommended)}")
    try:
        parse_clarification_request("\n".join(header) + "\n\n" + details)
    except HandoffError as exc:
        issues.append(f"clarification: {exc}")
        return None
    return request


def _candidate_int(data: dict[str, object], key: str, issues: list[str]) -> int | None:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        issues.append(f"{key} must be an integer")
        return None
    return value


def _candidate_string(
    data: dict[str, object],
    key: str,
    issues: list[str],
    *,
    allow_empty: bool = False,
) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        issues.append(f"{key} must be a string")
        return ""
    if not allow_empty and not value.strip():
        issues.append(f"{key} must be non-empty")
    return value.strip()


def _candidate_string_list(
    data: dict[str, object],
    key: str,
    issues: list[str],
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        issues.append(f"{key} must be an array of non-empty strings")
        return ()
    entries: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            issues.append(f"{key} must be an array of non-empty strings")
            return ()
        entries.append(entry.strip())
    if not allow_empty and not value:
        issues.append(f"{key} must contain at least one entry")
    return tuple(entries)


def _load_toml_file(path: Path, label: str) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise HandoffError(
            f"{label} does not exist: {path}",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        ) from exc
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise HandoffError(
            f"{label} is invalid: {exc}",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        ) from exc


def _required_int(data: dict[str, object], key: str, label: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HandoffError(
            f"{label} field {key} must be an integer",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    return value


def _required_string(data: dict[str, object], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(
            f"{label} field {key} must be a non-empty string",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    return value.strip()


def _required_string_tuple(
    data: dict[str, object], key: str, label: str
) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        raise HandoffError(
            f"{label} field {key} must be an array of strings",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise HandoffError(
                f"{label} field {key} must be an array of strings",
                reason=HandoffFailureReason.SESSION_PROTOCOL,
            )
        items.append(item.strip())
    return tuple(items)


def _required_bool(data: dict[str, object], key: str, label: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise HandoffError(
            f"{label} field {key} must be a boolean",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    return value


def _optional_string(data: dict[str, object], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise HandoffError(
            f"{label} field {key} must be a string",
            reason=HandoffFailureReason.SESSION_PROTOCOL,
        )
    return value.strip()


def _render_envelope(envelope: SessionEnvelope) -> str:
    return (
        f"schema_version = {envelope.schema_version}\n"
        f"session_id = {_toml_string(envelope.session_id)}\n"
        f"role = {_toml_string(envelope.role)}\n"
        f"task = {_toml_string(envelope.task)}\n"
        f"milestone = {_toml_string(envelope.milestone)}\n"
        f"protected_active_tasks = {_toml_array(envelope.protected_active_tasks)}\n"
        "incremental_planning_required = "
        f"{'true' if envelope.incremental_planning_required else 'false'}\n"
        "allow_active_task_replacement = "
        f"{'true' if envelope.allow_active_task_replacement else 'false'}\n"
    )


def _render_result(result: SessionResult) -> str:
    candidate = result.candidate
    lines = [
        f"schema_version = {candidate.schema_version}",
        f"session_id = {_toml_string(result.envelope.session_id)}",
        f"role = {_toml_string(result.envelope.role)}",
        f"task = {_toml_string(result.envelope.task)}",
        f"milestone = {_toml_string(result.envelope.milestone)}",
        "protected_active_tasks = "
        f"{_toml_array(result.envelope.protected_active_tasks)}",
        "incremental_planning_required = "
        + ("true" if result.envelope.incremental_planning_required else "false"),
        "allow_active_task_replacement = "
        + ("true" if result.envelope.allow_active_task_replacement else "false"),
        f"outcome = {_toml_string(candidate.outcome)}",
        f"commit_message = {_toml_string(candidate.commit_message)}",
        f"done = {_toml_array(candidate.done)}",
        f"changed_artifacts = {_toml_array(candidate.changed_artifacts)}",
        f"open_issues = {_toml_array(candidate.open_issues)}",
        f"addressed_findings = {_toml_array(candidate.addressed_findings)}",
        f"next_session_hint = {_toml_string(candidate.next_session_hint)}",
    ]
    if candidate.planning_complete is not None:
        lines.append(
            "planning_complete = " + ("true" if candidate.planning_complete else "false")
        )
    if candidate.clarification is not None:
        clarification = candidate.clarification
        lines.extend(
            [
                "",
                "[clarification]",
                f"title = {_toml_string(clarification.title)}",
                f"scope = {_toml_string(clarification.scope)}",
                f"blocks = {_toml_string(clarification.blocks)}",
                f"answer_shape = {_toml_string(clarification.answer_shape)}",
                f"recommended_option = {_toml_string(clarification.recommended_option)}",
                f"details = {_toml_string(clarification.details)}",
            ]
        )
    return "\n".join(lines) + "\n"


def _markdown_list(entries: tuple[str, ...]) -> str:
    return "\n".join(f"- {entry}" for entry in entries) if entries else "- None"


def _section_entries(section: str) -> tuple[str, ...]:
    if section_is_none(section):
        return ()
    return tuple(line.removeprefix("- ").strip() for line in _meaningful_lines(section))


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
