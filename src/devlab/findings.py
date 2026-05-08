from __future__ import annotations

import dataclasses
import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

FINDINGS_DIR = ".devlab/findings"
FINDING_ID_RE = re.compile(r"(?<![A-Z0-9])F\d{4,5}(?!\d)")
_FRONT_MATTER_RE = re.compile(r"\A\+\+\+\n([\s\S]*?)\n\+\+\+\n?", re.MULTILINE)


class FindingStatus(StrEnum):
    OPEN = "open"
    PLANNED = "planned"
    RESOLVED = "resolved"


@dataclasses.dataclass(frozen=True)
class Finding:
    id: str
    title: str
    status: FindingStatus
    path: Path
    source: str
    milestone: str | None
    handoff: str | None
    body: str
    metadata: dict[str, Any]


class FileFindingTracker:
    """File-backed workflow findings discovered by DevLab roles."""

    def __init__(self, root: Path, findings_dir: str = FINDINGS_DIR) -> None:
        self.root = root
        self.findings_path = root / findings_dir

    def list_findings(self) -> list[Finding]:
        return sorted(
            (self._read_finding(path) for path in self.findings_path.glob("F*.md")),
            key=lambda finding: (_finding_sort_key(finding.id), finding.path.name),
        )

    def get(self, finding_id: str) -> Finding:
        for finding in self.list_findings():
            if finding.id == finding_id:
                return finding
        raise KeyError(f"unknown finding id: {finding_id}")

    def open_findings(self) -> list[Finding]:
        return [
            finding for finding in self.list_findings() if finding.status == FindingStatus.OPEN
        ]

    def planned_findings_for_milestone(self, milestone: str) -> list[Finding]:
        return [
            finding
            for finding in self.list_findings()
            if finding.status == FindingStatus.PLANNED and finding.milestone == milestone
        ]

    def create(
        self,
        *,
        title: str,
        source: str,
        milestone: str | None,
        body: str,
        handoff: str | None = None,
    ) -> Finding:
        self.findings_path.mkdir(parents=True, exist_ok=True)
        finding_id = self._next_finding_id()
        path = self.findings_path / f"{finding_id}_{_slugify(title)}.md"
        metadata: dict[str, Any] = {
            "id": finding_id,
            "title": title,
            "status": FindingStatus.OPEN.value,
            "source": source,
        }
        if milestone is not None:
            metadata["milestone"] = milestone
        if handoff is not None:
            metadata["handoff"] = handoff
        path.write_text(_format_finding_file(metadata, body))
        return self._read_finding(path)

    def create_from_handoff(
        self,
        *,
        source: str,
        milestone: str | None,
        handoff_path: Path,
    ) -> Finding:
        handoff_text = handoff_path.read_text()
        open_issues = _extract_section(handoff_text, "Open Issues") or handoff_text
        title = f"{source.title()} finding"
        if milestone:
            title = f"{milestone} {title}"
        body = (
            f"# {title}\n\n"
            "## Finding\n"
            f"{open_issues.strip()}\n\n"
            "## Requested Planning\n"
            "Create follow-up task(s) that address this finding.\n"
        )
        return self.create(
            title=title,
            source=source,
            milestone=milestone,
            body=body,
            handoff=handoff_path.name,
        )

    def mark_planned(self, finding_id: str) -> None:
        self.set_status(finding_id, FindingStatus.PLANNED)

    def mark_resolved(self, finding_id: str) -> None:
        self.set_status(finding_id, FindingStatus.RESOLVED)

    def set_status(self, finding_id: str, status: FindingStatus) -> None:
        finding = self.get(finding_id)
        metadata = dict(finding.metadata)
        metadata["status"] = status.value
        finding.path.write_text(_format_finding_file(metadata, finding.body))

    def _next_finding_id(self) -> str:
        max_id = 0
        for finding in self.list_findings():
            match = re.search(r"\d+", finding.id)
            if match:
                max_id = max(max_id, int(match.group(0)))
        return f"F{max_id + 1:04d}"

    def _read_finding(self, path: Path) -> Finding:
        text = path.read_text()
        metadata, body = _split_front_matter(text)
        finding_id = str(metadata.get("id") or _finding_id_from_path(path) or "")
        if not finding_id:
            raise ValueError(f"finding file has no finding id: {path}")
        title = str(metadata.get("title") or _title_from_body(body, finding_id) or finding_id)
        status = _parse_status(metadata.get("status"))
        source = str(metadata.get("source") or "unknown")
        milestone = metadata.get("milestone")
        handoff = metadata.get("handoff")
        normalized_metadata = dict(metadata)
        normalized_metadata["id"] = finding_id
        normalized_metadata["title"] = title
        normalized_metadata["status"] = status.value
        normalized_metadata["source"] = source
        return Finding(
            id=finding_id,
            title=title,
            status=status,
            path=path,
            source=source,
            milestone=str(milestone) if milestone is not None else None,
            handoff=str(handoff) if handoff is not None else None,
            body=body,
            metadata=normalized_metadata,
        )


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    metadata = tomllib.loads(match.group(1))
    return metadata, text[match.end() :]


def _format_finding_file(metadata: dict[str, Any], body: str) -> str:
    lines = ["+++"]
    for key in ("id", "title", "status", "source", "milestone", "handoff"):
        if key not in metadata:
            continue
        value = metadata[key]
        if value is None:
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    known_keys = {"id", "title", "status", "source", "milestone", "handoff"}
    for key in sorted(k for k in metadata if k not in known_keys):
        lines.append(f"{key} = {_toml_value(metadata[key])}")
    lines.append("+++")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, FindingStatus):
        return _toml_value(value.value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return _toml_value(str(value))


def _parse_status(value: Any) -> FindingStatus:
    if value is None:
        return FindingStatus.OPEN
    try:
        return FindingStatus(str(value))
    except ValueError as exc:
        allowed = ", ".join(status.value for status in FindingStatus)
        raise ValueError(f"invalid finding status {value!r}; expected one of: {allowed}") from exc


def _extract_section(text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}[ \t]*$([\s\S]*?)(?=^##\s|\Z)",
        text,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def _finding_id_from_path(path: Path) -> str | None:
    match = FINDING_ID_RE.search(path.name)
    return match.group(0) if match else None


def _title_from_body(body: str, finding_id: str) -> str | None:
    match = re.search(rf"^#\s+{re.escape(finding_id)}:\s*(.+)$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _finding_sort_key(finding_id: str) -> int:
    match = re.search(r"\d+", finding_id)
    return int(match.group(0)) if match else 0


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "finding"
