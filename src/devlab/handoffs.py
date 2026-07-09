from __future__ import annotations

import dataclasses
import re
import tomllib
from pathlib import Path

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
    elif answer_shape == "file-edit":
        _require_clarification_detail(details, "Expected File Edits")
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
    for required in REQUIRED_HANDOFF_HEADINGS:
        if headings.count(required) > 1:
            raise HandoffError(f"handoff has duplicate required heading: ## {required}")

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
    recognized_headings = set(REQUIRED_HANDOFF_HEADINGS) | set(OPTIONAL_HANDOFF_HEADINGS)
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
