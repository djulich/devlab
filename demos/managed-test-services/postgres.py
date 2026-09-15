"""Target-owned disposable PostgreSQL service; requires Docker and postgres:16."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path


def docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def inspect(name: str, identity: str, service: str) -> dict | None:
    names = docker("container", "ls", "-a", "--format", "{{.Names}}").splitlines()
    if name not in names:
        return None
    data = json.loads(docker("inspect", name))[0]
    labels = data["Config"].get("Labels") or {}
    if (
        labels.get("devlab.test-instance") != identity
        or labels.get("devlab.test-service") != service
    ):
        raise ValueError("refusing container with different ownership")
    return data


def main() -> None:
    identity = os.environ["DEVLAB_TEST_SERVICE_INSTANCE"]
    service = os.environ["DEVLAB_TEST_SERVICE_ID"]
    private = Path(os.environ["DEVLAB_TEST_SERVICE_STATE_DIR"])
    result_path = Path(os.environ["DEVLAB_TEST_SERVICE_RESULT"])
    name = f"devlab-test-{identity}"
    action = sys.argv[1]
    data = inspect(name, identity, service)
    if action == "destroy":
        if data is not None:
            docker("rm", "-f", "-v", name)
        return
    if action == "check":
        if data is None or not data["State"]["Running"]:
            raise ValueError("owned test database is not running")
        docker("exec", name, "pg_isready", "-U", "devlab", "-d", "devlab")
        return
    if action != "ensure":
        raise ValueError("expected ensure, check, or destroy")
    if data is None:
        # Do not download/install host prerequisites or pull an image implicitly.
        docker("image", "inspect", "postgres:16")
        password = secrets.token_hex(24)
        env_file = private / "postgres.env"
        env_file.write_text(
            f"POSTGRES_USER=devlab\nPOSTGRES_DB=devlab\nPOSTGRES_PASSWORD={password}\n"
        )
        env_file.chmod(0o600)
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"devlab.test-instance={identity}",
            "--label",
            f"devlab.test-service={service}",
            "--env-file",
            str(env_file),
            "-p",
            "127.0.0.1::5432",
            "postgres:16",
        )
        data = inspect(name, identity, service)
    assert data is not None
    if not data["State"]["Running"]:
        docker("start", name)
    environment = dict(value.split("=", 1) for value in data["Config"]["Env"])
    password = environment["POSTGRES_PASSWORD"]
    for attempt in range(30):
        try:
            docker("exec", name, "pg_isready", "-U", "devlab", "-d", "devlab")
            break
        except subprocess.CalledProcessError:
            if attempt == 29:
                raise ValueError("owned database did not become ready") from None
            time.sleep(1)
    port = docker("port", name, "5432/tcp").split(":")[-1]
    staged = result_path.with_suffix(".tmp")
    staged.write_text(
        json.dumps(
            {
                "schema": 1,
                "instance": identity,
                "environment": {
                    "TEST_DATABASE_URL": f"postgresql://devlab:{password}@127.0.0.1:{port}/devlab"
                },
            }
        )
    )
    staged.chmod(0o600)
    staged.replace(result_path)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        # Never echo docker inspect output or generated connection credentials.
        print(
            "Managed test database operation failed; check Docker, image, and ownership.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
