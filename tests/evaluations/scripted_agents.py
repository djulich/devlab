from __future__ import annotations

import json
from pathlib import Path

from devlab.agents import AgentInvocation
from devlab.findings import FileFindingTracker
from devlab.task_tracker import FileTaskTracker
from tests.evaluations.generated_products import (
    write_calculator,
    write_compiled_cli,
    write_compose_deployment_artifacts,
    write_container_deployment_artifacts,
    write_http_app,
    write_mixed_rust_go_component,
    write_mixed_rust_go_integration,
    write_stateful_todo_api,
    write_static_frontend,
)
from tests.helpers import (
    approve_review_task,
    complete_acceptance,
    handoff,
    write_task,
)


class CalculatorScriptedAgent:
    def __init__(self, *, reject_first_review: bool = False, require_smoke_finding: bool = False):
        self.reject_first_review = reject_first_review
        self.require_smoke_finding = require_smoke_finding
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self._record(invocation)
        role = invocation.role_name
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python calculator CLI with add and subtract subcommands.\n"
            )
        elif role == "planner":
            self._planner(invocation.root)
        elif role == "developer":
            self._developer(invocation.root)
        elif role == "reviewer":
            self._reviewer(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        role = invocation.role_name
        if role == "reviewer" and self._should_reject_review():
            self.review_rejections += 1
            return handoff(role, open_issues="- Subtraction is missing from the calculator CLI.")
        if role == "integrator" and self._should_raise_smoke_finding(invocation.root):
            return handoff(
                role,
                open_issues="- The calculator milestone lacks a committed smoke test artifact.",
            )
        if role == "planner" and finding_exists(invocation.root, "F0001"):
            return handoff(role, addressed="- F0001: T0002")
        return handoff(role)

    def _record(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))

    def _planner(self, root: Path) -> None:
        if finding_exists(root, "F0001"):
            _project_plan(root).write_text(
                "# Project Plan\n\n"
                "## M1: Calculator CLI\n"
                "- T0001: Implement calculator CLI\n"
                "- T0002: Add calculator smoke test\n"
            )
            write_task(
                root,
                "T0002",
                "Add calculator smoke test",
                "M1",
                depends_on=["T0001"],
                addresses_findings=["F0001"],
            )
            return
        _project_plan(root).write_text(
            "# Project Plan\n\n"
            "## M1: Calculator CLI\n"
            "- T0001: Implement calculator CLI\n"
        )
        write_task(root, "T0001", "Implement calculator CLI", "M1")

    def _developer(self, root: Path) -> None:
        task = FileTaskTracker(root).select_next_development_task()
        assert task is not None
        complete_acceptance(root, task.id)
        if task.id == "T0001":
            complete = not self.reject_first_review or self.role_counts["developer"] > 1
            write_calculator(root, include_subtract=complete)
        elif task.id == "T0002":
            (root / "test_calculator_smoke.py").write_text(
                "from calculator import calculate\n\n\n"
                "def test_smoke_add_and_subtract():\n"
                "    assert calculate('add', 2, 3) == 5\n"
                "    assert calculate('subtract', 7, 4) == 3\n"
            )

    def _reviewer(self, root: Path) -> None:
        if self._should_reject_review():
            return
        approve_review_task(root)

    def _should_reject_review(self) -> bool:
        return self.reject_first_review and self.role_counts.get("reviewer", 0) == 1

    def _should_raise_smoke_finding(self, root: Path) -> bool:
        return (
            self.require_smoke_finding
            and self.role_counts.get("integrator", 0) == 1
            and not finding_exists(root, "F0001")
        )


