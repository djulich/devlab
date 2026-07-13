from __future__ import annotations

import dataclasses
import re
import tomllib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from devlab._toml import format_toml_value

CLARIFICATIONS_DIR = ".devlab/clarifications"
CLARIFICATION_ID_RE = re.compile(r"(?<![A-Z0-9])CL\d{4,5}(?!\d)")
_FRONT_MATTER_RE = re.compile(r"\A\+\+\+\n([\s\S]*?)\n\+\+\+\n?", re.MULTILINE)
_SCOPE_RE = re.compile(
    r"^(workspace|planning|milestone:[A-Za-z0-9_.-]+|task:T\d{3,5}|finding:F\d{4,5})$"
)
_BLOCKS_RE = re.compile(
    r"^(planning|implementation|milestone:[A-Za-z0-9_.-]+|task:T\d{3,5}|none)$"
)


class ClarificationStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    SUPERSEDED = "superseded"


class ClarificationAnswerShape(StrEnum):
    CHOICE = "choice"
    TEXT = "text"
    FILE_EDIT = "file-edit"


@dataclasses.dataclass(frozen=True)
class Clarification:
    id: str
    title: str
    status: ClarificationStatus
    path: Path
    asking_role: str
    session_id: str
    scope: str
    blocks: str
    answer_shape: ClarificationAnswerShape
    recommended_option: str
    decision_refs: tuple[str, ...]
    created_at: str
    answered_at: str | None
    body: str
    metadata: dict[str, Any]

    @property
    def is_blocking(self) -> bool:
        return self.status == ClarificationStatus.PENDING and self.blocks != "none"

    @property
    def answer_text(self) -> str:
        return _markdown_section(self.body, "Answer")


