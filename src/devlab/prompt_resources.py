from __future__ import annotations

from importlib import resources

PROMPT_RESOURCE_PACKAGE = "devlab.resources.prompts"


def read_prompt_resource(name: str) -> str:
    return resources.files(PROMPT_RESOURCE_PACKAGE).joinpath(name).read_text()