class CompiledLanguageScriptedAgent:
    """Drive one minimal compiled-language task through the complete workflow."""

    def __init__(self, language: str):
        self.language = language
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        role = invocation.role_name
        self.roles.append(role)
        self.role_counts[role] = self.role_counts.get(role, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                f"Build a minimal {self.language} CLI with project-owned validation.\n"
            )
        elif role == "planner":
            self._plan(invocation.root)
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            write_compiled_cli(invocation.root, self.language)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)

    def _plan(self, root: Path) -> None:
        title = f"Implement {self.language} CLI"
        _project_plan(root).write_text(
            f"# Project Plan\n\n## M1: {self.language} CLI\n- T0001: {title}\n"
        )
        profile = root / ".devlab/config/profiles/default.toml"
        profile.write_text(_compiled_profile(self.language))
        task_path = write_task(root, "T0001", title, "M1")
        task_path.write_text(task_path.read_text().replace('validation = []\n', ""))


def _compiled_profile(language: str) -> str:
    commands = {
        "rust": ["cargo fmt --check", "cargo test"],
        "go": [
            "gofmt -l . | (! grep .)",
            "GOCACHE=/tmp/devlab-evaluation-go-cache go vet ./...",
            "GOCACHE=/tmp/devlab-evaluation-go-cache go test ./...",
        ],
        "c": ["cmake --preset dev", "cmake --build --preset dev", "ctest --preset dev"],
        "cpp": ["cmake --preset dev", "cmake --build --preset dev", "ctest --preset dev"],
    }[language]
    validation = "\n".join(f'  "{command}",' for command in commands)
    return (
        'version = 1\nid = "default"\n'
        f'title = "{language} evaluation"\n\n'
        f'[tooling]\nsummary = "{language} project-owned workflow."\n'
        f"default_validation = [\n{validation}\n]\n\n"
        '[environment]\nmanaged_roles = []\n'
    )


class MixedLanguageScriptedAgent:
    """Exercise component profiles and a repository-owned integration command."""

    def __init__(self):
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        role = invocation.role_name
        self.roles.append(role)
        self.role_counts[role] = self.role_counts.get(role, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\nRust and Go components with a root integration command.\n"
            )
        elif role == "planner":
            self._plan(invocation.root)
        elif role == "developer":
            self._develop(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)

    def _plan(self, root: Path) -> None:
        _project_plan(root).write_text(
            "# Project Plan\n\n## M1: Mixed workspace\n"
            "- T0001: Implement Rust component\n"
            "- T0002: Implement Go component\n"
            "- T0003: Add cross-component validation\n"
        )
        profiles = root / ".devlab/config/profiles"
        (profiles / "rust.toml").write_text(
            _named_profile("rust", ["cd rust-component && cargo test"])
        )
        (profiles / "go.toml").write_text(
            _named_profile(
                "go",
                [
                    "cd go-component && "
                    "GOCACHE=/tmp/devlab-evaluation-go-cache go test ./..."
                ],
            )
        )
        (profiles / "integration.toml").write_text(_named_profile("integration", ["make check"]))
        tasks = (
            ("T0001", "Implement Rust component", "rust", []),
            ("T0002", "Implement Go component", "go", ["T0001"]),
            ("T0003", "Add cross-component validation", "integration", ["T0001", "T0002"]),
        )
        for task_id, title, profile, dependencies in tasks:
            path = write_task(root, task_id, title, "M1", depends_on=dependencies)
            text = path.read_text().replace('profile = "default"', f'profile = "{profile}"')
            path.write_text(text.replace('validation = []\n', ""))

    def _develop(self, root: Path) -> None:
        task = FileTaskTracker(root).select_next_development_task()
        assert task is not None
        complete_acceptance(root, task.id)
        if task.id == "T0001":
            write_mixed_rust_go_component(root, "rust")
        elif task.id == "T0002":
            write_mixed_rust_go_component(root, "go")
        else:
            write_mixed_rust_go_integration(root)


def _named_profile(profile_id: str, commands: list[str]) -> str:
    validation = "\n".join(f'  "{command}",' for command in commands)
    return (
        f'version = 1\nid = "{profile_id}"\ntitle = "{profile_id} workflow"\n\n'
        f'[tooling]\nsummary = "{profile_id} project-owned workflow."\n'
        f"default_validation = [\n{validation}\n]\n\n"
        '[environment]\nmanaged_roles = []\n'
    )


