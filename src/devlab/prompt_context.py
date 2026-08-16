from __future__ import annotations

import dataclasses
import math
import tomllib
from pathlib import Path
from typing import Any, cast

from devlab.agent_config import AGENTS_CONFIG, ROLE_NAMES
from devlab.prompt_resources import read_prompt_resource
from devlab.prompts import build_base_prompt, build_researcher_prompt, build_session_prompt
from devlab.research import ResearchStatus
from devlab.roles import ROLES
from devlab.workspace import WorkspaceSnapshot

DEFAULT_WARNING_TOKENS = 60_000
DEFAULT_CRITICAL_TOKENS = 100_000


@dataclasses.dataclass(frozen=True)
class PromptSize:
    characters: int
    lines: int
    estimated_tokens: int


@dataclasses.dataclass(frozen=True)
class PromptContextThresholds:
    warning_tokens: int = DEFAULT_WARNING_TOKENS
    critical_tokens: int = DEFAULT_CRITICAL_TOKENS


@dataclasses.dataclass(frozen=True)
class RolePromptContext:
    role_name: str
    base: PromptSize
    session: PromptSize
    total: PromptSize
    thresholds: PromptContextThresholds

    @property
    def status(self) -> str:
        if self.total.estimated_tokens >= self.thresholds.critical_tokens:
            return "critical"
        if self.total.estimated_tokens >= self.thresholds.warning_tokens:
            return "warning"
        return "ok"


@dataclasses.dataclass(frozen=True)
class PromptContextReport:
    roles: tuple[RolePromptContext, ...]


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def measure_prompt(text: str) -> PromptSize:
    return PromptSize(
        characters=len(text),
        lines=0 if not text else text.count("\n") + 1,
        estimated_tokens=estimate_tokens(text),
    )


def build_prompt_context_report(snapshot: WorkspaceSnapshot) -> PromptContextReport:
    root = snapshot.root
    thresholds = load_prompt_context_thresholds(root)
    roles: list[RolePromptContext] = []
    for role_name in ROLE_NAMES:
        role = ROLES[role_name]
        base_prompt = build_base_prompt(
            root, role, snapshot=snapshot, role_name=role_name
        )
        session_prompt = build_session_prompt(snapshot, role_name)
        role_thresholds = thresholds.get(role_name, thresholds["default"])
        roles.append(
            RolePromptContext(
                role_name=role_name,
                base=measure_prompt(base_prompt),
                session=measure_prompt(session_prompt),
                total=measure_prompt(base_prompt + "\n\n" + session_prompt),
                thresholds=role_thresholds,
            )
        )
    resume = snapshot.workflow_state().resume
    if resume is not None and resume.blocked_kind == "research":
        research = snapshot.get_research(resume.blocked_by)
        if research.status == ResearchStatus.REQUESTED:
            base_prompt = read_prompt_resource("role-researcher.md")
            session_prompt = build_researcher_prompt(snapshot, research, resume)
            role_thresholds = thresholds.get("researcher", thresholds["default"])
            roles.append(
                RolePromptContext(
                    role_name="researcher",
                    base=measure_prompt(base_prompt),
                    session=measure_prompt(session_prompt),
                    total=measure_prompt(base_prompt + "\n\n" + session_prompt),
                    thresholds=role_thresholds,
                )
            )
    return PromptContextReport(tuple(roles))



def load_prompt_context_thresholds(root: Path) -> dict[str, PromptContextThresholds]:
    data = _load_agents_config(root)
    prompt_context = _table(data.get("prompt_context", {}), "prompt_context")
    default_thresholds = _thresholds_from_table(prompt_context, "prompt_context")
    thresholds = {"default": default_thresholds}
    roles = _table(prompt_context.get("roles", {}), "prompt_context.roles")
    for role_name, value in roles.items():
        if role_name not in {*ROLE_NAMES, "researcher"}:
            raise ValueError(f"prompt_context.roles.{role_name} is not a known role")
        role_table = _table(value, f"prompt_context.roles.{role_name}")
        thresholds[role_name] = _thresholds_from_table(
            role_table,
            f"prompt_context.roles.{role_name}",
            fallback=default_thresholds,
        )
    return thresholds


def _thresholds_from_table(
    table: dict[str, Any],
    name: str,
    *,
    fallback: PromptContextThresholds | None = None,
) -> PromptContextThresholds:
    fallback = fallback or PromptContextThresholds()
    warning_tokens = _positive_int(
        table.get("warning_tokens", fallback.warning_tokens),
        f"{name}.warning_tokens",
    )
    critical_tokens = _positive_int(
        table.get("critical_tokens", fallback.critical_tokens),
        f"{name}.critical_tokens",
    )
    if critical_tokens < warning_tokens:
        raise ValueError(f"{name}.critical_tokens must be greater than or equal to warning_tokens")
    return PromptContextThresholds(warning_tokens, critical_tokens)


def _load_agents_config(root: Path) -> dict[str, Any]:
    path = root / AGENTS_CONFIG
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return _table(data, AGENTS_CONFIG)


def _table(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a TOML table")
    return cast("dict[str, Any]", value)


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value