class FileClarificationTracker:
    """File-backed operator clarification tracker."""

    def __init__(self, root: Path, clarifications_dir: str = CLARIFICATIONS_DIR) -> None:
        self.root = root
        self.clarifications_path = root / clarifications_dir

    def list_clarifications(self) -> list[Clarification]:
        return sorted(
            (
                self._read_clarification(path)
                for path in self.clarifications_path.glob("CL*.md")
            ),
            key=lambda clarification: (
                _clarification_sort_key(clarification.id),
                clarification.path.name,
            ),
        )

    def get(self, clarification_id: str) -> Clarification:
        for clarification in self.list_clarifications():
            if clarification.id == clarification_id:
                return clarification
        raise KeyError(f"unknown clarification id: {clarification_id}")

    def read_path(self, path: Path) -> Clarification:
        return self._read_clarification(path)

    def pending(self) -> list[Clarification]:
        return [
            clarification
            for clarification in self.list_clarifications()
            if clarification.status == ClarificationStatus.PENDING
        ]

    def answered(self) -> list[Clarification]:
        return [
            clarification
            for clarification in self.list_clarifications()
            if clarification.status == ClarificationStatus.ANSWERED
        ]

    def blocking(self) -> list[Clarification]:
        return [
            clarification
            for clarification in self.pending()
            if clarification.blocks != "none"
        ]

    def create(
        self,
        *,
        title: str,
        asking_role: str,
        session_id: str,
        scope: str,
        blocks: str,
        answer_shape: ClarificationAnswerShape | str,
        body: str,
        recommended_option: str = "",
        decision_refs: tuple[str, ...] | list[str] = (),
        created_at: str | None = None,
    ) -> Clarification:
        shape = _parse_answer_shape(answer_shape)
        _validate_scope(scope)
        _validate_blocks(blocks)
        if shape == ClarificationAnswerShape.CHOICE and not recommended_option:
            raise ValueError("choice clarification requires recommended_option")
        if shape == ClarificationAnswerShape.CHOICE:
            _validate_recommended_option(body, recommended_option)
        self.clarifications_path.mkdir(parents=True, exist_ok=True)
        clarification_id = self._next_clarification_id()
        path = self.clarifications_path / f"{clarification_id}_{_slugify(title)}.md"
        metadata: dict[str, Any] = {
            "id": clarification_id,
            "title": title,
            "status": ClarificationStatus.PENDING.value,
            "asking_role": asking_role,
            "session_id": session_id,
            "scope": scope,
            "blocks": blocks,
            "answer_shape": shape.value,
            "recommended_option": recommended_option,
            "decision_refs": list(decision_refs),
            "created_at": created_at or _utc_now(),
        }
        path.write_text(_format_clarification_file(metadata, _body_with_pending_answer(body)))
        return self._read_clarification(path)

    def answer(
        self,
        clarification_id: str,
        answer: str,
        *,
        operator: str = "",
        answered_at: str | None = None,
    ) -> Clarification:
        clarification = self.get(clarification_id)
        if clarification.status != ClarificationStatus.PENDING:
            raise ValueError(f"clarification {clarification_id} is not pending")
        if not answer.strip():
            raise ValueError("clarification answer must not be empty")
        metadata = dict(clarification.metadata)
        metadata["status"] = ClarificationStatus.ANSWERED.value
        metadata["answered_at"] = answered_at or _utc_now()
        if operator:
            metadata["answered_by"] = operator
        body = _replace_markdown_section(clarification.body, "Answer", answer.strip())
        clarification.path.write_text(_format_clarification_file(metadata, body))
        return self._read_clarification(clarification.path)

    def answer_choice(
        self,
        clarification_id: str,
        choice: str,
        *,
        note: str = "",
        operator: str = "",
        answered_at: str | None = None,
    ) -> Clarification:
        clarification = self.get(clarification_id)
        if clarification.answer_shape != ClarificationAnswerShape.CHOICE:
            raise ValueError(f"clarification {clarification_id} does not accept a choice answer")
        option = option_text(clarification.body, choice)
        if option is None:
            raise ValueError(f"unknown clarification option: {choice}")
        answer = option
        if note.strip():
            answer = f"{answer}\n\nOperator note: {note.strip()}"
        return self.answer(
            clarification_id,
            answer,
            operator=operator,
            answered_at=answered_at,
        )

    def supersede(
        self,
        clarification_id: str,
        reason: str,
        *,
        superseded_at: str | None = None,
    ) -> Clarification:
        if not reason.strip():
            raise ValueError("supersede reason must not be empty")
        clarification = self.get(clarification_id)
        metadata = dict(clarification.metadata)
        metadata["status"] = ClarificationStatus.SUPERSEDED.value
        metadata["superseded_at"] = superseded_at or _utc_now()
        body = clarification.body.rstrip() + "\n\n## Superseded\n" + reason.strip() + "\n"
        clarification.path.write_text(_format_clarification_file(metadata, body))
        return self._read_clarification(clarification.path)

    def _next_clarification_id(self) -> str:
        max_id = 0
        for clarification in self.list_clarifications():
            match = re.search(r"\d+", clarification.id)
            if match:
                max_id = max(max_id, int(match.group(0)))
        return f"CL{max_id + 1:04d}"

    def _read_clarification(self, path: Path) -> Clarification:
        text = path.read_text()
        metadata, body = _split_front_matter(text)
        clarification_id = str(metadata.get("id") or _clarification_id_from_path(path) or "")
        if not clarification_id:
            raise ValueError(f"clarification file has no clarification id: {path}")
        if CLARIFICATION_ID_RE.fullmatch(clarification_id) is None:
            raise ValueError(f"invalid clarification id: {clarification_id}")
        title = str(
            metadata.get("title")
            or _title_from_body(body, clarification_id)
            or clarification_id
        )
        status = _parse_status(metadata.get("status"))
        asking_role = _required_string(metadata, "asking_role", path)
        session_id = _required_string(metadata, "session_id", path)
        scope = _required_string(metadata, "scope", path)
        blocks = _required_string(metadata, "blocks", path)
        _validate_scope(scope)
        _validate_blocks(blocks)
        answer_shape = _parse_answer_shape(metadata.get("answer_shape"))
        recommended_option = str(metadata.get("recommended_option") or "")
        if answer_shape == ClarificationAnswerShape.CHOICE and not recommended_option:
            raise ValueError("choice clarification requires recommended_option")
        if answer_shape == ClarificationAnswerShape.CHOICE:
            _validate_recommended_option(body, recommended_option)
        decision_refs = _parse_string_list(metadata.get("decision_refs", []), "decision_refs")
        created_at = _required_string(metadata, "created_at", path)
        answered_at_value = metadata.get("answered_at")
        answered_at = str(answered_at_value) if answered_at_value is not None else None
        if status == ClarificationStatus.PENDING and answered_at is not None:
            raise ValueError("pending clarification must not include answered_at")
        if status == ClarificationStatus.ANSWERED and not answered_at:
            raise ValueError("answered clarification requires answered_at")
        if status == ClarificationStatus.ANSWERED and not _markdown_section(body, "Answer"):
            raise ValueError("answered clarification requires a non-empty ## Answer section")
        normalized_metadata = dict(metadata)
        normalized_metadata["id"] = clarification_id
        normalized_metadata["title"] = title
        normalized_metadata["status"] = status.value
        normalized_metadata["asking_role"] = asking_role
        normalized_metadata["session_id"] = session_id
        normalized_metadata["scope"] = scope
        normalized_metadata["blocks"] = blocks
        normalized_metadata["answer_shape"] = answer_shape.value
        normalized_metadata["recommended_option"] = recommended_option
        normalized_metadata["decision_refs"] = list(decision_refs)
        normalized_metadata["created_at"] = created_at
        return Clarification(
            id=clarification_id,
            title=title,
            status=status,
            path=path,
            asking_role=asking_role,
            session_id=session_id,
            scope=scope,
            blocks=blocks,
            answer_shape=answer_shape,
            recommended_option=recommended_option,
            decision_refs=tuple(decision_refs),
            created_at=created_at,
            answered_at=answered_at,
            body=body,
            metadata=normalized_metadata,
        )


