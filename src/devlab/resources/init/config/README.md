# DevLab Configuration

This directory contains target-local DevLab configuration. These files are part of the target repository's auditable workflow state and may be updated through normal DevLab tasks.

## Files

- `tooling.md` — human/agent-readable tooling policy and preferences.
- `agents.toml` — human-owned worker agent provider/model/command configuration.
- `profiles/*.toml` — task profiles defining tooling summaries, default validation, and executable environment lifecycle.
- `test-services.toml` — optional workspace-owned local test-service definitions.
- `prerequisites/*.md` — optional focused operator resolution guides referenced
  by profile prerequisites.

## Tooling Policy

`tooling.md` guides agents when planning, implementing, and reviewing work. Profile tasks must follow this policy. For example, if `tooling.md` says GUI work uses React, GUI profiles should use React-oriented tooling and validation.

## Agent Configuration

`agents.toml` controls how DevLab invokes worker agents for each role. It supports defaults, per-role overrides, provider command templates, model/effort settings, and stdin-based prompt delivery for CLIs that require it.

The file is intended to be edited by the human operator. See `docs/agent-configuration.md` in the DevLab repository for a full reference.

## Profiles

Each task resolves to exactly one profile:

- if task metadata contains `profile = "<id>"`, DevLab uses `.devlab/config/profiles/<id>.toml`;
- otherwise DevLab uses `profile = "default"`.

Profiles define task-type defaults such as validation commands, session
environment lifecycle, operation-scoped prerequisites, and managed-test-service
references. Profile sections omitted from a profile are treated as empty/no-op
values.

The default `neutral` initialization template leaves validation empty until the
project's toolchain is chosen. Explicit `python`, `rust`, `go`, `c`, and `cpp`
templates provide starter policies and profiles. The selected template is not a
runtime language mode; these files remain the authority and may be adapted to
the repository's actual conventions.

Existing profiles should only be extended or fixed in backward-compatible ways. If new behavior would remove, replace, narrow, or materially alter tooling, validation, setup, teardown, services, or assumptions used by already-planned tasks, create a new reusable profile instead.

## Planner Responsibilities

The planner should search existing profiles before creating new ones. If no profile fits upcoming work, it should create a task to add or update a suitable reusable profile before creating tasks that depend on that profile.
