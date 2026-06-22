# Release Policy

DevLab is pre-1.0 software. It is intended to become a reusable CLI and Python
package, but the workflow formats and operator experience are still evolving.

## Current Distribution

DevLab is not published to PyPI yet. Install it from a source checkout or Git URL
with `uv tool install`, as described in the README.

Before a PyPI release, the project should verify package metadata, license
metadata, source distributions, wheels, and installation from a clean environment.

## Versioning

DevLab uses semantic versioning.

While the version is `0.x`, minor releases may include breaking changes. Patch
releases should be bugfix-only and should not intentionally break existing target
workspaces.

After `1.0.0`, public compatibility surfaces should follow normal semantic
versioning:

- major versions may include breaking changes;
- minor versions add backward-compatible functionality;
- patch versions fix bugs without changing documented behavior.

## Compatibility Surfaces

The following should be treated as user-facing compatibility surfaces:

- CLI commands, options, and exit behavior;
- `.devlab/config/agents.toml`;
- profile TOML files under `.devlab/config/profiles/`;
- task, finding, milestone, workflow, and generation file formats;
- role handoff contracts that DevLab validates;
- target workspace layout under `.devlab/`;
- package installation and the `devlab` console script.

Packaged prompts are part of DevLab behavior, but their prose is not a stable API.
Prompt changes should still be reviewed carefully because they affect generated
workflow output.

## Breaking Changes Before 1.0

Breaking changes are allowed during `0.x` when they materially improve workflow
correctness, safety, maintainability, or operator clarity. They should be
documented in release notes or a migration note before external publication.

Examples of breaking changes include:

- changing task, finding, milestone, workflow, or generation file formats;
- renaming or removing CLI options;
- changing provider configuration semantics;
- changing when DevLab mutates or commits workflow state;
- requiring target workspaces to run a migration or regenerate planning state.

During `0.x`, old target workspaces are not guaranteed to keep working across all
minor upgrades. Prefer explicit diagnostics and repair guidance over silent
best-effort compatibility.

## Release Checklist

Before cutting a release:

- run `make check`;
- run relevant scripted workflow evaluations;
- run any selected live-agent baseline evaluations for the release risk;
- verify `uv build` produces an sdist and wheel;
- install the built wheel into a clean environment and run `devlab --help`;
- update README maturity guidance if evaluation confidence changed;
- document breaking changes and migration steps;
- tag the release in Git.

PyPI publication remains a future decision. Until then, release tags and Git URLs
are the expected installation path for non-development users.
