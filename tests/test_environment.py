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
