from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.evaluations.harness import EvaluationScenario, command_check, run_live_evaluation

pytestmark = pytest.mark.skipif(
    os.environ.get("DEVLAB_LIVE_EVALS") != "1",
    reason="live DevLab evaluations require DEVLAB_LIVE_EVALS=1",
)


def test_live_cli_calculator_happy_path_evaluation(tmp_path: Path) -> None:
    scenario = EvaluationScenario(
        id="live-cli-calculator-happy-path",
        title="Live CLI calculator happy path",
        system_spec=(
            "Build a Python CLI calculator in calculator.py with add and subtract commands. "
            "The commands must print only the numeric result."
        ),
        max_sessions=int(os.environ.get("DEVLAB_LIVE_MAX_SESSIONS", "10")),
        checks=(
            command_check("add command", ["calculator.py", "add", "2", "3"], "5"),
            command_check("subtract command", ["calculator.py", "subtract", "7", "4"], "3"),
        ),
    )
    agent_config = os.environ.get("DEVLAB_LIVE_AGENTS_TOML")

    diagnostics = run_live_evaluation(
        tmp_path,
        scenario,
        provider=os.environ.get("DEVLAB_LIVE_PROVIDER"),
        model=os.environ.get("DEVLAB_LIVE_MODEL"),
        effort=os.environ.get("DEVLAB_LIVE_EFFORT"),
        agent_config=Path(agent_config) if agent_config else None,
        max_sessions=scenario.max_sessions,
    )

    diagnostics_path = tmp_path / ".devlab/evaluations" / f"{scenario.id}.json"
    failure_context = (
        f"target_root={tmp_path}\n"
        f"diagnostics={diagnostics_path}\n"
        f"agent_logs={tmp_path / '.devlab/logs/agents'}\n"
        f"diagnostics_json={diagnostics_path.read_text()}"
    )
    assert diagnostics.completed is True, failure_context
    assert diagnostics.exit_code == 0, failure_context
    assert all(check["passed"] for check in diagnostics.checks), failure_context