def option_text(body: str, choice: str) -> str | None:
    choice = choice.strip()
    for option in choice_option_texts(body):
        if option.startswith(f"{choice}:"):
            return option
    return None


def choice_option_texts(body: str) -> tuple[str, ...]:
    options = _markdown_section(body, "Options")
    parsed: list[str] = []
    for line in options.splitlines():
        match = re.match(r"^\s*[-*]\s+([A-Za-z0-9_.-]+):\s*(.+?)\s*$", line)
        if match is not None:
            parsed.append(f"{match.group(1).strip()}: {match.group(2).strip()}")
    return tuple(parsed)


def _validate_recommended_option(body: str, recommended_option: str) -> None:
    if option_text(body, recommended_option) is None:
        raise ValueError(
            f"choice clarification recommended_option {recommended_option!r} "
            "must match one listed option"
        )


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    metadata = tomllib.loads(match.group(1))
    return metadata, text[match.end() :]


def _format_clarification_file(metadata: dict[str, Any], body: str) -> str:
    keys = (
        "id",
        "title",
        "status",
        "asking_role",
        "session_id",
        "scope",
        "blocks",
        "answer_shape",
        "recommended_option",
        "decision_refs",
        "created_at",
        "answered_at",
        "answered_by",
        "superseded_at",
    )
    lines = ["+++"]
    for key in keys:
        if key not in metadata:
            continue
        value = metadata[key]
        if value is None:
            continue
        lines.append(f"{key} = {format_toml_value(value)}")
    known_keys = set(keys)
    for key in sorted(k for k in metadata if k not in known_keys):
        lines.append(f"{key} = {format_toml_value(metadata[key])}")
    lines.append("+++")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")


def _parse_status(value: Any) -> ClarificationStatus:
    if value is None:
        return ClarificationStatus.PENDING
    try:
        return ClarificationStatus(str(value))
    except ValueError as exc:
        allowed = ", ".join(status.value for status in ClarificationStatus)
        raise ValueError(
            f"invalid clarification status {value!r}; expected one of: {allowed}"
        ) from exc


def _parse_answer_shape(value: Any) -> ClarificationAnswerShape:
    if value is None:
        raise ValueError("clarification front matter field 'answer_shape' is required")
    try:
        return ClarificationAnswerShape(str(value))
    except ValueError as exc:
        allowed = ", ".join(shape.value for shape in ClarificationAnswerShape)
        raise ValueError(
            f"invalid clarification answer_shape {value!r}; expected one of: {allowed}"
        ) from exc


def _validate_scope(scope: str) -> None:
    if _SCOPE_RE.fullmatch(scope) is None:
        raise ValueError(f"invalid clarification scope: {scope}")


def _validate_blocks(blocks: str) -> None:
    if _BLOCKS_RE.fullmatch(blocks) is None:
        raise ValueError(f"invalid clarification blocks: {blocks}")


def _required_string(metadata: dict[str, Any], key: str, path: Path) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"clarification file {path} requires string field {key!r}")
    return value


def _parse_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"clarification front matter field {field!r} must be a list")
    return [str(item) for item in value]


def _markdown_section(text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}[ \t]*$([\s\S]*?)(?=^##\s|\Z)",
        text,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def _replace_markdown_section(text: str, heading: str, replacement: str) -> str:
    pattern = re.compile(
        rf"(^## {re.escape(heading)}[ \t]*$\n)([\s\S]*?)(?=^##\s|\Z)",
        flags=re.MULTILINE,
    )
    match = pattern.search(text)
    section = f"## {heading}\n{replacement.strip()}\n"
    if match is None:
        suffix = "\n\n" if text.strip() else ""
        return text.rstrip() + suffix + section
    return text[: match.start()] + section + text[match.end() :]


def _body_with_pending_answer(body: str) -> str:
    if _markdown_section(body, "Answer"):
        return body
    return body.rstrip() + "\n\n## Answer\n- Pending\n"


def _clarification_id_from_path(path: Path) -> str | None:
    match = CLARIFICATION_ID_RE.search(path.name)
    return match.group(0) if match else None


def _title_from_body(body: str, clarification_id: str) -> str | None:
    match = re.search(
        rf"^#\s+{re.escape(clarification_id)}:\s*(.+)$",
        body,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else None


def _clarification_sort_key(clarification_id: str) -> int:
    match = re.search(r"\d+", clarification_id)
    return int(match.group(0)) if match else 0


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "clarification"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
