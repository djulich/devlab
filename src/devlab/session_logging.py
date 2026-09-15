"""Session identity, artifacts, metadata, and log-context formatting."""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from devlab.agent_config import ResolvedAgentConfig, format_resolved_agent_config
from devlab.agents import AgentInvocation
from devlab.handoffs import DEVLAB_PYTHON_ENV, SESSION_ENVELOPE_ENV, SESSION_ENVELOPE_FILE
from devlab.profiles import DEFAULT_PROFILE
from devlab.task_tracker import Task
from devlab.workspace import AGENT_LOG_DIR, ARTIFACTS_DIR, DESIGN_PLAN, WorkspaceSnapshot


@dataclasses.dataclass(frozen=True)
class SessionMetadata:
    """Durable metadata written for one provider invocation."""

    invocation_id: str
    session_number: int
    role_name: str
    provider: str
    model: str
    return_code: int
    failure_kind: str
    duration_seconds: float | None
    task_id: str
    provider_version: str = ""
    executable_config_digest: str = ""
    executable_config_authorization: str = ""
    test_service_instances: dict[str, str] = dataclasses.field(default_factory=dict)
    progress: str = ""
    dependency_introductions: tuple[dict[str, str], ...] = ()


@dataclasses.dataclass(frozen=True)
class SessionContext:
    """Per-session artifact paths and trusted invocation identity."""

    root: Path
    session_number: int
    role_name: str
    invocation_id: str
    stdout_log: Path
    stderr_log: Path
    base_prompt_log: Path | None
    session_prompt_log: Path | None
    service_environment: dict[str, str] = dataclasses.field(default_factory=dict)
    service_instances: dict[str, str] = dataclasses.field(default_factory=dict)

    def build_invocation(self, base_prompt: str, session_prompt: str) -> AgentInvocation:
        envelope = self.root / ARTIFACTS_DIR / self.role_name / SESSION_ENVELOPE_FILE
        return AgentInvocation(
            root=self.root,
            role_name=self.role_name,
            system_prompt=base_prompt,
            session_prompt=session_prompt,
            invocation_id=self.invocation_id,
            stdout_log=self.stdout_log,
            stderr_log=self.stderr_log,
            environment={
                **self.service_environment,
                SESSION_ENVELOPE_ENV: envelope.as_posix(),
                DEVLAB_PYTHON_ENV: str(Path(sys.executable).absolute()),
            },
        )

    def log_resolved_config(self, config: ResolvedAgentConfig) -> Path:
        path = agent_log_path(self.root, self.invocation_id, "config.toml")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = format_resolved_agent_config(config)
        text += f'stdout_log = "{self.stdout_log.as_posix()}"\n'
        text += f'stderr_log = "{self.stderr_log.as_posix()}"\n'
        if self.base_prompt_log is not None:
            text += f'base_prompt_log = "{self.base_prompt_log.as_posix()}"\n'
        if self.session_prompt_log is not None:
            text += f'session_prompt_log = "{self.session_prompt_log.as_posix()}"\n'
        path.write_text(text)
        return path

    def write_prompt_logs(self, base_prompt: str, session_prompt: str) -> None:
        if self.base_prompt_log is None or self.session_prompt_log is None:
            return
        self.base_prompt_log.parent.mkdir(parents=True, exist_ok=True)
        self.base_prompt_log.write_text(base_prompt)
        self.session_prompt_log.parent.mkdir(parents=True, exist_ok=True)
        self.session_prompt_log.write_text(session_prompt)

    def write_session_metadata(self, metadata: SessionMetadata) -> Path:
        path = agent_log_path(self.root, self.invocation_id, "metadata.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataclasses.asdict(metadata), indent=2) + "\n")
        return path


def agent_log_path(root: Path, invocation_id: str, suffix: str) -> Path:
    return root / AGENT_LOG_DIR / f"{invocation_id}.{suffix}"


def session_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def build_session_context(
    root: Path,
    session_number: int,
    role_name: str,
    *,
    retain_prompts: bool,
) -> SessionContext:
    invocation_id = f"{session_timestamp()}_{session_number:03d}_{role_name}"
    return SessionContext(
        root=root,
        session_number=session_number,
        role_name=role_name,
        invocation_id=invocation_id,
        stdout_log=agent_log_path(root, invocation_id, "stdout.log"),
        stderr_log=agent_log_path(root, invocation_id, "stderr.log"),
        base_prompt_log=(
            agent_log_path(root, invocation_id, "base-prompt.md") if retain_prompts else None
        ),
        session_prompt_log=(
            agent_log_path(root, invocation_id, "session-prompt.md") if retain_prompts else None
        ),
    )


def session_start_context(snapshot: WorkspaceSnapshot, role_name: str, task: Task | None) -> str:
    if role_name in {"developer", "reviewer"}:
        if task is None:
            return "task=none"
        return _format_task_context(task)
    if role_name == "planner":
        open_findings = len(snapshot.open_findings())
        active_tasks = len(snapshot.active_tasks())
        total_tasks = len(snapshot.list_tasks())
        return f"tasks={total_tasks} active_tasks={active_tasks} open_findings={open_findings}"
    if role_name == "integrator":
        milestone = snapshot.select_integration_milestone()
        if milestone is None:
            return "milestone=none"
        tasks = snapshot.tasks_for_milestone(milestone)
        closed = sum(1 for t in tasks if t.status.value == "closed")
        return f"milestone={milestone} closed_tasks={closed}/{len(tasks)}"
    if role_name == "architect":
        milestone = snapshot.select_architecture_review_milestone()
        if milestone is not None:
            return f"mode=architecture-review milestone={milestone}"
        if not (snapshot.root / DESIGN_PLAN).exists():
            return "mode=initial-design"
        return "mode=architecture"
    return ""


def session_finish_context(
    snapshot: WorkspaceSnapshot,
    role_name: str,
    *,
    task_id: str | None,
    milestone_id: str | None,
) -> str:
    parts: list[str] = []
    if role_name in {"developer", "reviewer"} and task_id is not None:
        task = _task_by_id(snapshot, task_id)
        parts.append(f"task={task_id}")
        if task is not None:
            parts.append(f"status={task.status.value}")
    elif role_name in {"integrator", "architect"} and milestone_id is not None:
        parts.append(f"milestone={milestone_id}")
    next_role = snapshot.assess_state()
    parts.append(f"next={next_role or 'complete'}")
    return " ".join(parts)


def _task_by_id(snapshot: WorkspaceSnapshot, task_id: str) -> Task | None:
    for task in snapshot.list_tasks():
        if task.id == task_id:
            return task
    return None


def _format_task_context(task: Task) -> str:
    parts = [
        f"task={task.id}",
        f"status={task.status.value}",
        f"profile={task.profile or DEFAULT_PROFILE}",
        f"domain={task.domain}",
    ]
    if task.milestone:
        parts.append(f"milestone={task.milestone}")
    return " ".join(parts)
