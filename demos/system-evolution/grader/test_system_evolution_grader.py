from __future__ import annotations

import hashlib
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


def test_generation_two_rejects_invalid_resume_artifacts_without_touching_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path / "target")
    fixture = tmp_path / "fixture.json"
    fixture.write_text("{}\n")
    resume = tmp_path / "resume.json"
    resume.write_text("{}\n")
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
        generation_1_resume=resume,
    )

    result = grader.grade()

    invalid = next(check for check in result.checks if check.id == "INPUT-GENERATION-1-ARTIFACTS")
    assert invalid.status == "grader_error"
    assert not any("compose" in call for call in calls)


def test_browser_checks_use_isolated_pinned_playwright_and_expand_results(tmp_path: Path) -> None:
    target = _target(tmp_path)
    captured: list[tuple[str, ...]] = []

    def runner(
        args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
    ) -> CommandResult:
        del cwd, environment
        command = tuple(args)
        captured.append(command)
        assert timeout == 360
        mount = command[command.index("--mount") + 1]
        script_path = Path(mount.split(",")[1].removeprefix("src="))
        script = script_path.read_text()
        assert "require('/tmp/evaluator-tools/node_modules/playwright')" in script
        payload = {
            "checks": [
                {
                    "id": "G1-UI-LOAD",
                    "passed": True,
                    "evidence": "loaded",
                    "requirement_ids": ["G1-UI-01"],
                },
                {
                    "id": "G1-UI-EMPTY",
                    "passed": False,
                    "evidence": "missing empty state",
                    "requirement_ids": ["G1-UI-05"],
                },
            ]
        }
        return _result(command, stdout=f"DEVLAB_BROWSER_RESULT:{json.dumps(payload)}\n")

    grader = SystemEvolutionGrader(
        target,
        1,
        "idea-greenhouse-run05",
        runner=runner,
        docker_path=Path("/usr/bin/docker"),
        host_port=49123,
    )

    grader._browser_checks()

    command = captured[0]
    assert command[:2] == ("/usr/bin/docker", "run")
    assert "--network=host" in command
    assert "mcr.microsoft.com/playwright:v1.53.1-jammy" in command
    assert "playwright@1.53.1" in command[-2]
    assert all(str(target) not in argument for argument in command)
    assert [(check.id, check.status) for check in grader.result.checks] == [
        ("G1-UI-LOAD", "passed"),
        ("G1-UI-EMPTY", "failed"),
    ]


def test_browser_setup_failure_is_a_grader_error(tmp_path: Path) -> None:
    target = _target(tmp_path)

    def runner(
        args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
    ) -> CommandResult:
        del cwd, environment, timeout
        return _result(
            tuple(args),
            returncode=1,
            stderr='DEVLAB_GRADER_ERROR:{"error":"chromium launch failed"}',
        )

    grader = SystemEvolutionGrader(
        target,
        1,
        "idea-greenhouse-run06",
        runner=runner,
        docker_path=Path("/usr/bin/docker"),
    )

    grader._browser_checks()

    assert len(grader.result.checks) == 1
    assert grader.result.checks[0].id == "G1-UI-GRADER"
    assert grader.result.checks[0].status == "grader_error"


def test_generation_one_fixture_is_seeded_through_public_api_and_digested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path / "target")
    fixture = tmp_path / "evidence" / "generation-1-fixture.json"
    resume = tmp_path / "evidence" / "generation-1-resume.json"
    grader = SystemEvolutionGrader(
        target,
        1,
        "idea-greenhouse-run07",
        docker_path=Path("/usr/bin/docker"),
        host_port=49123,
        generation_1_fixture_out=fixture,
        generation_1_resume_out=resume,
    )
    grader.result.target_revision = "abc123"
    grader.database_volume = "idea-greenhouse-run07_postgres-data"
    requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(
        method: str, url: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any], float, str]:
        requests.append((method, url, payload))
        assert payload is not None
        idea_id = len(requests)
        body = {
            "id": idea_id,
            "title": payload["title"],
            "notes": payload.get("notes"),
            "stage": payload.get("stage", "seed"),
            "created_at": f"2026-08-22T12:00:0{idea_id}Z",
            "updated_at": f"2026-08-22T12:00:0{idea_id}Z",
        }
        return 201, body, 0.01, ""

    monkeypatch.setattr(grader, "_request", request)

    grader._create_generation_1_fixture()

    assert [request[0] for request in requests] == ["POST", "POST", "POST"]
    assert all(request[1] == "http://127.0.0.1:49123/api/ideas" for request in requests)
    content = json.loads(fixture.read_text())
    digest = content.pop("content_digest")
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest == f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
    assert content["target_revision"] == "abc123"
    assert content["compose_project"] == "idea-greenhouse-run07"
    assert [idea["stage"] for idea in content["ideas"]] == ["seed", "sprout", "bloom"]
    check = grader.result.checks[0]
    assert check.status == "passed"
    assert check.artifacts == (str(fixture), str(resume))
    assert resume.stat().st_mode & 0o777 == 0o600
    resume_content = json.loads(resume.read_text())
    assert resume_content["compose_project"] == "idea-greenhouse-run07"
    assert resume_content["database_volume"] == "idea-greenhouse-run07_postgres-data"
    assert resume_content["postgres"]["password"]


