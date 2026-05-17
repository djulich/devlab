"""Read-only discovery of durable project knowledge files."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from devlab.workspace import read_file

ROOT_CONTEXT = "CONTEXT.md"
CONTEXT_MAP = "CONTEXT-MAP.md"
ADR_DIR = "docs/adr"
ADR_FILENAME_RE = re.compile(r"^(?P<number>\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@dataclasses.dataclass(frozen=True)
class KnowledgeDocument:
    """A target-owned project knowledge file discovered in the workspace."""

    path: Path
    display_path: str
    content: str


@dataclasses.dataclass(frozen=True)
class ProjectKnowledge:
    """Durable language and decision context for a target workspace."""

    context_map: KnowledgeDocument | None
    contexts: tuple[KnowledgeDocument, ...]
    adrs: tuple[KnowledgeDocument, ...]

    @property
    def documents(self) -> tuple[KnowledgeDocument, ...]:
        docs: list[KnowledgeDocument] = []
        if self.context_map is not None:
            docs.append(self.context_map)
        docs.extend(self.contexts)
        docs.extend(self.adrs)
        return tuple(docs)

    @property
    def has_documents(self) -> bool:
        return bool(self.documents)


def discover_project_knowledge(root: Path) -> ProjectKnowledge:
    """Discover target-owned context and ADR files without mutating the workspace."""

    context_map = _document(root, root / CONTEXT_MAP)
    contexts = _discover_contexts(root, context_map)
    adrs = [
        KnowledgeDocument(
            path=path,
            display_path=path.relative_to(root).as_posix(),
            content=read_file(path),
        )
        for path in sorted((root / ADR_DIR).glob("*.md"))
        if path.is_file()
    ]
    return ProjectKnowledge(
        context_map=context_map,
        contexts=tuple(doc for doc in contexts if doc is not None),
        adrs=tuple(adrs),
    )


def _discover_contexts(
    root: Path, context_map: KnowledgeDocument | None
) -> list[KnowledgeDocument | None]:
    if context_map is None:
        return [_document(root, root / ROOT_CONTEXT)]

    linked_paths = _context_paths_from_map(root, context_map.content)
    return [_document(root, path) for path in linked_paths]


def context_paths_from_map(root: Path, content: str) -> list[Path]:
    """Return in-workspace CONTEXT.md paths linked from a context map."""

    return _context_paths_from_map(root, content)


def _context_paths_from_map(root: Path, content: str) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for match in _MARKDOWN_LINK_RE.finditer(content):
        target = match.group(1).split("#", 1)[0]
        if not target.endswith("CONTEXT.md"):
            continue
        path = (root / target).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            continue
        if path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def _document(root: Path, path: Path) -> KnowledgeDocument | None:
    if not path.exists() or not path.is_file():
        return None
    return KnowledgeDocument(
        path=path,
        display_path=path.relative_to(root).as_posix(),
        content=read_file(path),
    )
