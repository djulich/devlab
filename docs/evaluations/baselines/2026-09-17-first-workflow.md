# First-Workflow Demonstration Baseline — 2026-09-17

This baseline records the public-demo rehearsal for the small `hello-devlab`
workflow in `demos/first-workflow/`. It is launch-readiness evidence, not a
comparison between providers or a cost-effectiveness claim.

## Environment

- Platform: Linux
- DevLab version: `0.1.0`, installed as a non-editable tool from the issue #4
  working tree
- Provider: Codex CLI `0.154.0`
- Model and effort: provider defaults; DevLab overrides were empty
- Target: new disposable Git repository prepared by
  `demos/first-workflow/prepare.sh`
- Session maximum: 900 seconds each
- Run ceiling: 12 provider calls and 80 elapsed minutes

An isolated clean clone built and installed successfully before the live run.
The first smoke check then exposed that successful smoke logs dirtied the target
worktree. The rehearsal was paused, the logs were moved to the ignored
`.devlab/local/agent-smoke/` boundary with a regression test, and the
non-editable tool was reinstalled before the complete run. After the changes
were committed, another clean clone of the committed result installed
successfully, prepared the demo, passed `devlab doctor` with a clean worktree,
and completed the marker-protected reset.

## Run

The successful demonstrated path used one smoke call and six role sessions:

1. architect — 77.9 seconds;
2. planner — 68.3 seconds;
3. developer for `T0001` — 103.9 seconds;
4. reviewer for `T0001` — 64.9 seconds;
5. integrator for `M1` — 75.5 seconds; and
6. architect milestone review — 41.3 seconds.

Role execution totaled about 7 minutes 12 seconds. The end-to-end rehearsal,
including bounded stops, inspection, approval waits, the smoke-test repair, and
the repeated smoke check, remained below 50 minutes and used eight successful
provider calls. A normal run of the corrected path would use seven calls when no
review rework is needed.

After the first two sessions, DevLab stopped cleanly with `developer` and
`T0001` as the durable next action. `status`, the then-separate
`workflow-state` report, and `diagnostics` read that state without changing the
worktree. Re-running `devlab continue`
resumed from the committed planning state.

## Outcome

- Workflow result: complete
- Role sequence: architect, planner, developer, reviewer, integrator, architect
- Tasks: one closed task; one developer/reviewer cycle; no rework
- Milestone: integrated, architecture-reviewed, and tagged
  `devlab/milestone/M1`
- Clarifications, research requests, and findings: none
- Artifact hygiene: no flagged paths
- Final worktree: clean
- `devlab doctor`: passed
- `uv run hello-devlab Ada`: printed `Hello, Ada!`
- pytest: 2 passed
- Ruff: passed
- ty: passed

Diagnostics reported three advisory unverified dependency introductions for
pytest, Ruff, and ty. These are the toolchain dependencies explicitly required
by the demo specification and do not represent a failed validation or an
unexpected runtime dependency.

## Conclusion

The demonstration exercises initialization, executable-configuration review,
provider wiring, planning, bounded interruption and continuation, implementation,
review, integration, architecture review, durable Git-backed state, diagnostics,
and final product verification within the published time and call budget.
