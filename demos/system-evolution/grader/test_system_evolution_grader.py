from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from system_evolution_grader import (
    Check,
    CommandResult,
    GradeResult,
    SystemEvolutionGrader,
    validate_project_name,
)


def test_result_model_counts_all_diagnostic_statuses_and_hard_gates() -> None:
    result = GradeResult(1, target_revision="abc123")
    result.add(Check("api-ok", "api", "passed", 0.1, "ok"))
    result.add(Check("api-bad", "api", "failed", 0.2, "bad", hard_gate=True))
    result.add(Check("browser-skip", "browser", "unverified", 0, "not implemented"))
    result.add(Check("grader-broke", "deployment", "grader_error", 0, "boom"))

    data = result.as_dict()

    assert data["schema_version"] == 1
    assert data["valid_run"] is False
    assert data["invalid_reasons"] == ["api-bad"]
    assert data["dimensions"]["api"] == {
        "passed": 1,
        "failed": 1,
        "unverified": 0,
        "grader_error": 0,
    }
    assert data["unweighted_pass_rate"] == 0.5


@pytest.mark.parametrize(
    "name",
    ("short", "UPPERCASE-project", "contains.dot", "-leading-hyphen", "x" * 64),
)
def test_compose_project_validation_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ValueError):
        validate_project_name(name)


def test_compose_lifecycle_is_scoped_and_never_deletes_volumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(
        args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
    ) -> CommandResult:
        del cwd, environment, timeout
        command = tuple(args)
        calls.append(command)
        if "rev-parse" in command:
            return _result(command, stdout="abc123\n")
        if command[-2:] == ("status", "--porcelain"):
            return _result(command)
        if command[-2:] == ("version", "--short"):
            return _result(command, stdout="2.39.1\n")
        if command[-3:] == ("config", "--format", "json"):
            return _result(command, stdout=json.dumps(_compose_config()))
        if command[-3:] == ("ps", "--format", "json"):
            rows = [
                {"Service": name, "State": "running", "Health": "healthy"}
                for name in ("db", "api", "frontend")
            ]
            return _result(command, stdout="\n".join(json.dumps(row) for row in rows))
        return _result(command, returncode=1 if "up" in command else 0)

    monkeypatch.setattr("system_evolution_grader.shutil.which", lambda name: f"/usr/bin/{name}")
    grader = SystemEvolutionGrader(
        target,
        1,
        "idea-greenhouse-run01",
        runner=runner,
        docker_path=Path("/usr/bin/docker"),
        host_port=49123,
    )

    result = grader.grade()

    compose_calls = [call for call in calls if "compose" in call]
    assert compose_calls
    assert all(
        call[:4] == ("/usr/bin/docker", "compose", "--project-name", "idea-greenhouse-run01")
        for call in compose_calls
    )
    down = next(call for call in compose_calls if "down" in call)
    assert down[-2:] == ("down", "--remove-orphans")
    assert "--volumes" not in down
    assert "-v" not in down
    assert "G1-DEP-START" in result.invalid_reasons


def test_missing_docker_is_unverified_and_makes_run_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)

    def runner(
        args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
    ) -> CommandResult:
        del cwd, environment, timeout
        command = tuple(args)
        if "rev-parse" in command:
            return _result(command, stdout="abc123\n")
        return _result(command)

    monkeypatch.setattr(
        "system_evolution_grader.shutil.which",
        lambda name: "/usr/bin/git" if name == "git" else None,
    )
    grader = SystemEvolutionGrader(target, 1, "idea-greenhouse-run02", runner=runner)

    result = grader.grade()

    docker_check = next(check for check in result.checks if check.id == "PREREQ-DOCKER-COMPOSE")
    assert docker_check.status == "unverified"
    assert result.as_dict()["valid_run"] is False


def test_resolved_compose_topology_checks_public_boundary(tmp_path: Path) -> None:
    target = _target(tmp_path)

    def runner(
        args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
    ) -> CommandResult:
        del cwd, environment, timeout
        command = tuple(args)
        config = _compose_config()
        config["services"]["api"]["ports"] = [{"published": "8000", "target": 8000}]
        return _result(command, stdout=json.dumps(config))

    grader = SystemEvolutionGrader(
        target,
        1,
        "idea-greenhouse-run03",
        runner=runner,
        docker_path=Path("/usr/bin/docker"),
    )

    assert grader._compose_config_checks() is False
    boundary = next(
        check for check in grader.result.checks if check.id == "G1-DEP-PUBLIC-BOUNDARY"
    )
    assert boundary.status == "failed"
    assert boundary.hard_gate is True


def test_generation_two_is_explicitly_deferred_without_touching_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)
    fixture = tmp_path / "fixture.json"
    fixture.write_text("{}\n")
    calls: list[tuple[str, ...]] = []

    def runner(
        args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
    ) -> CommandResult:
        del cwd, environment, timeout
        command = tuple(args)
        calls.append(command)
        if "rev-parse" in command:
            return _result(command, stdout="abc123\n")
        return _result(command)

    monkeypatch.setattr(
        "system_evolution_grader.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    grader = SystemEvolutionGrader(
        target,
        2,
        "idea-greenhouse-run04",
        runner=runner,
        docker_path=Path("/usr/bin/docker"),
        generation_1_fixture=fixture,
    )

    result = grader.grade()

    deferred = next(check for check in result.checks if check.id == "G2-GRADING-NOT-IMPLEMENTED")
    assert deferred.status == "unverified"
    assert not any("compose" in call for call in calls)


def _target(tmp_path: Path) -> Path:
    for relative in (
        "compose.yaml",
        ".env.example",
        "backend/Containerfile",
        "backend/docker-entrypoint.sh",
        "frontend/Containerfile",
        "frontend/nginx.conf",
        "scripts/compose-smoke.sh",
        "Makefile",
        "README.md",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n")
    (tmp_path / ".dockerignore").write_text(
        ".git\n.devlab\n.env\nnode_modules\ndist\n__pycache__\n"
    )
    return tmp_path


def _result(
    args: tuple[str, ...], *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> CommandResult:
    return CommandResult(args, returncode, stdout, stderr, 0.01)


def _compose_config() -> dict[str, Any]:
    health = {"test": ["CMD", "true"]}
    return {
        "services": {
            "db": {
                "healthcheck": health,
                "volumes": [{"type": "volume", "source": "postgres-data", "target": "/data"}],
            },
            "api": {"healthcheck": health, "depends_on": {"db": {"condition": "service_healthy"}}},
            "frontend": {
                "healthcheck": health,
                "depends_on": {"api": {"condition": "service_healthy"}},
                "ports": [{"published": "49123", "target": 8080}],
            },
        }
    }
