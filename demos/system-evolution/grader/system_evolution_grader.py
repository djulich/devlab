# ruff: noqa: E501
"""Independent black-box grader for the system-evolution demo.

This module deliberately does not use DevLab workflow state.  It invokes an
evaluator-owned Docker executable by absolute path and confines every Compose
mutation to one validated project name.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["passed", "failed", "unverified", "grader_error"]

DIMENSIONS = (
    "api",
    "browser",
    "deployment",
    "migration",
    "concurrency",
    "target_validation",
    "hygiene",
)
PROJECT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{7,62}$")
REQUIRED_ARTIFACTS = (
    "compose.yaml",
    ".env.example",
    ".dockerignore",
    "backend/Containerfile",
    "backend/docker-entrypoint.sh",
    "frontend/Containerfile",
    "frontend/nginx.conf",
    "scripts/compose-smoke.sh",
    "Makefile",
    "README.md",
)
PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.53.1-jammy"
PLAYWRIGHT_VERSION = "1.53.1"
BROWSER_RESULT_MARKER = "DEVLAB_BROWSER_RESULT:"
BROWSER_GRADER_ERROR_MARKER = "DEVLAB_GRADER_ERROR:"


@dataclasses.dataclass(frozen=True)
class Check:
    id: str
    dimension: str
    status: Status
    duration_seconds: float
    evidence: str
    requirement_ids: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    hard_gate: bool = False


@dataclasses.dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclasses.dataclass
class GradeResult:
    generation: int
    target_revision: str = ""
    checks: list[Check] = dataclasses.field(default_factory=list)
    invalid_reasons: list[str] = dataclasses.field(default_factory=list)
    started_at: str = dataclasses.field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str = ""
    schema_version: int = 1
    demo: str = "system-evolution"

    def add(self, check: Check) -> None:
        self.checks.append(check)
        if check.hard_gate and check.status != "passed":
            self.invalid_reasons.append(check.id)

    def as_dict(self) -> dict[str, Any]:
        dimensions = {
            name: {
                status: sum(
                    check.dimension == name and check.status == status for check in self.checks
                )
                for status in ("passed", "failed", "unverified", "grader_error")
            }
            for name in DIMENSIONS
        }
        decided = sum(value["passed"] + value["failed"] for value in dimensions.values())
        passed = sum(value["passed"] for value in dimensions.values())
        return {
            "schema_version": self.schema_version,
            "demo": self.demo,
            "generation": self.generation,
            "target_revision": self.target_revision,
            "valid_run": not self.invalid_reasons
            and not any(check.status == "grader_error" for check in self.checks),
            "invalid_reasons": self.invalid_reasons,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "dimensions": dimensions,
            "unweighted_pass_rate": passed / decided if decided else None,
            "checks": [dataclasses.asdict(check) for check in self.checks],
        }


Runner = Callable[[Sequence[str], Path, Mapping[str, str], int], CommandResult]


def run_command(
    args: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout: int
) -> CommandResult:
    started = time.monotonic()
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=dict(environment),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        tuple(args),
        completed.returncode,
        completed.stdout[-20_000:],
        completed.stderr[-20_000:],
        time.monotonic() - started,
    )


class SystemEvolutionGrader:
    """Grade one immutable target checkout through its public Compose boundary."""

    def __init__(
        self,
        target: Path,
        generation: int,
        compose_project: str,
        *,
        runner: Runner = run_command,
        docker_path: Path | None = None,
        host_port: int | None = None,
        generation_1_fixture: Path | None = None,
        generation_1_fixture_out: Path | None = None,
        generation_1_resume: Path | None = None,
        generation_1_resume_out: Path | None = None,
    ) -> None:
        self.target = target.resolve()
        self.generation = generation
        self.project = validate_project_name(compose_project)
        self.runner = runner
        discovered = shutil.which("docker") if docker_path is None else str(docker_path)
        self.docker = Path(discovered).resolve() if discovered else None
        self.host_port = host_port or available_port()
        self.generation_1_fixture = (
            generation_1_fixture.resolve() if generation_1_fixture is not None else None
        )
        self.generation_1_resume = (
            generation_1_resume.resolve() if generation_1_resume is not None else None
        )
        for name, artifact in (
            ("generation 1 fixture", self.generation_1_fixture),
            ("generation 1 resume state", self.generation_1_resume),
        ):
            if artifact is not None and artifact.is_relative_to(self.target):
                raise ValueError(f"{name} must be outside the target checkout")
        self.generation_1_fixture_out = (
            generation_1_fixture_out.resolve() if generation_1_fixture_out is not None else None
        )
        if (
            self.generation_1_fixture_out is not None
            and self.generation_1_fixture_out.is_relative_to(self.target)
        ):
            raise ValueError("generation 1 fixture output must be outside the target checkout")
        self.generation_1_resume_out = (
            generation_1_resume_out.resolve() if generation_1_resume_out is not None else None
        )
        if (
            self.generation_1_resume_out is not None
            and self.generation_1_resume_out.is_relative_to(self.target)
        ):
            raise ValueError("generation 1 resume output must be outside the target checkout")
        suffix = secrets.token_hex(6)
        self.prefix = f"grader-{suffix}"
        self.environment = self._environment(suffix)
        self.result = GradeResult(generation)
        self.started = False
        self.lifecycle_attempted = False
        self.database_volume = ""
        self.expected_database_volume = ""
        self.generation_1_fixture_data: dict[str, Any] | None = None

    def grade(self) -> GradeResult:
        try:
            if not self._validate_inputs():
                return self._finish()
            self._structural_checks()
            if self.docker is None:
                self._docker_unverified()
                return self._finish()
            if not self._compose_prerequisite_check():
                return self._finish()
            if not self._compose_config_checks():
                return self._finish()
            if self.generation == 2 and not self._preserved_volume_check():
                return self._finish()
            build = self._compose("build", timeout=1200)
            self._command_check(
                "G1-DEP-BUILD",
                "deployment",
                build,
                ("G1-DEP-04", "G1-DEP-05"),
                hard_gate=True,
            )
            if build.returncode != 0:
                return self._finish()
            self.lifecycle_attempted = True
            up = self._compose("up", "-d", "--wait", "--wait-timeout", "120", timeout=180)
            self.started = up.returncode == 0
            self._command_check(
                "G1-DEP-START",
                "deployment",
                up,
                ("G1-DEP-08",),
                hard_gate=True,
            )
            if not self.started:
                self._capture_failure_diagnostics()
                return self._finish()
            self._runtime_topology_check()
            if self.generation == 1:
                self._api_checks()
                self._browser_checks()
                self._persistence_checks()
                self._create_generation_1_fixture()
            else:
                self._generation_2_migration_checks()
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
            self.result.add(
                Check(
                    "GRADER-EXECUTION",
                    "deployment",
                    "grader_error",
                    0,
                    f"{type(error).__name__}: {error}",
                )
            )
            self._capture_failure_diagnostics()
        finally:
            self._cleanup()
            self._final_clean_check()
            self.result.finished_at = datetime.now(UTC).isoformat()
        return self._finish()

    def _validate_inputs(self) -> bool:
        started = time.monotonic()
        if self.generation not in (1, 2):
            raise ValueError("generation must be 1 or 2")
        if self.generation == 2 and (
            self.generation_1_fixture is None
            or not self.generation_1_fixture.is_file()
            or self.generation_1_resume is None
            or not self.generation_1_resume.is_file()
        ):
            self.result.add(
                Check(
                    "INPUT-GENERATION-1-FIXTURE",
                    "migration",
                    "grader_error",
                    0,
                    "generation 2 requires existing --generation-1-fixture and "
                    "--generation-1-resume artifacts",
                )
            )
            return False
        if self.generation == 2:
            try:
                resume_path = self.generation_1_resume
                if resume_path is None:
                    raise ValueError("generation 1 resume state path is missing")
                if resume_path.stat().st_mode & 0o077:
                    raise ValueError(
                        "generation 1 resume state must not be group/world accessible"
                    )
                fixture = load_digested_json(self.generation_1_fixture)
                resume = load_digested_json(resume_path)
                validate_generation_1_artifacts(fixture, resume, self.project)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self.result.add(
                    Check(
                        "INPUT-GENERATION-1-ARTIFACTS",
                        "migration",
                        "grader_error",
                        0,
                        f"invalid generation 1 artifact: {error}",
                    )
                )
                return False
            self.generation_1_fixture_data = fixture
            self.environment.update(
                {
                    "POSTGRES_DB": str(resume["postgres"]["database"]),
                    "POSTGRES_USER": str(resume["postgres"]["user"]),
                    "POSTGRES_PASSWORD": str(resume["postgres"]["password"]),
                }
            )
            self.expected_database_volume = str(resume["database_volume"])
        if not self.target.is_dir():
            self.result.add(
                Check("INPUT-TARGET", "hygiene", "grader_error", 0, "target is not a directory")
            )
            return False
        git = Path(shutil.which("git") or "").resolve() if shutil.which("git") else None
        if git is None:
            self.result.add(
                Check("INPUT-GIT", "hygiene", "grader_error", 0, "git executable unavailable")
            )
            return False
        revision = self.runner((str(git), "rev-parse", "HEAD"), self.target, self.environment, 10)
        clean = self.runner((str(git), "status", "--porcelain"), self.target, self.environment, 10)
        self.result.target_revision = revision.stdout.strip() if revision.returncode == 0 else ""
        passed = revision.returncode == 0 and clean.returncode == 0 and not clean.stdout.strip()
        self.result.add(
            Check(
                "INPUT-CLEAN-REVISION",
                "hygiene",
                "passed" if passed else "grader_error",
                time.monotonic() - started,
                f"revision={self.result.target_revision or 'unknown'}; "
                f"clean={not clean.stdout.strip()}",
            )
        )
        return passed

    def _structural_checks(self) -> None:
        started = time.monotonic()
        missing = [path for path in REQUIRED_ARTIFACTS if not (self.target / path).is_file()]
        self.result.add(
            Check(
                "G1-STRUCT-ARTIFACTS",
                "hygiene",
                "failed" if missing else "passed",
                time.monotonic() - started,
                "missing: " + ", ".join(missing)
                if missing
                else "all required deployment artifacts exist",
                ("G1-DEP-01",),
            )
        )
        ignored = (
            (self.target / ".dockerignore").read_text(errors="replace")
            if (self.target / ".dockerignore").is_file()
            else ""
        )
        required_ignores = (".git", ".devlab", ".env", "node_modules", "dist", "__pycache__")
        absent = [entry for entry in required_ignores if entry not in ignored]
        self.result.add(
            Check(
                "G1-DEP-CONTEXT-HYGIENE",
                "hygiene",
                "failed" if absent else "passed",
                0,
                "missing ignore rules: " + ", ".join(absent)
                if absent
                else "sensitive and generated paths excluded",
                ("G1-DEP-07",),
            )
        )

    def _compose_config_checks(self) -> bool:
        command = self._compose("config", "--format", "json", timeout=30)
        self._command_check("G1-DEP-COMPOSE-CONFIG", "deployment", command, ("G1-DEP-01",))
        if command.returncode != 0:
            return False
        config = json.loads(command.stdout)
        services = config.get("services", {})
        exact = set(services) == {"db", "api", "frontend"}
        self.result.add(
            Check(
                "G1-DEP-THREE-SERVICES",
                "deployment",
                "passed" if exact else "failed",
                0,
                f"services={sorted(services)}",
                ("G1-DEP-02",),
                hard_gate=True,
            )
        )
        published = {name: bool(service.get("ports")) for name, service in services.items()}
        ports_ok = published == {"db": False, "api": False, "frontend": True}
        self.result.add(
            Check(
                "G1-DEP-PUBLIC-BOUNDARY",
                "deployment",
                "passed" if ports_ok else "failed",
                0,
                f"published_ports={published}",
                ("G1-DEP-02",),
                hard_gate=True,
            )
        )
        db = services.get("db", {})
        api = services.get("api", {})
        frontend = services.get("frontend", {})
        db_mounts = db.get("volumes", [])
        named_volume = any(
            isinstance(mount, dict) and mount.get("type") == "volume" for mount in db_mounts
        )
        volume_mount = next(
            (
                mount
                for mount in db_mounts
                if isinstance(mount, dict) and mount.get("type") == "volume"
            ),
            {},
        )
        volume_source = str(volume_mount.get("source", ""))
        volume_config = config.get("volumes", {}).get(volume_source, {})
        self.database_volume = str(volume_config.get("name", volume_source))
        health_dependencies = (
            bool(db.get("healthcheck"))
            and bool(api.get("healthcheck"))
            and bool(frontend.get("healthcheck"))
            and "db" in api.get("depends_on", {})
            and "api" in frontend.get("depends_on", {})
        )
        self.result.add(
            Check(
                "G1-DEP-HEALTH-DEPENDENCIES",
                "deployment",
                "passed" if health_dependencies else "failed",
                0,
                f"named_db_volume={named_volume}; health/dependencies={health_dependencies}",
                ("G1-DEP-03", "G1-DEP-04", "G1-DEP-05"),
            )
        )
        self.result.add(
            Check(
                "G1-DEP-NAMED-VOLUME",
                "deployment",
                "passed" if named_volume and volume_source == "postgres-data" else "failed",
                0,
                f"db_mounts={db_mounts!r}; resolved_volume={self.database_volume!r}",
                ("G1-DEP-03",),
            )
        )
        return exact and ports_ok

    def _preserved_volume_check(self) -> bool:
        if self.docker is None or not self.database_volume:
            return False
        if self.database_volume != self.expected_database_volume:
            self.result.add(
                Check(
                    "G2-DEP-PRESERVED-VOLUME",
                    "migration",
                    "failed",
                    0,
                    f"generation 2 resolved volume={self.database_volume!r}; "
                    f"generation 1 volume={self.expected_database_volume!r}",
                    ("G2-DATA-02", "G2-DEP-02"),
                    hard_gate=True,
                )
            )
            return False
        command = self.runner(
            (str(self.docker), "volume", "inspect", self.database_volume),
            self.target,
            self.environment,
            30,
        )
        passed = command.returncode == 0
        self.result.add(
            Check(
                "G2-DEP-PRESERVED-VOLUME",
                "migration",
                "passed" if passed else "failed",
                command.duration_seconds,
                f"expected volume={self.database_volume}; {command_evidence(command)}",
                ("G2-DATA-02", "G2-DEP-02"),
                hard_gate=True,
            )
        )
        return passed

    def _compose_prerequisite_check(self) -> bool:
        command = self._compose("version", "--short", timeout=15)
        passed = command.returncode == 0 and bool(command.stdout.strip())
        self.result.add(
            Check(
                "PREREQ-DOCKER-COMPOSE",
                "deployment",
                "passed" if passed else "unverified",
                command.duration_seconds,
                command_evidence(command),
                hard_gate=True,
            )
        )
        return passed

    def _runtime_topology_check(self) -> None:
        result = self._compose("ps", "--format", "json", timeout=30)
        if result.returncode != 0:
            self._command_check(
                "G1-DEP-RUNTIME-TOPOLOGY", "deployment", result, ("G1-DEP-02",), hard_gate=True
            )
            return
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        services = {row.get("Service") for row in rows if row.get("State") == "running"}
        healthy = all(row.get("Health") == "healthy" for row in rows)
        passed = services == {"db", "api", "frontend"} and healthy
        self.result.add(
            Check(
                "G1-DEP-RUNTIME-TOPOLOGY",
                "deployment",
                "passed" if passed else "failed",
                result.duration_seconds,
                f"running={sorted(str(item) for item in services)}; healthy={healthy}",
                ("G1-DEP-02",),
                hard_gate=True,
            )
        )

    def _api_checks(self) -> None:
        base = f"http://127.0.0.1:{self.host_port}/api"
        self._http_check(
            "G1-API-HEALTH",
            "GET",
            f"{base}/health",
            200,
            lambda body: body == {"status": "ok", "database": "ok"},
            ("G1-API-01",),
        )
        self._http_check(
            "G1-API-EMPTY-LIST",
            "GET",
            f"{base}/ideas",
            200,
            lambda body: (
                body == {"ideas": [], "counts": {"seed": 0, "sprout": 0, "bloom": 0, "total": 0}}
            ),
            ("G1-API-03",),
        )
        created = self._request(
            "POST", f"{base}/ideas", {"title": f"  {self.prefix} café 🌱  ", "notes": "   "}
        )
        create_ok = (
            created[0] == 201
            and created[1].get("title") == f"{self.prefix} café 🌱"
            and created[1].get("notes") is None
            and created[1].get("stage") == "seed"
        )
        self.result.add(
            Check(
                "G1-API-CREATE-NORMALIZE",
                "api",
                "passed" if create_ok else "failed",
                created[2],
                summarize_http(created),
                ("G1-API-02", "G1-DATA-01"),
            )
        )
        idea_id = created[1].get("id") if create_ok else None
        for label, payload in (
            ("BLANK", {"title": "  "}),
            ("OVERLONG", {"title": "x" * 121}),
            ("WRONG-TYPE", {"title": 7}),
        ):
            self._http_check(
                f"G1-API-VALIDATE-{label}",
                "POST",
                f"{base}/ideas",
                range(400, 500),
                lambda body: body.get("error", {}).get("code") == "validation_error",
                ("G1-API-07",),
                payload,
            )
        if not isinstance(idea_id, int):
            self.result.add(
                Check(
                    "G1-API-CRUD",
                    "api",
                    "unverified",
                    0,
                    "create prerequisite failed",
                    ("G1-API-03", "G1-API-04", "G1-API-05", "G1-API-06"),
                )
            )
            return
        self._http_check(
            "G1-API-READ",
            "GET",
            f"{base}/ideas/{idea_id}",
            200,
            lambda body: body.get("id") == idea_id,
            ("G1-API-04",),
        )
        before = created[1].get("updated_at")
        updated = self._request(
            "PATCH", f"{base}/ideas/{idea_id}", {"notes": "  explored  ", "stage": "sprout"}
        )
        update_ok = (
            updated[0] == 200
            and updated[1].get("notes") == "explored"
            and updated[1].get("stage") == "sprout"
            and updated[1].get("updated_at") != before
        )
        self.result.add(
            Check(
                "G1-API-PARTIAL-UPDATE",
                "api",
                "passed" if update_ok else "failed",
                updated[2],
                summarize_http(updated),
                ("G1-API-05",),
            )
        )
        self._http_check(
            "G1-API-FILTER-COUNTS",
            "GET",
            f"{base}/ideas?stage=sprout",
            200,
            lambda body: (
                [item.get("id") for item in body.get("ideas", [])] == [idea_id]
                and body.get("counts", {}).get("total") == 1
                and body.get("counts", {}).get("sprout") == 1
            ),
            ("G1-API-03",),
        )
        self._http_check(
            "G1-API-DELETE",
            "DELETE",
            f"{base}/ideas/{idea_id}",
            204,
            lambda body: body == {},
            ("G1-API-06",),
        )
        self._http_check(
            "G1-API-MISSING",
            "GET",
            f"{base}/ideas/{idea_id}",
            404,
            lambda body: body.get("error", {}).get("code") == "idea_not_found",
            ("G1-API-04", "G1-API-07"),
        )

    def _persistence_checks(self) -> None:
        base = f"http://127.0.0.1:{self.host_port}/api"
        created = self._request("POST", f"{base}/ideas", {"title": f"{self.prefix}-persist"})
        idea_id = created[1].get("id")
        restart = self._compose("restart", "api", timeout=120)
        if restart.returncode == 0:
            self._wait_for_health(base)
        read = (
            self._request("GET", f"{base}/ideas/{idea_id}")
            if isinstance(idea_id, int)
            else (0, {}, 0.0, "create failed")
        )
        passed = restart.returncode == 0 and read[0] == 200 and read[1].get("id") == idea_id
        self.result.add(
            Check(
                "G1-DEP-API-RESTART-PERSISTENCE",
                "deployment",
                "passed" if passed else "failed",
                restart.duration_seconds + read[2],
                f"restart_exit={restart.returncode}; {summarize_http(read)}",
                ("G1-DATA-02", "G1-DEP-08"),
            )
        )
        down = self._compose("down", "--remove-orphans", timeout=120)
        up = self._compose("up", "-d", "--wait", "--wait-timeout", "120", timeout=180)
        self.started = up.returncode == 0
        if self.started:
            self._wait_for_health(base)
        read = (
            self._request("GET", f"{base}/ideas/{idea_id}")
            if isinstance(idea_id, int)
            else (0, {}, 0.0, "create failed")
        )
        passed = (
            down.returncode == 0
            and up.returncode == 0
            and read[0] == 200
            and read[1].get("id") == idea_id
        )
        self.result.add(
            Check(
                "G1-DEP-STACK-RESTART-PERSISTENCE",
                "deployment",
                "passed" if passed else "failed",
                down.duration_seconds + up.duration_seconds + read[2],
                f"down_exit={down.returncode}; up_exit={up.returncode}; {summarize_http(read)}",
                ("G1-DATA-02", "G1-DEP-08"),
            )
        )
        if isinstance(idea_id, int):
            deleted = self._request("DELETE", f"{base}/ideas/{idea_id}")
            if deleted[0] != 204:
                self.result.add(
                    Check(
                        "G1-FIXTURE-PROBE-CLEANUP",
                        "migration",
                        "grader_error",
                        deleted[2],
                        "could not remove persistence probe before fixture seeding; "
                        f"{summarize_http(deleted)}",
                    )
                )

    def _create_generation_1_fixture(self) -> None:
        output = self.generation_1_fixture_out
        resume_output = self.generation_1_resume_out
        if output is None or resume_output is None:
            self.result.add(
                Check(
                    "G1-EVOLUTION-FIXTURE",
                    "migration",
                    "unverified",
                    0,
                    "generation 1 fixture and resume output paths must be configured",
                    hard_gate=True,
                )
            )
            return
        if output.exists():
            self.result.add(
                Check(
                    "G1-EVOLUTION-FIXTURE",
                    "migration",
                    "grader_error",
                    0,
                    f"refusing to replace existing fixture artifact: {output}",
                )
            )
            return
        if resume_output.exists():
            self.result.add(
                Check(
                    "G1-EVOLUTION-FIXTURE",
                    "migration",
                    "grader_error",
                    0,
                    f"refusing to replace existing resume artifact: {resume_output}",
                )
            )
            return
        if not self.database_volume:
            self.result.add(
                Check(
                    "G1-EVOLUTION-FIXTURE",
                    "migration",
                    "grader_error",
                    0,
                    "resolved generation 1 database volume is unavailable",
                )
            )
            return
        started = time.monotonic()
        base = f"http://127.0.0.1:{self.host_port}/api/ideas"
        requests = (
            {
                "title": f"{self.prefix} fixture seed",
                "notes": "Capture the first café idea 🌱",
            },
            {
                "title": f"{self.prefix} fixture sprout",
                "notes": "Explore the preserved migration path",
                "stage": "sprout",
            },
            {
                "title": f"{self.prefix} fixture bloom",
                "notes": None,
                "stage": "bloom",
            },
        )
        ideas: list[dict[str, Any]] = []
        created_ids: list[int] = []
        failures: list[str] = []
        for payload in requests:
            response = self._request("POST", base, payload)
            response_id = response[1].get("id")
            if (
                response[0] == 201
                and isinstance(response_id, int)
                and not isinstance(response_id, bool)
            ):
                created_ids.append(response_id)
            problem = validate_generation_1_fixture_idea(response[1], payload)
            if response[0] != 201 or problem:
                failures.append(f"{payload['title']}: {problem or summarize_http(response)}")
            else:
                ideas.append(response[1])
        if failures:
            self._remove_partial_fixture(base, created_ids)
            self.result.add(
                Check(
                    "G1-EVOLUTION-FIXTURE",
                    "migration",
                    "failed",
                    time.monotonic() - started,
                    "; ".join(failures)[:4000],
                    ("G1-DATA-01", "G1-API-02"),
                    hard_gate=True,
                )
            )
            return
        ids = [idea["id"] for idea in ideas]
        if len(set(ids)) != 3:
            self._remove_partial_fixture(base, created_ids)
            self.result.add(
                Check(
                    "G1-EVOLUTION-FIXTURE",
                    "migration",
                    "failed",
                    time.monotonic() - started,
                    f"fixture IDs are not unique: {ids}",
                    ("G1-DATA-01",),
                    hard_gate=True,
                )
            )
            return
        content: dict[str, Any] = {
            "schema_version": 1,
            "demo": "system-evolution",
            "generation": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "target_revision": self.result.target_revision,
            "compose_project": self.project,
            "ideas": ideas,
        }
        canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content["content_digest"] = f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
        resume: dict[str, Any] = {
            "schema_version": 1,
            "demo": "system-evolution",
            "generation": 1,
            "compose_project": self.project,
            "database_volume": self.database_volume,
            "postgres": {
                "database": self.environment["POSTGRES_DB"],
                "user": self.environment["POSTGRES_USER"],
                "password": self.environment["POSTGRES_PASSWORD"],
            },
        }
        resume_canonical = json.dumps(
            resume, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        resume["content_digest"] = (
            f"sha256:{hashlib.sha256(resume_canonical.encode()).hexdigest()}"
        )
        resume_written = False
        try:
            write_new_json(resume_output, resume, mode=0o600)
            resume_written = True
            write_new_json(output, content)
        except OSError as error:
            if resume_written:
                resume_output.unlink(missing_ok=True)
            self._remove_partial_fixture(base, created_ids)
            self.result.add(
                Check(
                    "G1-EVOLUTION-FIXTURE",
                    "migration",
                    "grader_error",
                    time.monotonic() - started,
                    f"could not write fixture: {error}",
                )
            )
            return
        self.result.add(
            Check(
                "G1-EVOLUTION-FIXTURE",
                "migration",
                "passed",
                time.monotonic() - started,
                f"seeded idea IDs {[idea['id'] for idea in ideas]}; "
                f"digest={content['content_digest']}",
                ("G1-DATA-01", "G1-API-02"),
                (str(output), str(resume_output)),
            )
        )

    def _remove_partial_fixture(self, base: str, idea_ids: Sequence[int]) -> None:
        failures = []
        for idea_id in dict.fromkeys(idea_ids):
            response = self._request("DELETE", f"{base}/{idea_id}")
            if response[0] != 204:
                failures.append(f"id={idea_id}: {summarize_http(response)}")
        if failures:
            self.result.add(
                Check(
                    "G1-EVOLUTION-FIXTURE-CLEANUP",
                    "migration",
                    "grader_error",
                    0,
                    "could not remove partial fixture records; " + "; ".join(failures)[:3800],
                )
            )

    def _generation_2_migration_checks(self) -> None:
        fixture = self.generation_1_fixture_data
        if fixture is None:
            self.result.add(
                Check(
                    "G2-MIGRATION-FIXTURE",
                    "migration",
                    "grader_error",
                    0,
                    "validated generation 1 fixture is unavailable",
                )
            )
            return
        expected_ideas = fixture["ideas"]
        responses = self._fetch_fixture_ideas(expected_ideas)
        preserved_errors: list[str] = []
        default_errors: list[str] = []
        preserved_fields = ("id", "title", "notes", "stage", "created_at", "updated_at")
        expected_fields = {
            *preserved_fields,
            "next_action",
            "archived_at",
            "version",
        }
        for expected, response in zip(expected_ideas, responses, strict=True):
            status, current, _, error = response
            idea_id = expected["id"]
            if status != 200:
                preserved_errors.append(f"id={idea_id}: status={status}; {error}")
                continue
            changed = [
                field for field in preserved_fields if current.get(field) != expected.get(field)
            ]
            if changed:
                preserved_errors.append(f"id={idea_id}: changed fields={changed}")
            if set(current) != expected_fields:
                default_errors.append(
                    f"id={idea_id}: fields={sorted(current)}; expected={sorted(expected_fields)}"
                )
            elif (
                current["next_action"] is not None
                or current["archived_at"] is not None
                or current["version"] != 1
            ):
                default_errors.append(
                    f"id={idea_id}: next_action={current['next_action']!r}, "
                    f"archived_at={current['archived_at']!r}, version={current['version']!r}"
                )
        self.result.add(
            Check(
                "G2-MIGRATION-PRESERVATION",
                "migration",
                "failed" if preserved_errors else "passed",
                sum(response[2] for response in responses),
                "; ".join(preserved_errors)
                if preserved_errors
                else "all generation 1 fields preserved",
                ("G2-DATA-02", "G2-DEP-09"),
                hard_gate=True,
            )
        )
        self.result.add(
            Check(
                "G2-MIGRATION-DEFAULTS",
                "migration",
                "failed" if default_errors else "passed",
                0,
                "; ".join(default_errors)
                if default_errors
                else "new fields are null/null/version 1 on all fixture records",
                ("G2-DATA-01", "G2-DATA-02"),
                hard_gate=True,
            )
        )
        alembic = self._compose("exec", "-T", "api", "alembic", "current", timeout=30)
        current = alembic.returncode == 0 and "(head)" in alembic.stdout
        self.result.add(
            Check(
                "G2-MIGRATION-ALEMBIC-CURRENT",
                "migration",
                "passed" if current else "failed",
                alembic.duration_seconds,
                command_evidence(alembic),
                ("G2-DATA-02", "G2-DEP-04"),
            )
        )
        restart = self._compose("restart", "api", timeout=120)
        if restart.returncode == 0:
            self._wait_for_health(f"http://127.0.0.1:{self.host_port}/api")
        repeated = self._fetch_fixture_ideas(expected_ideas) if restart.returncode == 0 else []
        repeat_ok = (
            restart.returncode == 0
            and len(repeated) == len(expected_ideas)
            and all(
                response[0] == 200
                and all(
                    response[1].get(field) == expected.get(field) for field in preserved_fields
                )
                and response[1].get("next_action") is None
                and response[1].get("archived_at") is None
                and response[1].get("version") == 1
                for expected, response in zip(expected_ideas, repeated, strict=True)
            )
        )
        self.result.add(
            Check(
                "G2-MIGRATION-RESTART-IDEMPOTENCE",
                "migration",
                "passed" if repeat_ok else "failed",
                restart.duration_seconds + sum(response[2] for response in repeated),
                f"restart_exit={restart.returncode}; fixture records rechecked={len(repeated)}",
                ("G2-DATA-02", "G2-DEP-04"),
                hard_gate=True,
            )
        )

    def _fetch_fixture_ideas(
        self, ideas: Sequence[Mapping[str, Any]]
    ) -> list[tuple[int, dict[str, Any], float, str]]:
        base = f"http://127.0.0.1:{self.host_port}/api/ideas"
        return [self._request("GET", f"{base}/{idea['id']}") for idea in ideas]

    def _browser_checks(self) -> None:
        if self.docker is None:
            return
        with tempfile.TemporaryDirectory(prefix="devlab-system-evolution-browser-") as directory:
            script = Path(directory) / "browser-check.js"
            script.write_text(BROWSER_CHECK_SCRIPT)
            command = (
                str(self.docker),
                "run",
                "--rm",
                "--pull=missing",
                "--network=host",
                "--mount",
                f"type=bind,src={script},dst=/grader/browser-check.js,readonly",
                PLAYWRIGHT_IMAGE,
                "bash",
                "-lc",
                "npm install --prefix /tmp/evaluator-tools --no-save "
                f"playwright@{PLAYWRIGHT_VERSION} >/tmp/playwright-install.log 2>&1 || "
                "{ cat /tmp/playwright-install.log >&2; exit 1; }; "
                'node /grader/browser-check.js "$0"',
                f"http://127.0.0.1:{self.host_port}",
            )
            try:
                completed = self.runner(command, self.target, self.environment, 360)
            except (OSError, subprocess.SubprocessError) as error:
                self.result.add(
                    Check(
                        "G1-UI-GRADER",
                        "browser",
                        "grader_error",
                        0,
                        f"browser evaluator could not run: {error}",
                    )
                )
                return
        output = f"{completed.stdout}\n{completed.stderr}"
        marker_line = next(
            (line for line in output.splitlines() if line.startswith(BROWSER_RESULT_MARKER)),
            None,
        )
        if marker_line is None or completed.returncode != 0:
            status: Status = "grader_error"
            evidence = command_evidence(completed)
            if BROWSER_GRADER_ERROR_MARKER in output:
                evidence = output[-4000:]
            self.result.add(
                Check("G1-UI-GRADER", "browser", status, completed.duration_seconds, evidence)
            )
            return
        try:
            payload = json.loads(marker_line.removeprefix(BROWSER_RESULT_MARKER))
            checks = payload["checks"]
            if not isinstance(checks, list):
                raise ValueError("browser result checks must be a list")
            for item in checks:
                self.result.add(
                    Check(
                        str(item["id"]),
                        "browser",
                        "passed" if item["passed"] else "failed",
                        completed.duration_seconds / max(len(checks), 1),
                        str(item.get("evidence", ""))[:4000],
                        tuple(str(value) for value in item.get("requirement_ids", [])),
                    )
                )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.result.add(
                Check(
                    "G1-UI-GRADER",
                    "browser",
                    "grader_error",
                    completed.duration_seconds,
                    f"invalid browser result: {error}; output={output[-4000:]}",
                )
            )

    def _wait_for_health(self, base: str, deadline_seconds: float = 60) -> None:
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            status, _, _, _ = self._request("GET", f"{base}/health")
            if status == 200:
                return
            time.sleep(0.5)

    def _http_check(
        self,
        check_id: str,
        method: str,
        url: str,
        expected_status: int | range,
        predicate: Callable[[dict[str, Any]], bool],
        requirements: tuple[str, ...],
        payload: dict[str, Any] | None = None,
    ) -> None:
        response = self._request(method, url, payload)
        expected = (
            response[0] in expected_status
            if isinstance(expected_status, range)
            else response[0] == expected_status
        )
        passed = expected and predicate(response[1])
        self.result.add(
            Check(
                check_id,
                "api",
                "passed" if passed else "failed",
                response[2],
                summarize_http(response),
                requirements,
            )
        )

    def _request(
        self, method: str, url: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any], float, str]:
        started = time.monotonic()
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            url, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                return (
                    response.status,
                    json.loads(raw) if raw else {},
                    time.monotonic() - started,
                    "",
                )
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {}
            return error.code, body, time.monotonic() - started, str(error)
        except (OSError, TimeoutError) as error:
            return 0, {}, time.monotonic() - started, f"{type(error).__name__}: {error}"

    def _compose(self, *args: str, timeout: int) -> CommandResult:
        if self.docker is None:
            raise RuntimeError("Docker is unavailable")
        command = (str(self.docker), "compose", "--project-name", self.project, *args)
        return self.runner(command, self.target, self.environment, timeout)

    def _command_check(
        self,
        check_id: str,
        dimension: str,
        command: CommandResult,
        requirements: tuple[str, ...],
        *,
        hard_gate: bool = False,
    ) -> None:
        self.result.add(
            Check(
                check_id,
                dimension,
                "passed" if command.returncode == 0 else "failed",
                command.duration_seconds,
                command_evidence(command),
                requirements,
                hard_gate=hard_gate,
            )
        )

    def _docker_unverified(self) -> None:
        self.result.add(
            Check(
                "PREREQ-DOCKER-COMPOSE",
                "deployment",
                "unverified",
                0,
                "Docker Engine with Compose v2 is unavailable",
                hard_gate=True,
            )
        )

    def _capture_failure_diagnostics(self) -> None:
        if self.docker is None or not self.lifecycle_attempted:
            return
        for name, args in (("ps", ("ps",)), ("logs", ("logs", "--no-color", "--tail", "200"))):
            try:
                command = self._compose(*args, timeout=30)
                self.result.add(
                    Check(
                        f"DIAGNOSTIC-{name.upper()}",
                        "deployment",
                        "unverified",
                        command.duration_seconds,
                        command_evidence(command),
                    )
                )
            except (OSError, subprocess.SubprocessError) as error:
                self.result.add(
                    Check(
                        f"DIAGNOSTIC-{name.upper()}", "deployment", "grader_error", 0, str(error)
                    )
                )

    def _cleanup(self) -> None:
        if self.docker is None or not self.lifecycle_attempted:
            return
        try:
            cleanup = self._compose("down", "--remove-orphans", timeout=120)
            if cleanup.returncode != 0:
                self.result.add(
                    Check(
                        "GRADER-CLEANUP",
                        "deployment",
                        "grader_error",
                        cleanup.duration_seconds,
                        command_evidence(cleanup),
                    )
                )
        except (OSError, subprocess.SubprocessError) as error:
            self.result.add(Check("GRADER-CLEANUP", "deployment", "grader_error", 0, str(error)))

    def _final_clean_check(self) -> None:
        git_path = shutil.which("git")
        if not git_path or not self.target.is_dir():
            return
        try:
            clean = self.runner(
                (str(Path(git_path).resolve()), "status", "--porcelain"),
                self.target,
                self.environment,
                10,
            )
            self.result.add(
                Check(
                    "FINAL-CLEAN-WORKTREE",
                    "hygiene",
                    "passed"
                    if clean.returncode == 0 and not clean.stdout.strip()
                    else "grader_error",
                    clean.duration_seconds,
                    "target worktree unchanged"
                    if not clean.stdout.strip()
                    else clean.stdout[-2000:],
                )
            )
        except (OSError, subprocess.SubprocessError) as error:
            self.result.add(
                Check("FINAL-CLEAN-WORKTREE", "hygiene", "grader_error", 0, str(error))
            )

    def _finish(self) -> GradeResult:
        if not self.result.finished_at:
            self.result.finished_at = datetime.now(UTC).isoformat()
        return self.result

    def _environment(self, suffix: str) -> dict[str, str]:
        # Explicit values prevent target .env defaults from selecting shared ports or credentials.
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": str(Path.home()),
            "COMPOSE_PROJECT_NAME": self.project,
            "APP_PORT": str(self.host_port),
            "POSTGRES_DB": f"grader_{suffix}",
            "POSTGRES_USER": f"grader_{suffix}",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        }


def validate_project_name(value: str) -> str:
    if not PROJECT_PATTERN.fullmatch(value):
        raise ValueError(
            "compose project must be 8-63 lowercase letters, digits, underscores, or hyphens"
        )
    return value


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def validate_generation_1_fixture_idea(idea: dict[str, Any], request: Mapping[str, Any]) -> str:
    required = {"id", "title", "notes", "stage", "created_at", "updated_at"}
    if set(idea) != required:
        return f"response fields={sorted(idea)}; expected={sorted(required)}"
    if not isinstance(idea["id"], int) or isinstance(idea["id"], bool) or idea["id"] <= 0:
        return f"invalid positive integer ID: {idea['id']!r}"
    expected_stage = request.get("stage", "seed")
    for field, expected in (
        ("title", request["title"]),
        ("notes", request.get("notes")),
        ("stage", expected_stage),
    ):
        if idea[field] != expected:
            return f"{field}={idea[field]!r}; expected={expected!r}"
    if not all(
        isinstance(idea[field], str) and idea[field] for field in ("created_at", "updated_at")
    ):
        return "created_at and updated_at must be non-empty timestamp strings"
    return ""


def write_new_json(path: Path, content: Mapping[str, Any], *, mode: int = 0o644) -> None:
    """Atomically create evaluator evidence without replacing an existing artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temporary.write_text(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.chmod(mode)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_digested_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise ValueError("artifact path is missing")
    content = json.loads(path.read_text())
    if not isinstance(content, dict):
        raise ValueError(f"{path} must contain a JSON object")
    digest = content.pop("content_digest", None)
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected = f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
    if not secrets.compare_digest(str(digest), expected):
        raise ValueError(f"{path} content digest does not match")
    content["content_digest"] = digest
    return content


def validate_generation_1_artifacts(
    fixture: Mapping[str, Any], resume: Mapping[str, Any], compose_project: str
) -> None:
    for name, content in (("fixture", fixture), ("resume", resume)):
        if content.get("schema_version") != 1 or content.get("demo") != "system-evolution":
            raise ValueError(f"{name} has an unsupported schema or demo")
        if content.get("generation") != 1:
            raise ValueError(f"{name} is not a generation 1 artifact")
        if content.get("compose_project") != compose_project:
            raise ValueError(f"{name} Compose project does not match {compose_project!r}")
    ideas = fixture.get("ideas")
    if not isinstance(fixture.get("target_revision"), str) or not fixture["target_revision"]:
        raise ValueError("fixture target revision is missing")
    if not isinstance(fixture.get("created_at"), str) or not fixture["created_at"]:
        raise ValueError("fixture creation timestamp is missing")
    if not isinstance(ideas, list) or len(ideas) != 3:
        raise ValueError("fixture must contain exactly three ideas")
    stages = []
    ids = []
    for idea in ideas:
        if not isinstance(idea, dict):
            raise ValueError("fixture ideas must be objects")
        problem = validate_generation_1_fixture_idea(idea, idea)
        if problem:
            raise ValueError(f"invalid fixture idea: {problem}")
        stages.append(idea["stage"])
        ids.append(idea["id"])
    if sorted(stages) != ["bloom", "seed", "sprout"] or len(set(ids)) != 3:
        raise ValueError("fixture must contain unique seed, sprout, and bloom ideas")
    postgres = resume.get("postgres")
    if not isinstance(resume.get("database_volume"), str) or not resume["database_volume"]:
        raise ValueError("resume artifact has no resolved database volume")
    if not isinstance(postgres, dict) or not all(
        isinstance(postgres.get(key), str) and postgres[key]
        for key in ("database", "user", "password")
    ):
        raise ValueError("resume artifact has invalid PostgreSQL configuration")


def command_evidence(result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    return f"exit={result.returncode}" + (f"; {detail[-4000:]}" if detail else "")


def summarize_http(response: tuple[int, dict[str, Any], float, str]) -> str:
    status, body, _, error = response
    rendered = json.dumps(body, ensure_ascii=False, sort_keys=True)
    return f"status={status}; body={rendered[:2000]}" + (f"; error={error}" if error else "")


BROWSER_CHECK_SCRIPT = r"""
const { chromium } = require('/tmp/evaluator-tools/node_modules/playwright');

const baseUrl = process.argv[2];
const checks = [];
const diagnostics = { consoleErrors: [], pageErrors: [] };
const title = `grader-browser-${Date.now()}`;
const editedTitle = `${title}-edited`;

function record(id, passed, evidence, requirementIds) {
  checks.push({ id, passed, evidence, requirement_ids: requirementIds });
}

async function check(id, requirementIds, action) {
  try {
    const evidence = await action();
    record(id, true, evidence || 'verified', requirementIds);
  } catch (error) {
    record(id, false, error.message, requirementIds);
  }
}

async function visible(locator) {
  return (await locator.count()) > 0 && await locator.first().isVisible();
}

async function main() {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on('pageerror', error => diagnostics.pageErrors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && !/favicon/i.test(message.text())) {
        diagnostics.consoleErrors.push(message.text());
      }
    });

    await check('G1-UI-LOAD', ['G1-UI-01', 'G1-UI-05', 'G1-INT-01'], async () => {
      const response = await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 20000 });
      if (!response || !response.ok()) throw new Error(`navigation status=${response?.status()}`);
      await page.getByText('Idea Greenhouse', { exact: false }).first().waitFor();
      return `loaded ${baseUrl} through the frontend origin`;
    });

    await check('G1-UI-EMPTY', ['G1-UI-01', 'G1-UI-05'], async () => {
      const body = await page.locator('body').innerText();
      if (!/no ideas|empty|first idea|capture an idea|create an idea/i.test(body)) {
        throw new Error(`no explicit empty state; body=${body.slice(0, 1000)}`);
      }
      return 'explicit empty state is visible';
    });

    const titleField = page.getByLabel(/title/i).first();
    const notesField = page.getByLabel(/notes/i).first();
    const stageField = page.getByLabel(/stage/i).first();
    const createButton = page.getByRole('button', { name: /create|add|capture|save idea/i }).first();

    await check('G1-UI-ACCESSIBILITY', ['G1-UI-06'], async () => {
      for (const [name, locator] of [
        ['title', titleField], ['notes', notesField], ['stage', stageField], ['create', createButton]
      ]) {
        if (!await visible(locator)) throw new Error(`${name} control lacks a visible accessible name`);
      }
      for (const name of [/^all$/i, /seeds?/i, /sprouts?/i, /blooms?/i]) {
        if (!await visible(page.getByRole('button', { name }).or(page.getByRole('link', { name })))) {
          throw new Error(`missing accessible filter ${name}`);
        }
      }
      await titleField.focus();
      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => document.activeElement?.tagName || '');
      if (!focused) throw new Error('principal controls are not keyboard reachable');
      const selected = page.locator('[aria-pressed="true"], [aria-current="true"], [aria-selected="true"]');
      if (!await visible(selected)) throw new Error('selected filter state is not exposed');
      return 'labeled controls, keyboard focus, and selected filter state verified';
    });

    await check('G1-UI-BLANK-VALIDATION', ['G1-UI-02', 'G1-UI-06'], async () => {
      let createRequests = 0;
      const observe = request => {
        if (request.method() === 'POST' && /\/api\/ideas/.test(request.url())) createRequests += 1;
      };
      page.on('request', observe);
      await titleField.fill('   ');
      await createButton.click();
      await page.waitForTimeout(300);
      page.off('request', observe);
      const message = page.locator('[role="alert"]:visible, [aria-live]:visible');
      const body = await page.locator('body').innerText();
      if (!await visible(message) && !/title.{0,40}(required|blank|empty|enter)/i.test(body)) {
        throw new Error('blank title did not produce a visible validation message');
      }
      if (createRequests !== 0) throw new Error(`blank title sent ${createRequests} POST request(s)`);
      return 'blank title rejected visibly without an API request';
    });

    await check('G1-UI-CREATE', ['G1-UI-01', 'G1-UI-02'], async () => {
      await titleField.fill(title);
      await notesField.fill('browser-created notes');
      await createButton.click();
      await page.getByText(title, { exact: true }).waitFor({ timeout: 8000 });
      const body = await page.locator('body').innerText();
      if (!body.includes('browser-created notes')) throw new Error('created notes are not visible');
      if (!/total\s*[:]?\s*1|1\s*total/i.test(body)) throw new Error('total count did not update to one');
      return 'idea and updated count became visible without reload';
    });

    await check('G1-UI-STAGE-FILTER', ['G1-UI-03'], async () => {
      const card = page.getByText(title, { exact: true }).locator('xpath=ancestor::*[.//button][1]');
      const select = card.getByRole('combobox').first();
      if (await visible(select)) await select.selectOption('sprout');
      else {
        const change = card.getByRole('button', { name: /sprout|change stage|stage/i }).first();
        if (!await visible(change)) throw new Error('no accessible stage-change control');
        await change.click();
        const sprout = page.getByRole('button', { name: /sprout/i }).last();
        if (await visible(sprout)) await sprout.click();
      }
      await page.getByText(/sprout/i).first().waitFor({ timeout: 8000 });
      const filter = page.getByRole('button', { name: /sprouts?/i }).or(page.getByRole('link', { name: /sprouts?/i })).first();
      await filter.click();
      await page.getByText(title, { exact: true }).waitFor();
      return 'stage changed to sprout and remained visible through the Sprouts filter';
    });

    await check('G1-UI-EDIT', ['G1-UI-02'], async () => {
      const card = page.getByText(title, { exact: true }).locator('xpath=ancestor::*[.//button][1]');
      await card.getByRole('button', { name: /edit/i }).click();
      const editTitle = page.getByLabel(/title/i).last();
      await editTitle.fill(editedTitle);
      await page.getByRole('button', { name: /save|update/i }).last().click();
      await page.getByText(editedTitle, { exact: true }).waitFor({ timeout: 8000 });
      return 'edited title became visible without reload';
    });

    await check('G1-UI-DELETE-CONFIRM', ['G1-UI-04'], async () => {
      const card = page.getByText(editedTitle, { exact: true }).locator('xpath=ancestor::*[.//button][1]');
      let nativeConfirmation = '';
      page.once('dialog', async dialog => {
        nativeConfirmation = dialog.message();
        await dialog.accept();
      });
      await card.getByRole('button', { name: /delete|remove/i }).click();
      const dialog = page.getByRole('dialog');
      if (await visible(dialog)) {
        const text = await dialog.innerText();
        if (!text.includes(editedTitle)) throw new Error('confirmation does not identify the idea');
        await dialog.getByRole('button', { name: /confirm|delete|remove/i }).click();
      } else if (!nativeConfirmation.includes(editedTitle)) {
        throw new Error('deletion did not require confirmation identifying the idea');
      }
      await page.getByText(editedTitle, { exact: true }).waitFor({ state: 'hidden', timeout: 8000 });
      return 'identified confirmation was required and the idea was deleted';
    });

    await check('G1-UI-RUNTIME-ERRORS', ['G1-UI-05'], async () => {
      if (diagnostics.pageErrors.length) throw new Error(`page errors: ${diagnostics.pageErrors.join(' | ')}`);
      if (diagnostics.consoleErrors.length) throw new Error(`console errors: ${diagnostics.consoleErrors.join(' | ')}`);
      return 'no page or severe console errors';
    });

    console.log('DEVLAB_BROWSER_RESULT:' + JSON.stringify({ checks, diagnostics }));
  } catch (error) {
    console.error('DEVLAB_GRADER_ERROR:' + JSON.stringify({ error: error.message, diagnostics }));
    process.exitCode = 2;
  } finally {
    if (browser) await browser.close();
  }
}

main();
"""


def render_report(result: GradeResult) -> str:
    data = result.as_dict()
    lines = [
        f"system-evolution generation {result.generation}: "
        f"{'valid' if data['valid_run'] else 'invalid/incomplete'}",
        f"target revision: {result.target_revision or 'unknown'}",
    ]
    for name, counts in data["dimensions"].items():
        if sum(counts.values()):
            lines.append(
                f"{name}: " + ", ".join(f"{key}={value}" for key, value in counts.items())
            )
    if result.invalid_reasons:
        lines.append("hard gates: " + ", ".join(result.invalid_reasons))
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation", type=int, choices=(1, 2), required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--generation-1-fixture", type=Path)
    parser.add_argument("--generation-1-fixture-out", type=Path)
    parser.add_argument("--generation-1-resume", type=Path)
    parser.add_argument("--generation-1-resume-out", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    fixture_out = args.generation_1_fixture_out
    if args.generation == 1 and fixture_out is None:
        fixture_out = args.json_out.with_name(f"{args.json_out.stem}-fixture.json")
    resume_out = args.generation_1_resume_out
    if args.generation == 1 and resume_out is None:
        resume_out = args.json_out.with_name(f"{args.json_out.stem}-resume.json")
    try:
        grader = SystemEvolutionGrader(
            args.target,
            args.generation,
            args.compose_project,
            generation_1_fixture=args.generation_1_fixture,
            generation_1_fixture_out=fixture_out,
            generation_1_resume=args.generation_1_resume,
            generation_1_resume_out=resume_out,
        )
        result = grader.grade()
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n")
    print(render_report(result))
    return (
        0
        if result.as_dict()["valid_run"]
        and not any(check.status == "failed" for check in result.checks)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
