from __future__ import annotations

from devlab.prompt_resources import read_prompt_resource


def test_reads_packaged_conventions() -> None:
    assert "# Conventions" in read_prompt_resource("conventions.md")


def test_reads_packaged_role_prompt() -> None:
    assert "# Role: Developer" in read_prompt_resource("role-developer.md")
