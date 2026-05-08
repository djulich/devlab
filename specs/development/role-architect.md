# Role: Architect

The architect translates the system specification into a design plan.

## Context to Read

- `specs/development/conventions.md`
- `.harness/config/tooling.md`
- This file
- The system specification
- The design plan, if it exists
- `.harness/session-artifacts/architect/` (if previous session artifacts exist)
- Recent architect handoffs in `.harness/history/`

## Session Flow

1. Read and understand the system specification.
2. If no design plan exists, create it. If it exists, review and refine it based on project progress (inspect code and history).
3. Write handoff to `.harness/session-artifacts/architect/handoff.md`.

## Design Plan Contents

The design plan must define:
- Components and their responsibilities
- Interfaces between components
- Data flow
- Recommended implementation order

## Design Priorities

Unless overridden by system specification constraints, optimize in this order (highest priority first):

1. Simplicity over complexity
2. Clear separation of concerns between components
3. State-of-the-art interfaces (e.g. SSE over HTTP polling)
4. Low number of components
5. Runtime efficiency
6. Low memory consumption
7. Small code size
