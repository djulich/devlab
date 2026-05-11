from __future__ import annotations

from pathlib import Path

from devlab.agent_config import AGENTS_CONFIG, ResolvedAgentConfig, load_agent_configuration
from devlab.orchestrator import assess_state


def format_status(root: Path, *, verbose: bool = False) -> str:
    lines: list[str] = []
    role_name = assess_state(root)
    if role_name is None:
        lines.append("No role selected; workflow is complete or blocked.")
    else:
        lines.append(f"Next role: {role_name}")

    if verbose:
        lines.extend(["", *_format_agent_configuration(root)])
    return "\n".join(lines)


def _format_agent_configuration(root: Path) -> list[str]:
    config = load_agent_configuration(root)
    source = root / AGENTS_CONFIG
    lines = ["Agent configuration:"]
    if source.exists():
        lines.append(f"Source: {AGENTS_CONFIG}")
    else:
        lines.append("Source: built-in fallback defaults")
    for role_name in sorted(config.resolved):
        lines.append(_format_role_agent(config.resolved[role_name]))
    return lines


def _format_role_agent(config: ResolvedAgentConfig) -> str:
    timeout = "none" if config.timeout_seconds is None else str(config.timeout_seconds)
    command = "[" + ", ".join(repr(part) for part in config.command) + "]"
    stdin = "true" if config.uses_stdin else "false"
    return (
        f"- {config.role_name}: {config.provider} "
        f'model="{config.model}" '
        f'effort="{config.effort}" '
        f"timeout={timeout} "
        f"command={command} "
        f"stdin={stdin}"
    )