class ClarificationCalculatorScriptedAgent(CalculatorScriptedAgent):
    """Exercise a durable developer clarification and unattended resolution."""

    def on_invoke(self, invocation: AgentInvocation) -> None:
        if invocation.role_name == "developer" and not self.role_counts.get("developer"):
            self._record(invocation)
            return
        if invocation.role_name == "clarification-resolver":
            self._record(invocation)
            answer_path = (
                invocation.root
                / ".devlab/session-artifacts/clarification-resolver/answer.json"
            )
            answer_path.write_text(
                '{"clarification_id":"CL0001","answer_shape":"choice",'
                '"choice":"A"}'
            )
            return
        super().on_invoke(invocation)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        if invocation.role_name == "developer" and self.role_counts["developer"] == 1:
            return handoff(
                "developer",
                open_issues="- Blocked pending operator clarification.",
            ) + (
                "## Clarification Request\n"
                "clarification_required = true\n"
                'title = "Calculator numeric policy"\n'
                'scope = "task:T0001"\n'
                'blocks = "implementation"\n'
                'answer_shape = "choice"\n'
                'recommended_option = "A"\n\n'
                "### Context\n"
                "The calculator needs one numeric representation.\n\n"
                "### Question\n"
                "Which numeric representation should the implementation use?\n\n"
                "### Options\n"
                "- A: Use integer arithmetic.\n"
                "- B: Use decimal arithmetic.\n"
            )
        return super().handoff_for(invocation)


class ResearchCalculatorScriptedAgent(CalculatorScriptedAgent):
    """Exercise durable research, exact developer resume, and normal completion."""

    def on_invoke(self, invocation: AgentInvocation) -> None:
        if invocation.role_name == "developer" and not self.role_counts.get("developer"):
            self._record(invocation)
            return
        if invocation.role_name == "researcher":
            self._record(invocation)
            assert "RS0001" in invocation.session_prompt
            path = invocation.root / ".devlab/session-artifacts/researcher/result.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "research_id": "RS0001",
                        "summary": "Integer arithmetic is deterministic for this bounded CLI.",
                        "evidence": [
                            {
                                "claim": "Python integers have arbitrary precision.",
                                "source_ids": ["S1"],
                            }
                        ],
                        "sources": [
                            {
                                "id": "S1",
                                "title": "Python numeric types",
                                "location": "https://docs.python.org/3/library/stdtypes.html",
                                "source_type": "primary",
                            }
                        ],
                        "recommendation": "Use integer arithmetic.",
                        "confidence": "high",
                        "unresolved_questions": [],
                    }
                )
            )
            return
        if invocation.role_name == "developer" and self.role_counts.get("developer") == 1:
            assert "## Completed Research For This Route" in invocation.session_prompt
        super().on_invoke(invocation)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        if invocation.role_name == "developer" and self.role_counts["developer"] == 1:
            return handoff("developer", open_issues="- Research is required.") + (
                "## Research Request\n"
                "research_required = true\n"
                'title = "Python integer behavior"\n'
                'scope = "task:T0001"\n'
                'question = "Are Python integers suitable for deterministic '
                'calculator arithmetic?"\n'
                'context = "The implementation must choose a numeric representation."\n'
                'desired_outcome = "Recommend a documented numeric representation."\n'
                'acceptance_criteria = ["Use Python primary documentation."]\n'
            )
        return super().handoff_for(invocation)


