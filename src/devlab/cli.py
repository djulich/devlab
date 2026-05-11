from __future__ import annotations

import argparse
from pathlib import Path

from devlab.init import format_init_result, init_workspace
from devlab.orchestrator import DEFAULT_PROJECT_ROOT, assess_state, run_loop


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="devlab",
        description="Orchestrate agentic development sessions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a target-local .devlab tree.")
    init_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to initialize (default: current working directory).",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing starter files.",
    )

    run_parser = subparsers.add_parser("run", help="Run the DevLab workflow loop.")
    run_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to operate on (default: current working directory).",
    )
    run_parser.add_argument(
        "--auto",
        action="store_true",
        help="Run autonomously without pausing between sessions.",
    )
    run_parser.add_argument(
        "--max-sessions",
        type=int,
        default=20,
        help="Maximum number of sessions to run (default: 20).",
    )
    run_parser.add_argument(
        "--provider",
        default=None,
        help="Override the configured provider for this run.",
    )
    run_parser.add_argument(
        "--model",
        default=None,
        help="Override the configured model for this run.",
    )
    run_parser.add_argument(
        "--effort",
        default=None,
        help="Override the configured effort for this run.",
    )
    run_parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        help="Pass --dangerously-skip-permissions to the agent command.",
    )

    status_parser = subparsers.add_parser("status", help="Show the next selected role.")
    status_parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help="Project root to inspect (default: current working directory).",
    )

    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "init":
        result = init_workspace(root, force=args.force)
        print(format_init_result(result, root))
    elif args.command == "run":
        run_loop(
            root,
            auto=args.auto,
            max_sessions=args.max_sessions,
            provider=args.provider,
            model=args.model,
            effort=args.effort,
            dangerous_skip_permissions=args.dangerously_skip_permissions,
        )
    elif args.command == "status":
        role_name = assess_state(root)
        if role_name is None:
            print("No role selected; workflow is complete or blocked.")
        else:
            print(f"Next role: {role_name}")


if __name__ == "__main__":
    main()
