# Work History

This folder collects the agent session artifacts to create a thorough development history.

The files in this folder are created by the development harness, aka the orchestrator.

## Filenames

The filenames for the history items follow this format:

`<datetime>_<role>_<type>.md`

Where:

 - `<datetime>`: The event date and time in this ISO 8601 format: `YYYYMMDDThhmmss`.
 - `<role>`: The agent role which created the artifact, e.g. `developer`, `planner` or `architect`.
 - `<type>`: The entry type, e.g. `session-handoff`.

Example:

    20260426T223900_developer_session-handoff.md