class HttpApiScriptedAgent:
    def __init__(self) -> None:
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        role = invocation.role_name
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\nBuild a tiny stdlib HTTP API with health and echo endpoints.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: HTTP API\n"
                "- T0001: Implement stdlib HTTP API\n"
            )
            write_task(invocation.root, "T0001", "Implement stdlib HTTP API", "M1")
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            write_http_app(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class DeploymentWebApiScriptedAgent:
    def __init__(self) -> None:
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        role = invocation.role_name
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python JSON todo API with project-owned deployment "
                "artifacts. The deployment path uses a Containerfile, Makefile targets, "
                "and README verification instructions.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Deployable todo API\n"
                "- T0001: Implement stateful todo API\n"
                "- T0002: Add container deployment artifacts\n"
            )
            write_task(invocation.root, "T0001", "Implement stateful todo API", "M1")
            write_task(
                invocation.root,
                "T0002",
                "Add container deployment artifacts",
                "M1",
                depends_on=["T0001"],
                domain="deployment",
            )
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            if task.id == "T0001":
                write_stateful_todo_api(invocation.root)
            elif task.id == "T0002":
                write_container_deployment_artifacts(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class ComposeDeploymentScriptedAgent:
    def __init__(self) -> None:
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        role = invocation.role_name
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python JSON todo API with Docker Compose deployment "
                "artifacts, project-owned local deploy/teardown commands, a smoke-test "
                "script, and README deployment instructions.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Compose deployable todo API\n"
                "- T0001: Implement stateful todo API\n"
                "- T0002: Add Compose deployment artifacts\n"
            )
            write_task(invocation.root, "T0001", "Implement stateful todo API", "M1")
            write_task(
                invocation.root,
                "T0002",
                "Add Compose deployment artifacts",
                "M1",
                depends_on=["T0001"],
                domain="deployment",
            )
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            if task.id == "T0001":
                write_stateful_todo_api(invocation.root)
                write_container_deployment_artifacts(invocation.root)
            elif task.id == "T0002":
                write_compose_deployment_artifacts(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class StaticFrontendScriptedAgent:
    def __init__(self) -> None:
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        role = invocation.role_name
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python JSON todo API and a static vanilla HTML/CSS/JS "
                "frontend in static/. The frontend calls the API endpoints directly and "
                "has no frontend package manager or build step.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Static todo application\n"
                "- T0001: Implement todo API and static frontend\n"
            )
            write_task(invocation.root, "T0001", "Implement todo API and static frontend", "M1")
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            write_stateful_todo_api(invocation.root)
            write_static_frontend(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class StatefulWebApiScriptedAgent:
    def __init__(self) -> None:
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        role = invocation.role_name
        if role == "architect":
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\n"
                "Build a small Python JSON HTTP API for in-memory todo items. "
                "Expose health, create, list, and delete endpoints plus project-owned "
                "run/test commands and usage documentation.\n"
            )
        elif role == "planner":
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Stateful todo API\n"
                "- T0001: Implement stateful todo API\n"
            )
            write_task(invocation.root, "T0001", "Implement stateful todo API", "M1")
        elif role == "developer":
            task = FileTaskTracker(invocation.root).select_next_development_task()
            assert task is not None
            complete_acceptance(invocation.root, task.id)
            write_stateful_todo_api(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)


class SpecReconciliationScriptedAgent:
    def __init__(self) -> None:
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        role = invocation.role_name
        if role == "architect":
            self._architect(invocation)
        elif role == "planner":
            self._planner(invocation)
        elif role == "developer":
            self._developer(invocation.root)
        elif role == "reviewer":
            approve_review_task(invocation.root)
        elif role == "integrator":
            assert "## Assigned Completed Milestone" in invocation.session_prompt

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)

    def _architect(self, invocation: AgentInvocation) -> None:
        if self.role_counts["architect"] == 1:
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\nBuild a tiny calculator CLI.\n"
            )
            return
        if self.role_counts["architect"] == 3:
            assert (
                "DevLab archived the previous active planning graph"
                in invocation.session_prompt
            )
            _design_plan(invocation.root).write_text(
                "# Design Plan\n\nBuild a tiny greeter CLI.\n"
            )
            return
        assert "Assigned Integrated Milestone for Architecture Review" in invocation.session_prompt

    def _planner(self, invocation: AgentInvocation) -> None:
        if self.role_counts["planner"] == 1:
            _project_plan(invocation.root).write_text(
                "# Project Plan\n\n"
                "## M1: Calculator CLI\n"
                "- T0001: Implement calculator CLI\n"
            )
            write_task(invocation.root, "T0001", "Implement calculator CLI", "M1")
            return
        assert "DevLab archived the previous active planning graph" in invocation.session_prompt
        assert not list((invocation.root / ".devlab/tasks").glob("*.md"))
        _project_plan(invocation.root).write_text(
            "# Project Plan\n\n"
            "## M1: Greeter CLI\n"
            "- T0001: Implement greeter CLI\n"
        )
        write_task(invocation.root, "T0001", "Implement greeter CLI", "M1")

    def _developer(self, root: Path) -> None:
        task = FileTaskTracker(root).select_next_development_task()
        assert task is not None
        complete_acceptance(root, task.id)
        if task.title == "Implement calculator CLI":
            (root / "calculator.py").write_text(
                "import sys\n\n"
                "if len(sys.argv) != 4 or sys.argv[1] != 'add':\n"
                "    raise SystemExit(2)\n"
                "print(int(sys.argv[2]) + int(sys.argv[3]))\n"
            )
        elif task.title == "Implement greeter CLI":
            (root / "greeter.py").write_text(
                "import sys\n\n"
                "name = sys.argv[1] if len(sys.argv) > 1 else 'world'\n"
                "print(f'hello {name}')\n"
            )
        else:  # pragma: no cover - defensive scripted-agent guard
            raise AssertionError(f"unexpected task title: {task.title}")


