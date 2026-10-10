from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from devlab.environment import (
    EnvironmentCommandError,
    EnvironmentConfig,
    EnvironmentManager,
    EnvironmentTimeouts,
    _run_environment_command,
    run_validation_commands,
)


@pytest.mark.parametrize("context", ["task", "milestone"])
@pytest.mark.parametrize("environment_source", ["unset", "service", "command"])
def test_validation_uses_running_devlab_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context: str,
    environment_source: str,
) -> None:
    if environment_source == "unset":
        monkeypatch.delenv("DEVLAB_PYTHON", raising=False)
    else:
        monkeypatch.setenv("DEVLAB_PYTHON", "/stale/operator/python")
    environment = {"DEVLAB_TEST_VALUE": "service environment preserved"}
    if environment_source != "unset":
        environment["DEVLAB_PYTHON"] = "/different/service/python"
    script = tmp_path / "validate.py"
    script.write_text(
        "import json, os, sys\n"
        "from devlab.profiles import load_profiles\n"
        "assert callable(load_profiles)\n"
        "print(json.dumps([sys.executable, os.environ['DEVLAB_TEST_VALUE']]))\n"
    )
    run = run_validation_commands(
        tmp_path,
        role_name="orchestrator" if context == "task" else "integrator",
        task_id="T0001" if context == "task" else None,
        milestone_id="M1" if context == "milestone" else None,
        session_id="interpreter",
        commands=(f'"$DEVLAB_PYTHON" {shlex.quote(str(script))}',),
        environ=environment if environment_source != "command" else None,
        command_environments=(environment,) if environment_source == "command" else None,
    )
    assert run.outcome == "passed", run.commands
    assert json.loads(run.commands[0].output_summary) == [
        str(Path(sys.executable).absolute()),
        "service environment preserved",
    ]
    if environment_source == "unset":
        assert "DEVLAB_PYTHON" not in os.environ
    else:
        assert os.environ["DEVLAB_PYTHON"] == "/stale/operator/python"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group termination")
@pytest.mark.parametrize("operation", ["validation", "pre_session", "setup", "post_session"])
@pytest.mark.parametrize("close_output", [False, True])
def test_timeout_kills_children_even_after_shell_exit(
    tmp_path: Path, operation: str, close_output: bool
) -> None:
    script = tmp_path / "child.py"
    script.write_text(
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('captured stdout', flush=True)\n"
        "print('captured stderr', file=sys.stderr, flush=True)\n"
        + ("os.close(1)\nos.close(2)\n" if close_output else "")
        + "time.sleep(2.7)\n"
        + "Path('child-survived').write_text('unexpected write after timeout')\n"
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    # Exercise both an already-exited shell with inherited pipes and a shell
    # that exits on SIGTERM while a child has already closed its pipes.
    command += "; true" if close_output else " &"
    started = time.monotonic()
    if operation == "validation":
        run = run_validation_commands(
            tmp_path,
            role_name="developer",
            task_id="T0001",
            session_id="timeout",
            commands=(command, "touch next-command-ran"),
            timeout=1,
        )
        assert run.outcome == "timeout"
        assert len(run.commands) == 1
        assert run.commands[0].return_code is None
        log = tmp_path / run.commands[0].log_path
        record = json.loads(
            (tmp_path / ".devlab/verification/tasks/T0001/timeout.json").read_text()
        )
        assert record["outcome"] == "timeout"
    else:
        manager = EnvironmentManager(
            tmp_path,
            EnvironmentConfig(
                **{operation: (command, "touch next-command-ran")},
                timeouts=EnvironmentTimeouts(pre_session=1, setup=1, post_session=1),
            ),
        )
        with pytest.raises(EnvironmentCommandError) as caught:
            getattr(manager, operation)("developer")
        assert caught.value.phase == operation
        assert caught.value.return_code is None
        log = caught.value.log_path
    assert time.monotonic() - started < 5
    output = log.read_text()
    assert output.count("captured stdout") == 1
    assert output.count("captured stderr") == 1
    time.sleep(1.5)
    assert not (tmp_path / "child-survived").exists()
    assert not (tmp_path / "next-command-ran").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group termination")
def test_timeout_drain_is_bounded_when_detached_child_keeps_pipes(tmp_path: Path) -> None:
    script = tmp_path / "parent.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        "start_new_session=True)\n"
        "Path('detached-pid').write_text(str(child.pid))\n"
        "print('before timeout', flush=True)\n"
        "print('error before timeout', file=sys.stderr, flush=True)\n"
        "time.sleep(30)\n"
    )
    started = time.monotonic()
    try:
        run = run_validation_commands(
            tmp_path,
            role_name="integrator",
            milestone_id="M1",
            session_id="detached",
            commands=(f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}; true",),
            timeout=1,
        )
        assert time.monotonic() - started < 6
        assert run.outcome == "timeout"
        output = (tmp_path / run.commands[0].log_path).read_text()
        assert "before timeout" in output
        assert "error before timeout" in output
    finally:
        pid_file = tmp_path / "detached-pid"
        if pid_file.exists():
            os.killpg(int(pid_file.read_text()), signal.SIGKILL)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group termination")
