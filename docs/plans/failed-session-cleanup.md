# Failed Session Cleanup

## Goal

Improve recovery after failed `devlab plan` / `devlab implement` sessions that leave diagnostic logs or session artifacts in the Git working tree.

DevLab should preserve diagnostics by default, but provide an explicit cleanup command so users can retry after inspecting or deciding to discard failed-session artifacts.

## Policy

- Preflight failures should happen before writing session logs or artifacts where practical.
- Logs from sessions that actually started are useful diagnostics and must not be silently deleted.
- DevLab must not automatically discard agent-created target-code changes after an attempted session.
- Cleanup should remove only known DevLab failed-session artifact locations and should avoid deleting tracked history.

## Implementation Scope

Add a mutating CLI command:

```bash
devlab clean-failed-session [--root PATH]
```

The command removes untracked files/directories under:

- `.devlab/logs/agents/`
- `.devlab/logs/environment/`
- `.devlab/session-artifacts/`

It should use Git's own ignore/tracking knowledge, e.g. `git clean -fd -- <paths>`, so tracked files such as committed history logs or `.gitkeep` files are preserved.

The command should not restore or delete arbitrary target-project changes. If source files or specs remain modified, the user must inspect, commit, restore, or clean them explicitly.

Add failure guidance to session failure paths where DevLab may leave logs/artifacts, pointing users to:

```bash
devlab clean-failed-session
```

## Non-goals

- Do not automatically run cleanup on failure.
- Do not delete tracked logs/history.
- Do not restore target source changes.
- Do not solve every possible dirty-tree cause; this is a safe cleanup aid for known DevLab session diagnostics.

## Validation

- Unit/CLI tests verify cleanup removes untracked agent logs and session artifacts.
- Tests verify cleanup preserves tracked files and unrelated target changes.
- Standard validation: `uv run ruff check`, `uv run ty check`, `uv run pytest -q`.