class AdoptExistingScriptedAgent:
    def __init__(self) -> None:
        self.roles: list[str] = []
        self.role_counts: dict[str, int] = {}
        self.review_rejections = 0
        self.prompt_chars: list[int] = []

    def on_invoke(self, invocation: AgentInvocation) -> None:
        self.roles.append(invocation.role_name)
        self.role_counts[invocation.role_name] = self.role_counts.get(invocation.role_name, 0) + 1
        self.prompt_chars.append(len(invocation.system_prompt) + len(invocation.session_prompt))
        role = invocation.role_name
        if role == "architect":
            self._architect(invocation)
        elif role == "planner":
            self._planner(invocation)

    def handoff_for(self, invocation: AgentInvocation) -> str:
        return handoff(invocation.role_name)

    def _architect(self, invocation: AgentInvocation) -> None:
        assert "existing-project adoption" in invocation.session_prompt
        assert "current-state design baseline" in invocation.session_prompt
        assert "Preserve the existing project's development stack" in invocation.session_prompt
        assert "target-owned validation path" in invocation.session_prompt
        assert (invocation.root / "calculator.py").exists()
        assert (invocation.root / "test_calculator.py").exists()
        _design_plan(invocation.root).write_text(
            "# Design Plan\n\n"
            "## Current-State Design Baseline\n\n"
            "- Existing source structure: `calculator.py` provides a Python CLI entry point.\n"
            "- Existing behavior: the CLI supports an `add` command.\n"
            "- Existing tests: `test_calculator.py` covers addition.\n"
            "- Existing tooling: the project uses Python stdlib execution with pytest tests.\n"
            "- Deployment state: no deployment artifacts are present.\n"
            "- Specification gaps: the current CLI does not support subtraction.\n\n"
            "## Target Design\n\n"
            "Extend the existing calculator CLI with a subtract command while preserving "
            "the current add command and test style.\n"
        )

    def _planner(self, invocation: AgentInvocation) -> None:
        assert "existing-project adoption" in invocation.session_prompt
        assert "target-owned validation path" in invocation.session_prompt
        assert "Do not silently rely on host-global" in invocation.session_prompt
        assert "Current-State Design Baseline" in _design_plan(invocation.root).read_text()
        _project_plan(invocation.root).write_text(
            "# Project Plan\n\n"
            "## M1: Adopted calculator enhancement\n"
            "- T0001: Add subtract command to existing calculator CLI\n"
        )
        write_task(
            invocation.root,
            "T0001",
            "Add subtract command to existing calculator CLI",
            "M1",
        )



def finding_exists(root: Path, finding_id: str) -> bool:
    return any(finding.id == finding_id for finding in FileFindingTracker(root).list_findings())


def _design_plan(root: Path) -> Path:
    return root / ".devlab/plans/design-plan.md"


def _project_plan(root: Path) -> Path:
    return root / ".devlab/plans/project-plan.md"