def test_generation_one_fixture_refuses_to_replace_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path / "target")
    fixture = tmp_path / "fixture.json"
    resume = tmp_path / "resume.json"
    fixture.write_text("original\n")
    grader = SystemEvolutionGrader(
        target,
        1,
        "idea-greenhouse-run08",
        docker_path=Path("/usr/bin/docker"),
        generation_1_fixture_out=fixture,
        generation_1_resume_out=resume,
    )
    monkeypatch.setattr(grader, "_request", lambda *args, **kwargs: pytest.fail())

    grader._create_generation_1_fixture()

    assert fixture.read_text() == "original\n"
    assert grader.result.checks[0].status == "grader_error"


def test_failed_fixture_seeding_removes_partial_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path / "target")
    fixture = tmp_path / "fixture.json"
    resume = tmp_path / "resume.json"
    grader = SystemEvolutionGrader(
        target,
        1,
        "idea-greenhouse-run09",
        docker_path=Path("/usr/bin/docker"),
        generation_1_fixture_out=fixture,
        generation_1_resume_out=resume,
    )
    grader.database_volume = "idea-greenhouse-run09_postgres-data"
    deleted: list[int] = []
    posts = 0

    def request(
        method: str, url: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any], float, str]:
        nonlocal posts
        if method == "DELETE":
            deleted.append(int(url.rsplit("/", 1)[1]))
            return 204, {}, 0.01, ""
        posts += 1
        assert payload is not None
        body = {
            "id": posts,
            "title": payload["title"],
            "notes": payload.get("notes"),
            "stage": "seed" if posts == 2 else payload.get("stage", "seed"),
            "created_at": "2026-08-22T12:00:00Z",
            "updated_at": "2026-08-22T12:00:00Z",
        }
        return 201, body, 0.01, ""

    monkeypatch.setattr(grader, "_request", request)

    grader._create_generation_1_fixture()

    assert deleted == [1, 2, 3]
    assert not fixture.exists()
    assert grader.result.checks[-1].status == "failed"


def test_fixture_output_must_be_outside_target(tmp_path: Path) -> None:
    target = _target(tmp_path / "target")

    with pytest.raises(ValueError, match="outside the target checkout"):
        SystemEvolutionGrader(
            target,
            1,
            "idea-greenhouse-run10",
            docker_path=Path("/usr/bin/docker"),
            generation_1_fixture_out=target / "fixture.json",
        )


def test_generation_two_loads_validated_resume_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path / "target")
    fixture = tmp_path / "fixture.json"
    resume = tmp_path / "resume.json"
    _write_digested(fixture, _fixture_content("idea-greenhouse-run11"))
    _write_digested(
        resume,
        {
            "schema_version": 1,
            "demo": "system-evolution",
            "generation": 1,
            "compose_project": "idea-greenhouse-run11",
            "database_volume": "idea-greenhouse-run11_postgres-data",
            "postgres": {"database": "db", "user": "user", "password": "secret"},
        },
    )

    def runner(
        args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
    ) -> CommandResult:
        del cwd, environment, timeout
        command = tuple(args)
        return _result(command, stdout="abc123\n" if "rev-parse" in command else "")

    monkeypatch.setattr("system_evolution_grader.shutil.which", lambda name: f"/usr/bin/{name}")
    grader = SystemEvolutionGrader(
        target,
        2,
        "idea-greenhouse-run11",
        runner=runner,
        docker_path=Path("/usr/bin/docker"),
        generation_1_fixture=fixture,
        generation_1_resume=resume,
    )

    assert grader._validate_inputs() is True
    assert grader.environment["POSTGRES_DB"] == "db"
    assert grader.environment["POSTGRES_USER"] == "user"
    assert grader.environment["POSTGRES_PASSWORD"] == "secret"
    assert grader.expected_database_volume == "idea-greenhouse-run11_postgres-data"