def test_interruption_cleans_up_owned_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "interrupted.py"
    script.write_text(
        "import signal, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(1.8)\n"
        "Path('child-survived').write_text('unexpected write after interruption')\n"
    )
    communicate = subprocess.Popen.communicate
    interrupted = False

    def interrupt_once(
        process: subprocess.Popen[str], input: str | None = None, timeout: float | None = None
    ) -> tuple[str, str]:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            with pytest.raises(subprocess.TimeoutExpired):
                communicate(process, timeout=0.2)
            raise KeyboardInterrupt
        return communicate(process, input=input, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        _run_environment_command(
            tmp_path,
            f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}; true",
            environ=os.environ,
            timeout=30,
        )
    time.sleep(1)
    assert not (tmp_path / "child-survived").exists()


@pytest.mark.parametrize(
    "exit_code, outcome", [(0, "passed"), (7, "failed"), (127, "missing_tool")]
)
def test_validation_preserves_output_environment_and_exit_status(
    tmp_path: Path, exit_code: int, outcome: str
) -> None:
    script = tmp_path / "validate.py"
    script.write_text(
        "import os, sys\n"
        "print(os.environ['DEVLAB_TEST_VALUE'])\n"
        "print('diagnostic', file=sys.stderr)\n"
        f"sys.exit({exit_code})\n"
    )
    run = run_validation_commands(
        tmp_path,
        role_name="developer",
        task_id="T0001",
        session_id="normal",
        commands=(f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}",),
        environ={"DEVLAB_TEST_VALUE": "environment preserved"},
    )
    assert run.outcome == outcome
    assert run.commands[0].return_code == exit_code
    output = (tmp_path / run.commands[0].log_path).read_text()
    assert "environment preserved" in output
    assert "diagnostic" in output


def _validation_evidence_fixture(root: Path):
    from devlab.environment import reusable_task_validation

    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "product.txt").write_text("tested\n")
    run_validation_commands(
        root,
        role_name="developer",
        task_id="T0001",
        session_id="001",
        commands=("test -f product.txt",),
        source="task",
        contract_digest="contract",
    )
    evidence = reusable_task_validation(root, "T0001", ("test -f product.txt",), "contract")
    assert evidence is not None
    return evidence


def test_validation_evidence_survives_commit_and_workflow_bookkeeping(tmp_path: Path) -> None:
    from devlab.environment import reusable_task_validation

    evidence = _validation_evidence_fixture(tmp_path)
    (tmp_path / ".devlab/tasks").mkdir()
    (tmp_path / ".devlab/tasks/T0001.md").write_text("review bookkeeping\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "commit",
            "-qm",
            "Record tested content",
        ],
        check=True,
    )
    assert (
        reusable_task_validation(tmp_path, "T0001", ("test -f product.txt",), "contract")
        == evidence
    )


