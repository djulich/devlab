"""Independent black-box grader for the system-evolution demo.

This module deliberately does not use DevLab workflow state.  It invokes an
evaluator-owned Docker executable by absolute path and confines every Compose
mutation to one validated project name.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import secrets
import shutil
import socket
import subprocess
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
    ) -> None:
        self.target = target.resolve()
        self.generation = generation
        self.project = validate_project_name(compose_project)
        self.runner = runner
        discovered = shutil.which("docker") if docker_path is None else str(docker_path)
        self.docker = Path(discovered).resolve() if discovered else None
        self.host_port = host_port or available_port()
        self.generation_1_fixture = generation_1_fixture
        suffix = secrets.token_hex(6)
        self.prefix = f"grader-{suffix}"
        self.environment = self._environment(suffix)
        self.result = GradeResult(generation)
        self.started = False
        self.lifecycle_attempted = False

    def grade(self) -> GradeResult:
        try:
            if not self._validate_inputs():
                return self._finish()
            if self.generation == 2:
                self.result.add(
                    Check(
                        "G2-GRADING-NOT-IMPLEMENTED",
                        "migration",
                        "unverified",
                        0,
                        "generation 2 migration and concurrency grading is a later bounded slice",
                        hard_gate=True,
                    )
                )
                return self._finish()
            self._structural_checks()
            if self.docker is None:
                self._docker_unverified()
                return self._finish()
            if not self._compose_prerequisite_check():
                return self._finish()
            if not self._compose_config_checks():
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
            self._api_checks()
            self._persistence_checks()
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
            self.generation_1_fixture is None or not self.generation_1_fixture.is_file()
        ):
            self.result.add(
                Check(
                    "INPUT-GENERATION-1-FIXTURE",
                    "migration",
                    "grader_error",
                    0,
                    "generation 2 requires an existing --generation-1-fixture",
                )
            )
            return False
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
                "passed" if named_volume else "failed",
                0,
                f"db_mounts={db_mounts!r}",
                ("G1-DEP-03",),
            )
        )
        return exact and ports_ok

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


def command_evidence(result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    return f"exit={result.returncode}" + (f"; {detail[-4000:]}" if detail else "")


def summarize_http(response: tuple[int, dict[str, Any], float, str]) -> str:
    status, body, _, error = response
    rendered = json.dumps(body, ensure_ascii=False, sort_keys=True)
    return f"status={status}; body={rendered[:2000]}" + (f"; error={error}" if error else "")


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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        grader = SystemEvolutionGrader(
            args.target,
            args.generation,
            args.compose_project,
            generation_1_fixture=args.generation_1_fixture,
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
