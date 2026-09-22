# Reviewer signal mismatch defaults to changes requested

When a valid reviewer result's two outcome signals disagree — its structured
`open_issues` list and the task file's `- [x] Approved` checkbox — the
orchestrator defaults to `changes_requested`. A task is only closed when both
signals agree (approved checkbox present AND no open issues). Any other
combination sends the task back for another review cycle. This trades extra
sessions on agent mistakes for resilience against the most likely real-agent
failure mode (producing one signal but not the other), bounded by
`max_sessions`. The mismatch cases log warnings to surface prompt/agent issues
in diagnostics.

The original decision referred to the rendered handoff's Open Issues section.
Current sessions submit a validated structured result, and the Markdown section
is rendered from it. Malformed candidates or mismatched session identity are
rejected by submission/result validation; this fallback applies only to outcome
signals within an accepted result. See [Handoffs and
continuity](../design.md#handoffs-and-continuity).