def test_generation_two_migration_preserves_fixture_and_is_restart_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path / "target")
    grader = SystemEvolutionGrader(
        target,
        2,
        "idea-greenhouse-run12",
        docker_path=Path("/usr/bin/docker"),
    )
    fixture = _fixture_content("idea-greenhouse-run12")
    grader.generation_1_fixture_data = fixture

    def request(
        method: str, url: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any], float, str]:
        del method, payload
        idea_id = int(url.rsplit("/", 1)[1])
        expected = next(idea for idea in fixture["ideas"] if idea["id"] == idea_id)
        return 200, {**expected, "next_action": None, "archived_at": None, "version": 1}, 0.01, ""

    def compose(*args: str, timeout: int) -> CommandResult:
        del timeout
        if args[:3] == ("exec", "-T", "api"):
            return _result(tuple(args), stdout="abc123 (head)\n")
        return _result(tuple(args))

    monkeypatch.setattr(grader, "_request", request)
    monkeypatch.setattr(grader, "_compose", compose)
    monkeypatch.setattr(grader, "_wait_for_health", lambda *args, **kwargs: None)

    grader._generation_2_migration_checks()

    assert [(check.id, check.status) for check in grader.result.checks] == [
        ("G2-MIGRATION-PRESERVATION", "passed"),
        ("G2-MIGRATION-DEFAULTS", "passed"),
        ("G2-MIGRATION-ALEMBIC-CURRENT", "passed"),
        ("G2-MIGRATION-RESTART-IDEMPOTENCE", "passed"),
    ]


def test_generation_two_fields_archive_filters_and_versioned_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path / "target")
    grader = SystemEvolutionGrader(
        target,
        2,
        "idea-greenhouse-run14",
        docker_path=Path("/usr/bin/docker"),
        host_port=49123,
    )
    fixture = _fixture_content("idea-greenhouse-run14")
    grader.generation_1_fixture_data = fixture
    records = {
        idea["id"]: {**idea, "next_action": None, "archived_at": None, "version": 1}
        for idea in fixture["ideas"]
    }
    next_id = 10
    mutation_headers: list[str] = []

    def request(
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], float, str]:
        nonlocal next_id
        path = url.removeprefix("http://127.0.0.1:49123/api/ideas")
        path, _, query = path.partition("?")
        if method == "POST" and path == "":
            assert payload is not None
            if len(str((payload or {}).get("next_action") or "")) > 240:
                return _http(422, {"error": {"code": "validation_error"}})
            idea = {
                "id": next_id,
                "title": payload["title"],
                "notes": None,
                "stage": payload.get("stage", "seed"),
                "next_action": (payload.get("next_action") or "").strip() or None,
                "archived_at": None,
                "version": 1,
                "created_at": f"2026-08-23T12:00:{next_id}Z",
                "updated_at": f"2026-08-23T12:00:{next_id}Z",
            }
            records[next_id] = idea
            next_id += 1
            return _http(201, idea)
        if method == "GET" and path == "":
            filters = dict(item.split("=") for item in query.split("&") if item)
            archive = filters.get("archive", "active")
            ideas = list(records.values())
            if archive == "active":
                ideas = [idea for idea in ideas if idea["archived_at"] is None]
            elif archive == "archived":
                ideas = [idea for idea in ideas if idea["archived_at"] is not None]
            if "stage" in filters:
                ideas = [idea for idea in ideas if idea["stage"] == filters["stage"]]
            active = [idea for idea in records.values() if idea["archived_at"] is None]
            counts = {
                stage: sum(idea["stage"] == stage for idea in active)
                for stage in ("seed", "sprout", "bloom")
            }
            counts.update(
                active=len(active), archived=len(records) - len(active), total=len(records)
            )
            return _http(200, {"ideas": ideas, "counts": counts})

        parts = path.strip("/").split("/")
        idea_id = int(parts[0])
        idea = records.get(idea_id)
        if method == "GET":
            return _http(200, idea) if idea else _http(404, {})
        assert headers is not None and "If-Match" in headers
        mutation_headers.append(headers["If-Match"])
        if idea is None:
            return _http(404, {})
        assert headers["If-Match"] == f'"{idea["version"]}"'
        if method == "PATCH":
            assert payload is not None
            if len(str((payload or {}).get("next_action") or "")) > 240:
                return _http(422, {"error": {"code": "validation_error"}})
            idea.update(next_action=(payload.get("next_action") or "").strip() or None)
            _advance(idea)
            return _http(200, idea)
        if method == "POST" and parts[1] == "archive":
            if idea["archived_at"] is not None:
                return _http(
                    409,
                    {"error": {"code": "invalid_archive_state"}, "current": dict(idea)},
                )
            idea["archived_at"] = "2026-08-23T13:00:00Z"
            _advance(idea)
            return _http(200, idea)
        if method == "POST" and parts[1] == "restore":
            if idea["archived_at"] is None:
                return _http(
                    409,
                    {"error": {"code": "invalid_archive_state"}, "current": dict(idea)},
                )
            idea["archived_at"] = None
            _advance(idea)
            return _http(200, idea)
        assert method == "DELETE"
        del records[idea_id]
        return _http(204, {})

    monkeypatch.setattr(grader, "_request", request)

    grader._generation_2_archive_checks()

    assert [(check.id, check.status) for check in grader.result.checks] == [
        ("G2-API-NEXT-ACTION-CREATE", "passed"),
        ("G2-API-NEXT-ACTION-EDIT-CLEAR", "passed"),
        ("G2-API-NEXT-ACTION-LIMIT", "passed"),
        ("G2-API-ARCHIVE", "passed"),
        ("G2-API-INVALID-ARCHIVE-STATE", "passed"),
        ("G2-API-ARCHIVE-FILTERS-COUNTS", "passed"),
        ("G2-API-RESTORE", "passed"),
        ("G2-API-PERMANENT-DELETE", "passed"),
    ]
    assert set(records) == {1, 2, 3}
    assert mutation_headers