@pytest.mark.parametrize(
    "change",
    [
        "content",
        "new_file",
        "workspace_script",
        "delete",
        "mode",
        "config",
        "contract",
        "commands",
        "runtime",
        "log",
        "failure",
        "malformed",
        "legacy",
        "symlink",
    ],
)
def test_validation_evidence_rejects_changed_or_incomplete_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from devlab.environment import reusable_task_validation

    evidence = _validation_evidence_fixture(tmp_path)
    commands = ("test -f product.txt",)
    contract = "contract"
    if change == "content":
        (tmp_path / "product.txt").write_text("changed without a commit\n")
    elif change == "new_file":
        (tmp_path / "new.py").write_text("new code\n")
    elif change == "workspace_script":
        (tmp_path / ".devlab/check.sh").write_text("echo new validation logic\n")
    elif change == "delete":
        (tmp_path / "product.txt").unlink()
    elif change == "mode":
        (tmp_path / "product.txt").chmod(0o755)
    elif change == "config":
        (tmp_path / ".devlab/config").mkdir()
        (tmp_path / ".devlab/config/tooling.md").write_text("new configuration\n")
    elif change == "contract":
        contract = "different"
    elif change == "commands":
        commands = ("false",)
    elif change == "runtime":
        monkeypatch.setenv("VALIDATION_TEST_INPUT", "changed")
    elif change == "log":
        (tmp_path / evidence.log_paths[0]).unlink()
    elif change in {"failure", "malformed", "legacy"}:
        newer = tmp_path / ".devlab/verification/tasks/T0001/002.json"
        newer.write_text(
            {
                "failure": '{"outcome":"failed"}',
                "malformed": "[]",
                "legacy": '{"outcome":"passed"}',
            }[change]
        )
    elif change == "symlink":
        (tmp_path / "linked-input").symlink_to(tmp_path / "product.txt")
    assert reusable_task_validation(tmp_path, "T0001", commands, contract) is None


def test_validation_that_changes_inputs_cannot_supply_reusable_evidence(tmp_path: Path) -> None:
    from devlab.environment import reusable_task_validation

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    run = run_validation_commands(
        tmp_path,
        role_name="developer",
        task_id="T0001",
        session_id="001",
        commands=("echo changed > product.txt",),
        contract_digest="contract",
    )
    assert run.outcome == "passed"
    assert run.workspace_digest == ""
    assert (
        reusable_task_validation(tmp_path, "T0001", ("echo changed > product.txt",), "contract")
        is None
    )


def test_validation_reports_progress_before_execution_and_results_after_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import devlab.environment as environment

    messages: list[str] = []

    def info(message: str, *args: object, **kwargs: object) -> None:
        rendered = message % args
        if "; log: " in rendered:
            assert (tmp_path / rendered.split("; log: ", 1)[1]).is_file()
        messages.append(rendered)

    def command(root: Path, value: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert messages[-1].endswith(f": {value}")
        return subprocess.CompletedProcess(value, 0 if value == "first" else 1, "output", "")

    monkeypatch.setattr(environment.logger, "info", info)
    monkeypatch.setattr(environment, "_run_environment_command", command)
    run = run_validation_commands(
        tmp_path,
        role_name="orchestrator",
        task_id="T0001",
        session_id="retry",
        commands=("first", "second", "not-run"),
    )
    assert run.outcome == "failed"
    assert any("command 1/3: first" in message for message in messages)
    assert any("command 1 passed after" in message for message in messages)
    assert any("command 2 failed after" in message for message in messages)
    assert not any("not-run" in message for message in messages)
    assert messages[-1] == "Validation T0001: failed"
