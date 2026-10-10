from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Exercise the real entry point, forbidding workflow imports and side effects.
COMPLETE = """
import sys
def audit(event, args):
    if event in ('subprocess.Popen', 'os.system', 'os.mkdir', 'os.remove', 'os.rename'):
        raise AssertionError((event, args))
    if (event == 'open' and args[0] != '/dev/null'
            and isinstance(args[1], str) and any(c in args[1] for c in 'wax+')):
        raise AssertionError((event, args))
sys.addaudithook(audit)
import argcomplete
original = argcomplete.autocomplete
def exit_completion(code):
    assert 'devlab.cli_commands' not in sys.modules
    assert 'devlab.orchestrator' not in sys.modules
    assert 'devlab.workspace' not in sys.modules
    raise SystemExit(code)
def complete(parser, **kwargs):
    return original(parser, output_stream=sys.stdout, exit_method=exit_completion, **kwargs)
argcomplete.autocomplete = complete
from devlab.cli import main
main()
"""


def complete(line: str, root: Path) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-B", "-c", COMPLETE],
        cwd=root,
        env={
            **os.environ,
            "_ARGCOMPLETE": "1",
            "COMP_LINE": line,
            "COMP_POINT": str(len(line)),
            "_ARGCOMPLETE_SHELL": "bash",
            "_ARGCOMPLETE_SUPPRESS_SPACE": "1",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split("\v") if result.stdout else []


@pytest.mark.parametrize(
    "line, expected",
    [
        ("devlab cont", ["continue"]),
        ("devlab continue --heart", ["--heartbeat-interval"]),
        ("devlab trust exec", ["executable-config"]),
        ("devlab session handoff s", ["submit"]),
        ("devlab init --template py", ["python"]),
        ("devlab continue --clarification-mode o", ["operator"]),
        ("devlab completion z", ["zsh"]),
        ("devlab continue --heartbeat-interval ", []),
    ],
)
def test_completion_is_read_only_and_does_not_import_workflow(
    tmp_path: Path, line: str, expected: list[str]
) -> None:
    assert complete(line, tmp_path) == expected
    assert list(tmp_path.iterdir()) == []


def test_path_completion_respects_directory_options_and_spaces(tmp_path: Path) -> None:
    (tmp_path / "target space").mkdir()
    (tmp_path / "target.toml").touch()
    assert complete("devlab continue --root tar", tmp_path) == ["target\\ space/"]
    assert complete("devlab agent-smoke-test --config tar", tmp_path) == [
        "target\\ space/",
        "target.toml",
    ]
    assert complete("devlab continue --root missing/", tmp_path) == []


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_fallback_is_shell_code_without_workflow_imports(tmp_path: Path, shell: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from devlab.cli import main; main(); import sys; "
            "assert 'devlab.cli_commands' not in sys.modules",
            "completion",
            shell,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "_python_argcomplete" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(shutil.which("bash") is None, reason="Bash is not installed")
def test_bash_registration_completes_through_real_entry_point(tmp_path: Path) -> None:
    executable = Path(sys.executable).parent / "devlab"
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            """
eval "$("$1" completion bash)"
COMP_LINE="devlab continue --heart"
COMP_POINT=${#COMP_LINE}
COMP_WORDS=(devlab continue --heart)
COMP_CWORD=2
COMP_TYPE=9
_python_argcomplete "$1"
printf '%s\n' "${COMPREPLY[@]}"
""",
            "bash",
            str(executable),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "--heartbeat-interval"


@pytest.mark.skipif(shutil.which("zsh") is None, reason="Zsh is not installed")
def test_packaged_zsh_completion_registers(tmp_path: Path) -> None:
    completion_dir = ROOT / "share-data/share/zsh/site-functions"
    result = subprocess.run(
        [
            "zsh",
            "-f",
            "-c",
            """
fpath=("$1" $fpath)
autoload -Uz compinit
compinit -D
print -r -- "${_comps[devlab]}"
""",
            "zsh",
            str(completion_dir),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "_devlab"


@pytest.mark.parametrize("symlink", [False, True])
def test_bash_discovers_packaged_completion_from_installation_prefix(
    tmp_path: Path, symlink: bool
) -> None:
    framework = Path("/usr/share/bash-completion/bash_completion")
    if not framework.is_file() or shutil.which("bash") is None:
        pytest.skip("Bash completion framework is unavailable")
    prefix = tmp_path / "installed tool"
    executable = prefix / "bin/devlab"
    executable.parent.mkdir(parents=True)
    executable.write_text(f"#!{sys.executable}\nfrom devlab.cli import main\nmain()\n")
    executable.chmod(0o755)
    relative = "share/bash-completion/completions/devlab"
    completion = prefix / relative
    completion.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "share-data" / relative, completion)
    if symlink:
        link = tmp_path / "user-bin/devlab"
        link.parent.mkdir()
        link.symlink_to(executable)
        executable = link
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            """
source "$1"
type _comp_load >/dev/null 2>&1 || exit 77
_comp_load devlab || exit 1
COMP_LINE="devlab continue --heart"
COMP_POINT=${#COMP_LINE}
COMP_WORDS=(devlab continue --heart)
COMP_CWORD=2
COMP_TYPE=9
_python_argcomplete devlab
printf '%s\n' "${COMPREPLY[@]}"
""",
            "bash",
            str(framework),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(executable.parent) + os.pathsep + os.environ["PATH"],
            "BASH_COMPLETION_USER_DIR": str(tmp_path / "empty"),
        },
        capture_output=True,
        text=True,
    )
    if result.returncode == 77:
        pytest.skip("Bash completion framework lacks prefix discovery")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "--heartbeat-interval"