def _advance(idea: dict[str, Any]) -> None:
    idea["version"] += 1
    idea["updated_at"] = f"2026-08-23T14:00:0{idea['version']}Z"


def _http(status: int, body: dict[str, Any]) -> tuple[int, dict[str, Any], float, str]:
    return status, dict(body), 0.01, ""


def test_generation_two_missing_preserved_volume_is_a_hard_gate(tmp_path: Path) -> None:
    target = _target(tmp_path / "target")

    def runner(
        args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
    ) -> CommandResult:
        del cwd, environment, timeout
        return _result(tuple(args), returncode=1, stderr="no such volume")

    grader = SystemEvolutionGrader(
        target,
        2,
        "idea-greenhouse-run13",
        runner=runner,
        docker_path=Path("/usr/bin/docker"),
    )
    grader.database_volume = "idea-greenhouse-run13_postgres-data"
    grader.expected_database_volume = "idea-greenhouse-run13_postgres-data"

    assert grader._preserved_volume_check() is False
    check = grader.result.checks[0]
    assert check.id == "G2-DEP-PRESERVED-VOLUME"
    assert check.status == "failed"
    assert check.hard_gate is True


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


def _fixture_content(project: str) -> dict[str, Any]:
    ideas = []
    for idea_id, stage in enumerate(("seed", "sprout", "bloom"), 1):
        ideas.append(
            {
                "id": idea_id,
                "title": f"fixture {stage}",
                "notes": None,
                "stage": stage,
                "created_at": f"2026-08-22T12:00:0{idea_id}Z",
                "updated_at": f"2026-08-22T12:00:0{idea_id}Z",
            }
        )
    return {
        "schema_version": 1,
        "demo": "system-evolution",
        "generation": 1,
        "created_at": "2026-08-22T12:00:00Z",
        "target_revision": "generation-one-revision",
        "compose_project": project,
        "ideas": ideas,
    }


def _write_digested(path: Path, content: dict[str, Any]) -> None:
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content = {
        **content,
        "content_digest": f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}",
    }
    path.write_text(json.dumps(content))
    if "postgres" in content:
        path.chmod(0o600)
