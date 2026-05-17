from __future__ import annotations

from pathlib import Path

from devlab.knowledge import discover_project_knowledge


def test_discovers_root_context_and_adrs(tmp_path: Path) -> None:
    (tmp_path / "CONTEXT.md").write_text("# Context\n")
    adr_dir = tmp_path / "docs/adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0002-second.md").write_text("# Second\n")
    (adr_dir / "0001-first.md").write_text("# First\n")

    knowledge = discover_project_knowledge(tmp_path)

    assert knowledge.context_map is None
    assert [document.display_path for document in knowledge.contexts] == ["CONTEXT.md"]
    assert [document.display_path for document in knowledge.adrs] == [
        "docs/adr/0001-first.md",
        "docs/adr/0002-second.md",
    ]


def test_context_map_selects_linked_context_files(tmp_path: Path) -> None:
    (tmp_path / "CONTEXT.md").write_text("# Root context not used when map exists\n")
    (tmp_path / "CONTEXT-MAP.md").write_text(
        "# Context Map\n\n"
        "- [Ordering](./src/ordering/CONTEXT.md)\n"
        "- [Billing](./src/billing/CONTEXT.md#language)\n"
    )
    ordering = tmp_path / "src/ordering/CONTEXT.md"
    billing = tmp_path / "src/billing/CONTEXT.md"
    ordering.parent.mkdir(parents=True)
    billing.parent.mkdir(parents=True)
    ordering.write_text("# Ordering\n")
    billing.write_text("# Billing\n")

    knowledge = discover_project_knowledge(tmp_path)

    assert knowledge.context_map is not None
    assert knowledge.context_map.display_path == "CONTEXT-MAP.md"
    assert [document.display_path for document in knowledge.contexts] == [
        "src/ordering/CONTEXT.md",
        "src/billing/CONTEXT.md",
    ]
