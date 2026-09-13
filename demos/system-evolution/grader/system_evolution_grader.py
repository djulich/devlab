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
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, BrokenBarrierError
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
            if self.generation == 2:
                self._target_validation_checks()
                if not self._preserved_volume_check():
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
            if self.generation == 2:
                self._image_runtime_inspection()
            if self.generation == 1:
                self._api_checks()
                self._browser_checks()
                self._persistence_checks()
                self._create_generation_1_fixture()
            else:
                self._generation_2_migration_checks()
                self._generation_2_archive_checks()
                self._generation_2_concurrency_checks()
                self._generation_2_browser_conflict_checks()
                self._generation_2_clean_install_check()
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

    def _target_validation_checks(self) -> None:
        """Run target-owned commands under a disposable Compose namespace."""
        make_path = shutil.which("make")
        if make_path is None:
            self.result.add(
                Check(
                    "PREREQ-TARGET-MAKE",
                    "target_validation",
                    "unverified",
                    0,
                    "make executable is unavailable; target commands were not run",
                )
            )
            return
        project = validate_project_name(f"{self.project[:38]}-validation-{secrets.token_hex(4)}")
        environment = self._disposable_environment(project)
        preflight = self._compose_for(
            project, environment, "config", "--format", "json", timeout=30
        )
        try:
            config = json.loads(preflight.stdout) if preflight.returncode == 0 else {}
            db_mounts = config.get("services", {}).get("db", {}).get("volumes", [])
            source = next(
                (
                    str(mount.get("source", ""))
                    for mount in db_mounts
                    if isinstance(mount, dict) and mount.get("type") == "volume"
                ),
                "",
            )
            validation_volume = str(config.get("volumes", {}).get(source, {}).get("name", source))
        except (AttributeError, json.JSONDecodeError):
            validation_volume = ""
        if (
            preflight.returncode != 0
            or not validation_volume
            or validation_volume == self.expected_database_volume
        ):
            self.result.add(
                Check(
                    "G2-TARGET-VALIDATION-NAMESPACE",
                    "target_validation",
                    "grader_error",
                    preflight.duration_seconds,
                    f"project={project}; volume={validation_volume!r}; "
                    f"preserved={self.expected_database_volume!r}; {command_evidence(preflight)}",
                )
            )
            return
        commands = (
            ("G2-TARGET-BACKEND", "test-backend", ("G2-TEST-01",)),
            ("G2-TARGET-FRONTEND", "test-frontend", ("G2-TEST-02",)),
            ("G2-TARGET-COMPOSE-CONFIG", "compose-config", ("G2-DEP-08",)),
            ("G2-TARGET-COMPOSE-BUILD", "compose-build", ("G2-DEP-08",)),
            ("G2-TARGET-DEPLOYMENT", "deployment-check", ("G2-DEP-08", "G2-TEST-03")),
            ("G2-TARGET-CHECK", "check", ("G2-CMD-01", "G2-TEST-01")),
        )
        database_name = f"{project}-test-db"
        database_port = available_port()
        database_created = False
        try:
            setup = self.runner(
                (
                    str(self.docker),
                    "create",
                    "--name",
                    database_name,
                    "--tmpfs",
                    "/var/lib/postgresql/data",
                    "--publish",
                    f"127.0.0.1:{database_port}:5432",
                    "--env",
                    "POSTGRES_USER",
                    "--env",
                    "POSTGRES_PASSWORD",
                    "--env",
                    "POSTGRES_DB",
                    "postgres:17.6-bookworm",
                ),
                self.target,
                environment,
                180,
            )
            database_created = setup.returncode == 0
            if not database_created:
                self.result.add(
                    Check(
                        "PREREQ-TARGET-DATABASE",
                        "target_validation",
                        "unverified",
                        setup.duration_seconds,
                        "Could not start evaluator-owned disposable PostgreSQL; target validation not run.",
                    )
                )
                return
            started = self.runner(
                (str(self.docker), "start", database_name), self.target, environment, 30
            )
            if started.returncode != 0:
                self.result.add(
                    Check(
                        "PREREQ-TARGET-DATABASE",
                        "target_validation",
                        "unverified",
                        started.duration_seconds,
                        "Could not start evaluator-owned PostgreSQL; target validation not run.",
                    )
                )
                return
            deadline = time.monotonic() + 60
            while True:
                ready = self.runner(
                    (
                        str(self.docker),
                        "exec",
                        database_name,
                        "pg_isready",
                        "-h",
                        "127.0.0.1",
                        "-U",
                        environment["POSTGRES_USER"],
                        "-d",
                        environment["POSTGRES_DB"],
                    ),
                    self.target,
                    environment,
                    10,
                )
                if ready.returncode == 0:
                    break
                if time.monotonic() >= deadline:
                    self.result.add(
                        Check(
                            "PREREQ-TARGET-DATABASE",
                            "target_validation",
                            "unverified",
                            60,
                            "Evaluator-owned PostgreSQL did not become ready; target validation not run.",
                        )
                    )
                    return
                time.sleep(1)
            environment["TEST_DATABASE_URL"] = (
                f"postgresql+psycopg://{environment['POSTGRES_USER']}:{environment['POSTGRES_PASSWORD']}"
                f"@127.0.0.1:{database_port}/{environment['POSTGRES_DB']}"
            )
            for check_id, target, requirements in commands:
                try:
                    command = self.runner(
                        (str(Path(make_path).resolve()), target),
                        self.target,
                        environment,
                        1800,
                    )
                except (OSError, subprocess.SubprocessError) as error:
                    self.result.add(
                        Check(
                            check_id,
                            "target_validation",
                            "grader_error",
                            0,
                            f"target command could not run: {type(error).__name__}: {error}",
                            requirements,
                        )
                    )
                    continue
                rendered_command = " ".join(command.args)
                self.result.add(
                    Check(
                        check_id,
                        "target_validation",
                        "passed" if command.returncode == 0 else "failed",
                        command.duration_seconds,
                        f"command={rendered_command}; {command_evidence(command)}"[:4000],
                        requirements,
                    )
                )
        except (OSError, subprocess.SubprocessError):
            self.result.add(
                Check(
                    "PREREQ-TARGET-DATABASE",
                    "target_validation",
                    "grader_error",
                    0,
                    "Evaluator database provisioning command failed.",
                )
            )
        finally:
            if database_created:
                try:
                    removed = self.runner(
                        (str(self.docker), "rm", "--force", database_name),
                        self.target,
                        environment,
                        30,
                    )
                    if removed.returncode != 0:
                        self.result.add(
                            Check(
                                "G2-TARGET-DATABASE-CLEANUP",
                                "target_validation",
                                "grader_error",
                                removed.duration_seconds,
                                "Could not remove evaluator-owned test database.",
                            )
                        )
                except (OSError, subprocess.SubprocessError):
                    self.result.add(
                        Check(
                            "G2-TARGET-DATABASE-CLEANUP",
                            "target_validation",
                            "grader_error",
                            0,
                            "Could not remove evaluator-owned test database.",
                        )
                    )
            try:
                cleanup = self._compose_for(
                    project,
                    environment,
                    "down",
                    "--remove-orphans",
                    "--volumes",
                    timeout=180,
                )
                cleanup_error = command_evidence(cleanup) if cleanup.returncode != 0 else ""
                cleanup_duration = cleanup.duration_seconds
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_error = f"{type(error).__name__}: {error}"
                cleanup_duration = 0
            if cleanup_error:
                self.result.add(
                    Check(
                        "G2-TARGET-VALIDATION-CLEANUP",
                        "target_validation",
                        "grader_error",
                        cleanup_duration,
                        f"project={project}; {cleanup_error}",
                    )
                )

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
        if not passed:
            return False

        if self.docker is None:
            return False
        daemon = self.runner((str(self.docker), "info"), self.target, self.environment, 15)
        daemon_available = daemon.returncode == 0
        self.result.add(
            Check(
                "PREREQ-DOCKER-DAEMON",
                "deployment",
                "passed" if daemon_available else "unverified",
                daemon.duration_seconds,
                command_evidence(daemon),
                hard_gate=True,
            )
        )
        return daemon_available

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

    def _image_runtime_inspection(self) -> None:
        """Inspect running containers and image metadata without exporting layers."""
        if self.docker is None:
            return
        started = time.monotonic()
        inspections: dict[str, dict[str, Any]] = {}
        grader_errors: list[str] = []
        for service in ("db", "api", "frontend"):
            container = self._compose("ps", "-q", service, timeout=30)
            container_id = container.stdout.strip()
            if container.returncode != 0 or not container_id:
                grader_errors.append(
                    f"{service}: container lookup failed: {command_evidence(container)}"
                )
                continue
            inspected = self.runner(
                (str(self.docker), "inspect", container_id),
                self.target,
                self.environment,
                30,
            )
            try:
                rows = json.loads(inspected.stdout) if inspected.returncode == 0 else []
                if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                    raise ValueError("expected one container inspection row")
                inspections[service] = rows[0]
            except (ValueError, json.JSONDecodeError) as error:
                grader_errors.append(
                    f"{service}: invalid container inspection: {error}; {command_evidence(inspected)}"
                )
        runtime_ok = False
        if not grader_errors and set(inspections) == {"db", "api", "frontend"}:
            project_labels = {
                str(row.get("Config", {}).get("Labels", {}).get("com.docker.compose.project", ""))
                for row in inspections.values()
            }
            users = {
                service: str(row.get("Config", {}).get("User", ""))
                for service, row in inspections.items()
            }
            ports = {
                service: bool(row.get("HostConfig", {}).get("PortBindings"))
                for service, row in inspections.items()
            }
            db_mounts = inspections["db"].get("Mounts", [])
            volume_names = {
                str(mount.get("Name", ""))
                for mount in db_mounts
                if isinstance(mount, dict) and mount.get("Type") == "volume"
            }
            runtime_ok = (
                project_labels == {self.project}
                and users["api"] not in ("", "0", "root")
                and users["frontend"] not in ("", "0", "root")
                and ports == {"db": False, "api": False, "frontend": True}
                and self.database_volume in volume_names
            )
            evidence = (
                f"project_labels={sorted(project_labels)}; users={users}; ports={ports}; "
                f"db_volumes={sorted(volume_names)}"
            )
        else:
            evidence = "; ".join(grader_errors)
        self.result.add(
            Check(
                "G2-DEP-RUNTIME-INSPECTION",
                "deployment",
                "grader_error" if grader_errors else ("passed" if runtime_ok else "failed"),
                time.monotonic() - started,
                evidence[:4000],
                ("G2-DEP-02", "G2-DEP-03", "G2-DEP-04", "G2-DEP-05"),
            )
        )

        image_errors: list[str] = []
        image_grader_errors: list[str] = []
        image_evidence: list[str] = []
        for service in ("api", "frontend"):
            row = inspections.get(service, {})
            image_id = str(row.get("Image", ""))
            if not image_id:
                image_grader_errors.append(f"{service}: running image ID unavailable")
                continue
            inspect = self.runner(
                (str(self.docker), "image", "inspect", image_id),
                self.target,
                self.environment,
                30,
            )
            history = self.runner(
                (str(self.docker), "history", "--no-trunc", image_id),
                self.target,
                self.environment,
                30,
            )
            combined = f"{inspect.stdout}\n{inspect.stderr}\n{history.stdout}\n{history.stderr}"
            leaked = [
                marker
                for marker in (
                    self.environment["POSTGRES_PASSWORD"],
                    ".devlab",
                    "agents.toml",
                )
                if marker and marker in combined
            ]
            try:
                image_rows = json.loads(inspect.stdout) if inspect.returncode == 0 else []
                config = image_rows[0].get("Config", {})
                user = str(config.get("User", ""))
                image_environment = config.get("Env", []) or []
            except (IndexError, AttributeError, json.JSONDecodeError):
                user = ""
                image_environment = []
                image_grader_errors.append(f"{service}: invalid image inspection")
            if inspect.returncode != 0 or history.returncode != 0:
                image_grader_errors.append(f"{service}: image inspect/history command failed")
            if user in ("", "0", "root"):
                leaked.append("root runtime user")
            if service == "frontend" and any(
                str(value).startswith(("DATABASE_URL=", "POSTGRES_PASSWORD="))
                for value in image_environment
            ):
                leaked.append("database configuration in frontend image")
            if leaked:
                image_errors.append(f"{service}: {', '.join(leaked)}")
            image_evidence.append(
                f"{service}: user={user!r}; history_lines={len(history.stdout.splitlines())}"
            )
        self.result.add(
            Check(
                "G2-DEP-IMAGE-INSPECTION",
                "hygiene",
                "grader_error"
                if image_grader_errors
                else ("failed" if image_errors else "passed"),
                time.monotonic() - started,
                (
                    "; ".join((*image_grader_errors, *image_errors))
                    if image_grader_errors or image_errors
                    else "; ".join(image_evidence)
                )[:4000],
                ("G2-DEP-04", "G2-DEP-05", "G2-DEP-06"),
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
                field
                for field in preserved_fields
                if not preserved_value_equal(field, current.get(field), expected.get(field))
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
                    preserved_value_equal(field, response[1].get(field), expected.get(field))
                    for field in preserved_fields
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

    def _generation_2_archive_checks(self) -> None:
        """Exercise Generation 2 fields and archive behavior without touching fixture rows."""
        base = f"http://127.0.0.1:{self.host_port}/api/ideas"
        fixture = self.generation_1_fixture_data or {}
        fixture_ideas = fixture.get("ideas", [])
        temporary_ids: list[int] = []
        responses: list[tuple[int, dict[str, Any], float, str]] = []

        def request(
            method: str,
            url: str,
            payload: dict[str, Any] | None = None,
            *,
            version: int | None = None,
        ) -> tuple[int, dict[str, Any], float, str]:
            response = self._request(
                method,
                url,
                payload,
                headers={"If-Match": f'"{version}"'} if version is not None else None,
            )
            responses.append(response)
            return response

        def add_check(
            check_id: str, passed: bool, evidence: str, requirements: tuple[str, ...]
        ) -> None:
            self.result.add(
                Check(
                    check_id,
                    "api",
                    "passed" if passed else "failed",
                    sum(item[2] for item in responses),
                    evidence[:4000],
                    requirements,
                )
            )
            responses.clear()

        try:
            created: list[dict[str, Any]] = []
            for stage in ("seed", "sprout", "bloom"):
                response = request(
                    "POST",
                    base,
                    {
                        "title": f"{self.prefix} {stage}",
                        "stage": stage,
                        "next_action": "  Review evidence  " if stage == "seed" else None,
                    },
                )
                idea_id = response[1].get("id")
                if isinstance(idea_id, int) and not isinstance(idea_id, bool):
                    temporary_ids.append(idea_id)
                if (
                    response[0] == 201
                    and isinstance(idea_id, int)
                    and not isinstance(idea_id, bool)
                ):
                    created.append(response[1])
            create_ok = (
                len(created) == 3
                and created[0].get("next_action") == "Review evidence"
                and all(
                    idea.get("version") == 1 and idea.get("archived_at") is None
                    for idea in created
                )
            )
            add_check(
                "G2-API-NEXT-ACTION-CREATE",
                create_ok,
                f"created={len(created)}; trimmed={created[0].get('next_action') if created else None!r}",
                ("G2-API-02",),
            )
            if len(created) != 3:
                return

            seed, sprout, bloom = created
            edited = request(
                "PATCH",
                f"{base}/{seed['id']}",
                {"next_action": "  Ship the report  "},
                version=seed["version"],
            )
            cleared = request(
                "PATCH",
                f"{base}/{seed['id']}",
                {"next_action": "   "},
                version=edited[1].get("version") if edited[0] == 200 else None,
            )
            edit_ok = (
                edited[0] == 200
                and edited[1].get("next_action") == "Ship the report"
                and edited[1].get("version") == 2
                and cleared[0] == 200
                and cleared[1].get("next_action") is None
                and cleared[1].get("version") == 3
            )
            seed = cleared[1] if cleared[0] == 200 else edited[1]
            add_check(
                "G2-API-NEXT-ACTION-EDIT-CLEAR",
                edit_ok,
                f"edit={summarize_http(edited)}; clear={summarize_http(cleared)}",
                ("G2-API-06",),
            )

            overlong_create = request(
                "POST", base, {"title": f"{self.prefix} invalid", "next_action": "x" * 241}
            )
            invalid_id = overlong_create[1].get("id")
            if isinstance(invalid_id, int) and not isinstance(invalid_id, bool):
                temporary_ids.append(invalid_id)
            overlong_patch = request(
                "PATCH",
                f"{base}/{seed['id']}",
                {"next_action": "x" * 241},
                version=seed.get("version"),
            )
            length_ok = all(
                response[0] == 422
                and response[1].get("error", {}).get("code") == "validation_error"
                for response in (overlong_create, overlong_patch)
            )
            add_check(
                "G2-API-NEXT-ACTION-LIMIT",
                length_ok,
                f"create={summarize_http(overlong_create)}; patch={summarize_http(overlong_patch)}",
                ("G2-API-02", "G2-API-06", "G2-API-10"),
            )

            archived = request(
                "POST", f"{base}/{bloom['id']}/archive", {}, version=bloom["version"]
            )
            archive_ok = (
                archived[0] == 200
                and archived[1].get("archived_at") is not None
                and archived[1].get("version") == 2
                and archived[1].get("updated_at") != bloom.get("updated_at")
            )
            add_check(
                "G2-API-ARCHIVE",
                archive_ok,
                summarize_http(archived),
                ("G2-API-07",),
            )
            bloom = archived[1] if archived[0] == 200 else bloom

            invalid_archive = request(
                "POST", f"{base}/{bloom['id']}/archive", {}, version=bloom.get("version")
            )
            invalid_restore = request(
                "POST", f"{base}/{sprout['id']}/restore", {}, version=sprout["version"]
            )
            invalid_ok = all(
                response[0] == 409
                and response[1].get("error", {}).get("code") == "invalid_archive_state"
                and response[1].get("current", {}).get("id") == idea_id
                for response, idea_id in (
                    (invalid_archive, bloom["id"]),
                    (invalid_restore, sprout["id"]),
                )
            )
            add_check(
                "G2-API-INVALID-ARCHIVE-STATE",
                invalid_ok,
                f"archive={summarize_http(invalid_archive)}; restore={summarize_http(invalid_restore)}",
                ("G2-API-07", "G2-API-10"),
            )

            expected_all = {idea["id"] for idea in fixture_ideas} | set(temporary_ids)
            expected_active = expected_all - {bloom["id"]}
            expected_counts = {"seed": 1, "sprout": 1, "bloom": 0}
            for idea in fixture_ideas:
                expected_counts[idea["stage"]] += 1
            expected_counts.update(
                active=len(expected_active), archived=1, total=len(expected_all)
            )
            listings = {
                "default": request("GET", base),
                "active": request("GET", f"{base}?archive=active"),
                "archived": request("GET", f"{base}?archive=archived"),
                "all": request("GET", f"{base}?archive=all"),
                "stage": request("GET", f"{base}?archive=all&stage=bloom"),
            }
            ids = {
                name: {item.get("id") for item in response[1].get("ideas", [])}
                for name, response in listings.items()
            }
            filters_ok = (
                all(response[0] == 200 for response in listings.values())
                and ids["default"] == expected_active
                and ids["active"] == expected_active
                and ids["archived"] == {bloom["id"]}
                and ids["all"] == expected_all
                and ids["stage"]
                == {idea["id"] for idea in fixture_ideas if idea["stage"] == "bloom"}
                | {bloom["id"]}
                and all(
                    response[1].get("counts") == expected_counts for response in listings.values()
                )
            )
            add_check(
                "G2-API-ARCHIVE-FILTERS-COUNTS",
                filters_ok,
                f"ids={ids}; expected_counts={expected_counts}; actual_counts="
                f"{listings['all'][1].get('counts')}",
                ("G2-API-03",),
            )

            restored = request(
                "POST", f"{base}/{bloom['id']}/restore", {}, version=bloom.get("version")
            )
            restore_ok = (
                restored[0] == 200
                and restored[1].get("archived_at") is None
                and restored[1].get("version") == 3
                and restored[1].get("updated_at") != bloom.get("updated_at")
            )
            bloom = restored[1] if restored[0] == 200 else bloom
            add_check(
                "G2-API-RESTORE",
                restore_ok,
                summarize_http(restored),
                ("G2-API-07",),
            )

            rearchived = request(
                "POST", f"{base}/{bloom['id']}/archive", {}, version=bloom.get("version")
            )
            bloom = rearchived[1] if rearchived[0] == 200 else bloom
            delete_active = request("DELETE", f"{base}/{sprout['id']}", version=sprout["version"])
            delete_archived = request(
                "DELETE", f"{base}/{bloom['id']}", version=bloom.get("version")
            )
            delete_ok = (
                rearchived[0] == 200
                and rearchived[1].get("version") == 4
                and delete_active[0] == 204
                and delete_active[1] == {}
                and delete_archived[0] == 204
                and delete_archived[1] == {}
            )
            if delete_active[0] == 204:
                temporary_ids.remove(sprout["id"])
            if delete_archived[0] == 204:
                temporary_ids.remove(bloom["id"])
            add_check(
                "G2-API-PERMANENT-DELETE",
                delete_ok,
                f"rearchive={summarize_http(rearchived)}; active={summarize_http(delete_active)}; "
                f"archived={summarize_http(delete_archived)}",
                ("G2-API-08",),
            )
        finally:
            failures: list[str] = []
            for idea_id in dict.fromkeys(temporary_ids):
                current = self._request("GET", f"{base}/{idea_id}")
                version = current[1].get("version")
                deleted = (
                    self._request(
                        "DELETE",
                        f"{base}/{idea_id}",
                        headers={"If-Match": f'"{version}"'},
                    )
                    if current[0] == 200 and isinstance(version, int)
                    else current
                )
                if deleted[0] not in (204, 404):
                    failures.append(f"id={idea_id}: {summarize_http(deleted)}")
            if failures:
                self.result.add(
                    Check(
                        "G2-API-TEMPORARY-CLEANUP",
                        "api",
                        "grader_error",
                        0,
                        "could not remove evaluator records; " + "; ".join(failures)[:3800],
                    )
                )

    def _generation_2_concurrency_checks(self) -> None:
        """Verify expected versions, stale safety, and atomic writer exclusion."""
        base = f"http://127.0.0.1:{self.host_port}/api/ideas"
        temporary_ids: list[int] = []

        def create(label: str) -> tuple[int, dict[str, Any], float, str]:
            response = self._request("POST", base, {"title": f"{self.prefix} {label}"})
            idea_id = response[1].get("id")
            if isinstance(idea_id, int) and not isinstance(idea_id, bool):
                temporary_ids.append(idea_id)
            return response

        def mutate(
            method: str,
            url: str,
            version: int,
            payload: dict[str, Any] | None = None,
        ) -> tuple[int, dict[str, Any], float, str]:
            return self._request(method, url, payload, headers={"If-Match": f'"{version}"'})

        try:
            probe = create("precondition probe")
            probe_id = probe[1].get("id")
            if probe[0] != 201 or not isinstance(probe_id, int):
                self.result.add(
                    Check(
                        "G2-CONCURRENCY-SETUP",
                        "concurrency",
                        "failed",
                        probe[2],
                        summarize_http(probe),
                        ("G2-API-02",),
                    )
                )
                return

            syntax_cases: tuple[tuple[str, str | None, int], ...] = (
                ("missing", None, 428),
                ("unquoted", "1", 400),
                ("weak", 'W/"1"', 400),
                ("zero", '"0"', 400),
                ("negative", '"-1"', 400),
                ("empty", '""', 400),
                ("multiple", '"1", "2"', 400),
            )
            syntax_results = []
            for name, value, expected in syntax_cases:
                response = self._request(
                    "PATCH",
                    f"{base}/{probe_id}",
                    {"notes": name},
                    headers={"If-Match": value} if value is not None else None,
                )
                syntax_results.append((name, expected, response))
            syntax_ok = all(
                response[0] == expected
                and stable_error(
                    response[1],
                    "precondition_required" if name == "missing" else "invalid_if_match",
                )
                for name, expected, response in syntax_results
            )
            self.result.add(
                Check(
                    "G2-CONCURRENCY-IF-MATCH-SYNTAX",
                    "concurrency",
                    "passed" if syntax_ok else "failed",
                    sum(response[2] for _, _, response in syntax_results),
                    "; ".join(
                        f"{name}={summarize_http(response)}"
                        for name, _, response in syntax_results
                    )[:4000],
                    ("G2-API-05", "G2-API-10"),
                )
            )
            missing = self._request(
                "PATCH",
                f"{base}/2147483647",
                {"notes": "missing"},
                headers={"If-Match": '"1"'},
            )
            self.result.add(
                Check(
                    "G2-CONCURRENCY-MISSING-PRECEDENCE",
                    "concurrency",
                    "passed"
                    if missing[0] == 404 and stable_error(missing[1], "idea_not_found")
                    else "failed",
                    missing[2],
                    summarize_http(missing),
                    ("G2-API-05", "G2-API-10"),
                )
            )

            initial = probe[1]
            updated = mutate(
                "PATCH", f"{base}/{probe_id}", initial["version"], {"notes": "current"}
            )
            update_ok = (
                updated[0] == 200
                and updated[1].get("version") == initial["version"] + 1
                and updated[1].get("notes") == "current"
            )
            self.result.add(
                Check(
                    "G2-CONCURRENCY-VERSION-INCREMENT",
                    "concurrency",
                    "passed" if update_ok else "failed",
                    updated[2],
                    summarize_http(updated),
                    ("G2-API-06", "G2-API-09"),
                )
            )
            current = updated[1] if updated[0] == 200 else initial
            stale: list[tuple[str, tuple[int, dict[str, Any], float, str], dict[str, Any]]] = []
            stale.append(
                (
                    "update",
                    mutate("PATCH", f"{base}/{probe_id}", 1, {"notes": "stale"}),
                    dict(current),
                )
            )
            archived = mutate("POST", f"{base}/{probe_id}/archive", current["version"], {})
            current = archived[1] if archived[0] == 200 else current
            stale.append(
                (
                    "archive",
                    mutate("POST", f"{base}/{probe_id}/archive", 2, {}),
                    dict(current),
                )
            )
            restored = mutate("POST", f"{base}/{probe_id}/restore", current["version"], {})
            current = restored[1] if restored[0] == 200 else current
            stale.append(
                (
                    "restore",
                    mutate("POST", f"{base}/{probe_id}/restore", 3, {}),
                    dict(current),
                )
            )
            stale.append(("delete", mutate("DELETE", f"{base}/{probe_id}", 3), dict(current)))
            final = self._request("GET", f"{base}/{probe_id}")
            stale_ok = (
                archived[0] == 200
                and archived[1].get("version") == 3
                and restored[0] == 200
                and restored[1].get("version") == 4
                and all(
                    response[0] == 409 and stable_conflict(response[1], expected)
                    for _, response, expected in stale
                )
                and final[0] == 200
                and final[1] == current
            )
            self.result.add(
                Check(
                    "G2-CONCURRENCY-SEQUENTIAL-STALE",
                    "concurrency",
                    "passed" if stale_ok else "failed",
                    archived[2]
                    + restored[2]
                    + final[2]
                    + sum(response[2] for _, response, _ in stale),
                    "; ".join(f"{name}={summarize_http(response)}" for name, response, _ in stale)[
                        :4000
                    ],
                    ("G2-API-05", "G2-API-07", "G2-API-08", "G2-API-09"),
                )
            )

            race_failures: list[str] = []
            race_grader_errors: list[str] = []
            race_duration = 0.0
            for repetition in range(1, 9):
                race = create(f"race {repetition}")
                race_id = race[1].get("id")
                version = race[1].get("version")
                if race[0] != 201 or not isinstance(race_id, int) or version != 1:
                    race_failures.append(f"race {repetition} setup: {summarize_http(race)}")
                    continue
                barrier = Barrier(2)

                def writer(
                    label: str,
                    barrier_: Barrier = barrier,
                    race_id_: int = race_id,
                    version_: int = version,
                ) -> tuple[int, dict[str, Any], float, str]:
                    barrier_.wait(timeout=10)
                    return mutate(
                        "PATCH",
                        f"{base}/{race_id_}",
                        version_,
                        {"notes": f"writer {label}"},
                    )

                try:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        outcomes = list(executor.map(writer, ("a", "b"), timeout=20))
                except (BrokenBarrierError, TimeoutError) as error:
                    race_grader_errors.append(
                        f"race {repetition}: synchronization failed: {type(error).__name__}: {error}"
                    )
                    continue
                final_race = self._request("GET", f"{base}/{race_id}")
                race_duration += sum(item[2] for item in outcomes) + final_race[2]
                successes = [item for item in outcomes if item[0] == 200]
                conflicts = [item for item in outcomes if item[0] == 409]
                if not (
                    len(successes) == 1
                    and len(conflicts) == 1
                    and final_race[0] == 200
                    and successes[0][1] == final_race[1]
                    and final_race[1].get("version") == 2
                    and stable_conflict(conflicts[0][1], final_race[1])
                ):
                    race_failures.append(
                        f"race {repetition}: statuses={[item[0] for item in outcomes]}; "
                        f"final={summarize_http(final_race)}"
                    )
            self.result.add(
                Check(
                    "G2-CONCURRENCY-SYNCHRONIZED-RACES",
                    "concurrency",
                    "grader_error"
                    if race_grader_errors
                    else ("failed" if race_failures else "passed"),
                    race_duration,
                    "; ".join((*race_grader_errors, *race_failures))[:4000]
                    if race_grader_errors or race_failures
                    else "8/8 races produced one success and one version conflict",
                    ("G2-API-09",),
                )
            )
        finally:
            failures: list[str] = []
            for idea_id in dict.fromkeys(temporary_ids):
                current = self._request("GET", f"{base}/{idea_id}")
                version = current[1].get("version")
                deleted = (
                    mutate("DELETE", f"{base}/{idea_id}", version)
                    if current[0] == 200 and isinstance(version, int)
                    else current
                )
                if deleted[0] not in (204, 404):
                    failures.append(f"id={idea_id}: {summarize_http(deleted)}")
            if failures:
                self.result.add(
                    Check(
                        "G2-CONCURRENCY-TEMPORARY-CLEANUP",
                        "concurrency",
                        "grader_error",
                        0,
                        "could not remove concurrency probes; " + "; ".join(failures)[:3800],
                    )
                )

    def _browser_checks(self) -> None:
        self._run_browser_checks(BROWSER_CHECK_SCRIPT, "G1-UI-GRADER")

    def _generation_2_browser_conflict_checks(self) -> None:
        self._run_browser_checks(GENERATION_2_BROWSER_CHECK_SCRIPT, "G2-UI-GRADER")

    def _generation_2_clean_install_check(self) -> None:
        """Apply the full migration chain to a separately namespaced empty database."""
        project = validate_project_name(f"{self.project[:40]}-clean-{secrets.token_hex(4)}")
        environment = self._disposable_environment(project)
        port = environment["APP_PORT"]
        started = time.monotonic()
        evidence: list[str] = []
        passed = False
        execution_error = ""
        cleanup_error = ""
        try:
            config_result = self._compose_for(
                project, environment, "config", "--format", "json", timeout=30
            )
            if config_result.returncode != 0:
                evidence.append(f"config: {command_evidence(config_result)}")
                return
            config = json.loads(config_result.stdout)
            db = config.get("services", {}).get("db", {})
            volume_source = next(
                (
                    str(mount.get("source", ""))
                    for mount in db.get("volumes", [])
                    if isinstance(mount, dict) and mount.get("type") == "volume"
                ),
                "",
            )
            volume_config = config.get("volumes", {}).get(volume_source, {})
            clean_volume = str(volume_config.get("name", volume_source))
            if not clean_volume or clean_volume == self.expected_database_volume:
                evidence.append(
                    f"unsafe clean-install volume={clean_volume!r}; "
                    f"preserved={self.expected_database_volume!r}"
                )
                return
            up = self._compose_for(
                project,
                environment,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                timeout=180,
            )
            evidence.append(f"up_exit={up.returncode}; volume={clean_volume}")
            if up.returncode != 0:
                evidence.append(command_evidence(up))
                return
            base = f"http://127.0.0.1:{port}/api"
            self._wait_for_health(base)
            health = self._request("GET", f"{base}/health")
            ideas = self._request("GET", f"{base}/ideas")
            alembic = self._compose_for(
                project,
                environment,
                "exec",
                "-T",
                "api",
                "alembic",
                "current",
                timeout=30,
            )
            expected_counts = {
                "seed": 0,
                "sprout": 0,
                "bloom": 0,
                "active": 0,
                "archived": 0,
                "total": 0,
            }
            passed = (
                health[0] == 200
                and health[1] == {"status": "ok", "database": "ok"}
                and ideas[0] == 200
                and ideas[1] == {"ideas": [], "counts": expected_counts}
                and alembic.returncode == 0
                and "(head)" in alembic.stdout
            )
            evidence.append(
                f"health={summarize_http(health)}; ideas={summarize_http(ideas)}; "
                f"alembic={command_evidence(alembic)}"
            )
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
            execution_error = f"{type(error).__name__}: {error}"
        finally:
            try:
                cleanup = self._compose_for(
                    project,
                    environment,
                    "down",
                    "--remove-orphans",
                    "--volumes",
                    timeout=180,
                )
                if cleanup.returncode != 0:
                    cleanup_error = command_evidence(cleanup)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_error = f"{type(error).__name__}: {error}"
            diagnostics = "; ".join(evidence)
            if execution_error:
                diagnostics += f"; execution={execution_error}"
            if cleanup_error:
                diagnostics += f"; cleanup={cleanup_error}"
            self.result.add(
                Check(
                    "G2-MIGRATION-CLEAN-INSTALL",
                    "migration",
                    "grader_error"
                    if execution_error or cleanup_error
                    else ("passed" if passed else "failed"),
                    time.monotonic() - started,
                    diagnostics[:4000],
                    ("G2-DATA-02", "G2-DEP-04", "G2-DEP-14"),
                    hard_gate=True,
                )
            )

    def _run_browser_checks(self, script_content: str, grader_check_id: str) -> None:
        if self.docker is None:
            return
        with tempfile.TemporaryDirectory(prefix="devlab-system-evolution-browser-") as directory:
            Path(directory).chmod(0o755)
            script = Path(directory) / "browser-check.js"
            script.write_text(script_content)
            script.chmod(0o644)
            command = (
                str(self.docker),
                "run",
                "--rm",
                "--pull=missing",
                "--network=host",
                "--volume",
                f"{script}:/grader/browser-check.js:ro,Z",
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
                        grader_check_id,
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
                Check(grader_check_id, "browser", status, completed.duration_seconds, evidence)
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
                    grader_check_id,
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
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], float, str]:
        started = time.monotonic()
        data = json.dumps(payload).encode() if payload is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
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

    def _compose_for(
        self,
        project: str,
        environment: Mapping[str, str],
        *args: str,
        timeout: int,
    ) -> CommandResult:
        if self.docker is None:
            raise RuntimeError("Docker is unavailable")
        validated = validate_project_name(project)
        command = (str(self.docker), "compose", "--project-name", validated, *args)
        return self.runner(command, self.target, environment, timeout)

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

    def _disposable_environment(self, project: str) -> dict[str, str]:
        suffix = secrets.token_hex(6)
        environment = dict(self.environment)
        environment.update(
            {
                "COMPOSE_PROJECT_NAME": validate_project_name(project),
                "APP_PORT": str(available_port()),
                "POSTGRES_DB": f"grader_{suffix}",
                "POSTGRES_USER": f"grader_{suffix}",
                "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
            }
        )
        return environment


def validate_project_name(value: str) -> str:
    if not PROJECT_PATTERN.fullmatch(value):
        raise ValueError(
            "compose project must be 8-63 lowercase letters, digits, underscores, or hyphens"
        )
    return value


def preserved_value_equal(field: str, current: object, expected: object) -> bool:
    """Compare timestamp instants; Generation 1 naive timestamps denote UTC."""
    if field not in {"created_at", "updated_at"}:
        return current == expected
    if not isinstance(current, str) or not isinstance(expected, str):
        return False
    try:
        values = [
            datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (current, expected)
        ]
    except ValueError:
        return False
    normalized = [
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        for value in values
    ]
    return normalized[0] == normalized[1]


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


def stable_error(body: Mapping[str, Any], code: str) -> bool:
    error = body.get("error")
    return (
        isinstance(error, dict)
        and set(error) == {"code", "message", "fields"}
        and error.get("code") == code
        and isinstance(error.get("message"), str)
        and bool(error["message"])
        and error.get("fields") is None
    )


def stable_conflict(body: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    return stable_error(body, "version_conflict") and body.get("current") == current


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


GENERATION_2_BROWSER_CHECK_SCRIPT = r"""
const { chromium } = require('/tmp/evaluator-tools/node_modules/playwright');

const baseUrl = process.argv[2];
const checks = [];
const diagnostics = { consoleErrors: [], pageErrors: [] };
const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const originalTitle = `grader-conflict-${suffix}`;
const draftTitle = `${originalTitle}-unsaved`;
const serverTitle = `${originalTitle}-server`;
const draftNotes = 'unsaved browser notes';
let browser;
let requestContext;
let currentIdea;

function record(id, passed, evidence, requirementIds) {
  checks.push({ id, passed, evidence, requirement_ids: requirementIds });
}

async function main() {
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    requestContext = page.request;
    page.on('pageerror', error => diagnostics.pageErrors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && !/favicon/i.test(message.text())) {
        diagnostics.consoleErrors.push(message.text());
      }
    });

    const created = await requestContext.post(`${baseUrl}/api/ideas`, {
      data: { title: originalTitle, notes: 'original browser notes' }
    });
    if (created.status() !== 201) throw new Error(`probe create status=${created.status()}`);
    currentIdea = await created.json();
    if (!Number.isInteger(currentIdea.id) || currentIdea.version !== 1) {
      throw new Error(`invalid probe representation=${JSON.stringify(currentIdea)}`);
    }

    const navigation = await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 20000 });
    if (!navigation || !navigation.ok()) {
      throw new Error(`navigation status=${navigation?.status()}`);
    }
    try {
      const card = page.getByText(originalTitle, { exact: true })
        .locator('xpath=ancestor::*[.//button][1]');
      await card.getByRole('button', { name: /edit/i }).click();
      const editTitle = page.getByLabel(/title/i).last();
      const editNotes = page.getByLabel(/notes/i).last();
      await editTitle.fill(draftTitle);
      await editNotes.fill(draftNotes);

    const external = await requestContext.patch(`${baseUrl}/api/ideas/${currentIdea.id}`, {
      headers: { 'If-Match': `"${currentIdea.version}"` },
      data: { title: serverTitle }
    });
    if (external.status() !== 200) {
      throw new Error(`external mutation status=${external.status()}`);
    }
    currentIdea = await external.json();
    if (currentIdea.version !== 2 || currentIdea.title !== serverTitle) {
      throw new Error(`external mutation representation=${JSON.stringify(currentIdea)}`);
    }

    const attempts = [];
    const observe = request => {
      if (request.method() === 'PATCH' && request.url().endsWith(`/api/ideas/${currentIdea.id}`)) {
        attempts.push(request.headers()['if-match'] || '');
      }
    };
    page.on('request', observe);
    const conflictResponse = page.waitForResponse(
      response => response.request().method() === 'PATCH'
        && response.url().endsWith(`/api/ideas/${currentIdea.id}`),
      { timeout: 10000 }
    );
    await page.getByRole('button', { name: /save|update/i }).last().click();
    const conflict = await conflictResponse;
    await page.waitForTimeout(300);
    page.off('request', observe);

    const alert = page.locator('[role="alert"]:visible, [aria-live]:visible')
      .filter({ hasText: /changed|conflict|elsewhere|reload/i });
    const reload = page.getByRole('button', { name: /reload current idea/i });
    const conflictVisible = await alert.count() > 0 && await alert.first().isVisible();
    const reloadVisible = await reload.count() > 0 && await reload.first().isVisible();
    record(
      'G2-UI-STALE-CONFLICT',
      conflict.status() === 409 && conflictVisible && reloadVisible,
      `status=${conflict.status()}; alert=${conflictVisible}; reload=${reloadVisible}`,
      ['G2-UI-03', 'G2-UI-04']
    );

    const titlePreserved = await editTitle.inputValue() === draftTitle;
    const notesPreserved = await editNotes.inputValue() === draftNotes;
    record(
      'G2-UI-CONFLICT-PRESERVES-DRAFT',
      titlePreserved && notesPreserved,
      `title=${titlePreserved}; notes=${notesPreserved}`,
      ['G2-UI-02', 'G2-UI-04']
    );

    const storedBeforeReload = await requestContext.get(`${baseUrl}/api/ideas/${currentIdea.id}`);
    const storedBody = await storedBeforeReload.json();
    const noRetry = attempts.length === 1
      && attempts[0] === '"1"'
      && storedBeforeReload.status() === 200
      && storedBody.version === 2
      && storedBody.title === serverTitle;
    record(
      'G2-UI-CONFLICT-NO-SILENT-RETRY',
      noRetry,
      `attempts=${JSON.stringify(attempts)}; stored_version=${storedBody.version}; stored_title=${storedBody.title}`,
      ['G2-UI-03', 'G2-UI-04']
    );

      if (reloadVisible) {
        await reload.click();
        await page.waitForFunction(({ serverTitle }) =>
          [...document.querySelectorAll('input')].some(input => input.getClientRects().length > 0 && input.value === serverTitle)
          || [...document.querySelectorAll('body *')].some(node => node.getClientRects().length > 0 && node.textContent.trim() === serverTitle),
          { serverTitle }, { timeout: 8000 });
      }
      const staleDraftCount = await page.locator('input').evaluateAll((inputs, title) => inputs.filter(input => input.value === title).length, draftTitle);
      const draftHidden = reloadVisible && staleDraftCount === 0;
    record(
      'G2-UI-CONFLICT-RELOAD-CURRENT',
      draftHidden,
      `server title visible; stale draft field count=${staleDraftCount}`,
      ['G2-UI-04']
    );

      record(
        'G2-UI-CONFLICT-RUNTIME-ERRORS',
        diagnostics.pageErrors.length === 0 && diagnostics.consoleErrors.length === 0,
        `page_errors=${JSON.stringify(diagnostics.pageErrors)}; console_errors=${JSON.stringify(diagnostics.consoleErrors)}`,
        ['G2-UI-05']
      );
    } catch (error) {
      for (const [id, requirements] of [
        ['G2-UI-STALE-CONFLICT', ['G2-UI-03', 'G2-UI-04']],
        ['G2-UI-CONFLICT-PRESERVES-DRAFT', ['G2-UI-02', 'G2-UI-04']],
        ['G2-UI-CONFLICT-NO-SILENT-RETRY', ['G2-UI-03', 'G2-UI-04']],
        ['G2-UI-CONFLICT-RELOAD-CURRENT', ['G2-UI-04']]
      ]) {
        if (!checks.some(check => check.id === id)) {
          record(id, false, `browser flow failed: ${error.message}`, requirements);
        }
      }
      if (!checks.some(check => check.id === 'G2-UI-CONFLICT-RUNTIME-ERRORS')) {
        record('G2-UI-CONFLICT-RUNTIME-ERRORS', diagnostics.pageErrors.length === 0 && diagnostics.consoleErrors.length === 0,
          `page_errors=${JSON.stringify(diagnostics.pageErrors)}; console_errors=${JSON.stringify(diagnostics.consoleErrors)}`, ['G2-UI-05']);
      }
    }
  } catch (error) {
    console.error('DEVLAB_GRADER_ERROR:' + JSON.stringify({ error: error.message, diagnostics }));
    process.exitCode = 2;
  } finally {
    if (currentIdea && requestContext) {
      try {
        const latest = await requestContext.get(`${baseUrl}/api/ideas/${currentIdea.id}`);
        if (latest.status() === 200) {
          const body = await latest.json();
          const deleted = await requestContext.delete(`${baseUrl}/api/ideas/${currentIdea.id}`, {
            headers: { 'If-Match': `"${body.version}"` }
          });
          if (deleted.status() !== 204) {
            throw new Error(`cleanup delete status=${deleted.status()}`);
          }
        } else if (latest.status() !== 404) {
          throw new Error(`cleanup read status=${latest.status()}`);
        }
      } catch (error) {
        console.error('DEVLAB_GRADER_ERROR:' + JSON.stringify({
          error: `browser probe cleanup failed: ${error.message}`, diagnostics
        }));
        process.exitCode = 2;
      }
    }
    if (checks.length) {
      console.log('DEVLAB_BROWSER_RESULT:' + JSON.stringify({ checks, diagnostics }));
    }
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
