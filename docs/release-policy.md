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

### Version Source

The `[project].version` value in `pyproject.toml` is the single authoritative
DevLab package version. Use plain semantic versions there, such as `0.2.0`,
without a `v` prefix.

The CLI reads the installed distribution metadata through
`importlib.metadata`; it does not duplicate the version in a Python module.
This makes `devlab --version` report the package that is actually being
executed, whether it was installed from a wheel, checkout, Git tag, or editable
checkout.

Package versions are independent from version fields in durable DevLab file
formats. Values such as `schema_version`, `layout_version`, and workflow
`version` advance only when their specific persisted format changes. They do
not track package releases.

### Choosing the Next Version

Choose the release version from the most significant user-facing change since
the previous release:

- increment the patch component for bug fixes that preserve documented
  behavior, for example `0.2.0` to `0.2.1`;
- increment the minor component for new capabilities, for example `0.2.1` to
  `0.3.0`;
- during `0.x`, also increment the minor component for intentional breaking
  changes and document their migration impact;
- release `1.0.0` when the public compatibility contract is considered stable;
- after `1.0.0`, increment the major component for breaking changes.

Do not bump the package version for every development commit. Select and record
the next version while preparing a release. If the current version has not yet
been released, compatible work may be included without another bump.

## Compatibility Surfaces

The following should be treated as user-facing compatibility surfaces:

- CLI commands, options, and exit behavior;
- `.devlab/config/agents.toml`;
- profile TOML files under `.devlab/config/profiles/`;
- managed-test-service configuration under `.devlab/config/test-services.toml`;
- task, finding, milestone, clarification, research, workflow, workflow-event,
  prerequisite-blocker, verification, test-service-state, and generation file
  formats;
- operator-local executable-configuration trust and prerequisite-attestation
  semantics;
- trusted session envelopes, structured result candidates/results, rendered
  handoff contracts, and archived submission evidence;
- target workspace layout under `.devlab/`;
- package installation and the `devlab` console script.

This list is the current candidate surface, not the final 1.x promise. The
stabilized compatibility and migration contract is tracked in
[issue #1](https://github.com/djulich/devlab/issues/1).

Packaged prompts are part of DevLab behavior, but their prose is not a stable
API. Prompt changes should still be reviewed carefully because they affect
generated workflow output.

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

## Release Procedure

Until DevLab is published to PyPI, a release consists of an immutable Git tag
and installable source distribution and wheel. Use tags of the form `vX.Y.Z`;
the tag for package version `0.2.0` is `v0.2.0`.

1. Review changes since the previous release and choose the next version using
   the rules above.
2. Update `[project].version` in `pyproject.toml`.
3. Refresh `uv.lock` so the root package entry records the same version.
4. Document notable changes. Include explicit migration guidance for breaking
   CLI, configuration, workspace-layout, or durable-format changes.
5. Run the complete development validation:

   ```bash
   make check
   ```

6. Run relevant scripted workflow evaluations and any live-agent baseline
   evaluations justified by the release risk.
7. Build both package formats:

   ```bash
   uv build
   ```

8. Verify that the source distribution and wheel contain the expected package
   metadata, license, resources, and documentation. The wheel contains only the
   installed product. The source distribution additionally contains `Makefile`,
   `uv.lock`, and the product tests so `make check` can validate the unpacked
   release source. Repository-only `demos/` content appears in neither artifact.
9. Install the built wheel into a clean environment and smoke-test the installed
   command:

   ```bash
   devlab --version
   devlab --help
   ```

   The reported version must match `pyproject.toml`.
10. Commit the release preparation, then create an annotated tag:

    ```bash
    git tag -a vX.Y.Z -m "DevLab X.Y.Z"
    ```

11. Verify that the tagged commit is clean and that installation from the tag
    succeeds. Push the commit and tag only when the release is ready to share.

Before considering the release complete:

- update README maturity guidance if evaluation confidence changed;
- retain the validation and evaluation results needed to support release
  claims;
- ensure users can install by immutable tag rather than relying on `main`.

PyPI publication remains a future decision. Until then, release tags and Git URLs
are the expected installation path for non-development users.
