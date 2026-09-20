# Release Policy

DevLab is unpublished pre-1.0 software. It is intended to become a reusable CLI
and Python package, but its workflow formats and operator experience are still
evolving.

## Current Distribution

DevLab is not published to PyPI. Install it from a source checkout or Git URL
with `uv tool install`, as described in the README.

Before a public release, the project verifies package metadata, license
metadata, source distributions, wheels, and installation from a clean
environment.

## Versioning

DevLab uses semantic versioning.

While the version is `0.x`, minor releases may include breaking changes. Patch
releases should be bugfix-only and should not intentionally break the
representation written by that minor release.

After `1.0.0`, public compatibility surfaces follow normal semantic versioning:

- major versions may include breaking changes;
- minor versions add backward-compatible functionality; and
- patch versions fix bugs without changing documented behavior.

### Version source

The `[project].version` value in `pyproject.toml` is the single authoritative
DevLab package version. Use plain semantic versions there, such as `0.2.0`,
without a `v` prefix.

The CLI reads installed distribution metadata through `importlib.metadata`; it
does not duplicate the version in a Python module. Package versions are
independent from version fields in durable DevLab files. Values such as
`schema_version`, `layout_version`, and workflow `version` advance only when
their specific persisted representation changes.

### Choosing the next version

Choose the release version from the most significant user-facing change since
the previous release:

- increment the patch component for bug fixes that preserve documented
  behavior, for example `0.2.0` to `0.2.1`;
- increment the minor component for new capabilities or intentional breaking
  changes during `0.x`, for example `0.2.1` to `0.3.0`;
- release `1.0.0` only after the public compatibility contract is frozen and
  exercised by a release candidate; and
- after `1.0.0`, increment the major component for breaking changes.

Do not bump the package version for every development commit. Select and record
the version while preparing a release.

## Pre-1.0 Evolution

Until the 1.0 release-candidate freeze, the documented CLI, human and structured
output, executable configuration, and durable workspace formats are
provisional. Development commits and `0.x` releases do not promise backward
compatibility unless a release note explicitly says otherwise.

Breaking changes are allowed when they materially improve workflow correctness,
safety, maintainability, or operator clarity. They do not require compatibility
aliases, deprecation periods, reader-before-writer sequencing, or general
migration support. The change must update its implementation, tests,
documentation, and generated templates together. If preserving a known local
workspace is worthwhile, the change may include bounded migration or recovery
instructions, but that is a scoped development aid rather than a public
compatibility promise.

Examples include:

- renaming or removing CLI commands and options;
- changing structured output or provider configuration semantics;
- changing task, finding, milestone, workflow, or generation representations;
- changing when DevLab mutates or commits workflow state; and
- requiring a development workspace to be restored or regenerated.

DevLab exposes no supported Python library API before the freeze. Modules,
classes, functions, dataclasses, and constants under `devlab.*` are internal
implementation details.

## Format Safety

The absence of a backward-compatibility promise does not permit ambiguous or
unsafe mutation. Authoritative formats retain explicit version discriminators
where needed. A reader that encounters an unsupported version or malformed
control state must fail before mutation and identify the affected path and
condition. Reporting must not silently rewrite state. Closed session and safety
protocols reject unknown structure rather than guessing its meaning.

These checks protect current repository state and bounded-session identity; they
do not promise that the current reader accepts representations written by an
earlier development version. Tests therefore cover current-format behavior,
validation failures, and non-mutation rather than a frozen historical workspace
fixture.

## 1.0 Compatibility Freeze

The 1.x contract will be established during the 1.0 release-candidate phase,
after the operator model and durable formats have been exercised outside an
editable development checkout. That work must:

- name the public CLI, structured output, configuration, and durable-state
  surfaces;
- define additive evolution, deprecation, migration, and unsupported-state
  behavior;
- capture an independently authored immutable workspace baseline from the
  candidate rather than from an earlier development snapshot;
- add executable tests proving the candidate and later 1.x readers honor the
  contract; and
- update this policy before `1.0.0` is released.

No pre-1.0 fixture or development representation becomes part of that contract
merely because it was committed or carried a format version.

## Release Procedure

Until DevLab is published to PyPI, a release consists of an immutable Git tag
and GitHub Release containing the verified source distribution, wheel, and
checksums. The package version is `X.Y.Z`, while its Git tag is `vX.Y.Z`; for
example, package version `0.2.0` uses tag `v0.2.0`. The `v` distinguishes a
repository tag from the package version and is not part of the version recorded
in package metadata.

The GitHub Release is the canonical release note; a separate changelog is not
required. An annotated tag message can seed the draft release note, while a
lightweight tag uses the release commit message. In either case, review and
expand the draft with a concise summary of notable changes and any scoped
recovery guidance before publishing it.

1. Review changes since the previous release and choose the next version using
   the rules above.
2. Update `[project].version` in `pyproject.toml`.
3. Refresh `uv.lock` so the root package entry records the same version.
4. Draft a concise summary of notable changes and any scoped recovery guidance
   for the GitHub Release.
5. Run the complete development validation:

   ```bash
   make check
   ```

6. Run relevant scripted workflow evaluations and any live-agent baseline
   evaluations justified by the release risk.
7. Run the repository-owned release verification:

   ```bash
   make release-check
   ```

   The command builds the source distribution and wheel in a temporary
   directory; verifies project metadata, version agreement, license, project
   URLs, package resources, and the source/wheel content boundary; runs strict
   Twine checks through a pinned, isolated `uv tool run` invocation against both
   distributions so their metadata and long descriptions are suitable for a
   package index; installs the wheel in a clean temporary environment; and runs
   `devlab --version` and `devlab --help`. Twine remains outside DevLab's normal
   development and runtime dependency sets because its upload-oriented
   dependency tree is needed only for this release check. The command fails if
   the repository worktree changes. The wheel contains only the installed
   product. The source distribution additionally contains `Makefile`,
   `scripts/release_check.py`, `uv.lock`, and the product tests so the
   verification can be inspected and the unpacked release source can run the
   complete `make check`. Repository-only `demos/` content appears in neither
   artifact. Pass `--dist-dir PATH` directly to `scripts/release_check.py` to
   retain the exact verified artifacts and a `SHA256SUMS` file in an empty
   output directory.
8. Commit the release preparation. With that clean commit checked out, create
   a `vX.Y.Z` tag. A lightweight tag is sufficient:

   ```bash
   git tag vX.Y.Z
   ```

   To record the release note in Git as well as GitHub, use an annotated tag
   (`git tag -a vX.Y.Z`) and enter the note in the tag-message editor.
   Cryptographic tag signing is optional until the project adopts a signing
   policy; use `git tag -s vX.Y.Z` when signing.
9. Verify that the worktree is clean, the tag resolves to the checked-out
   commit, and installation from that commit succeeds. Push the release commit
   first and the specific tag second, only when the release is ready to share:

   ```bash
   git push origin main
   git push origin vX.Y.Z
   ```

   Never move or replace a shared release tag. Correct a released artifact with
   a new version and tag.
10. The tag push starts the `Prepare release` workflow. It verifies that the
    tag matches the package version and tagged commit, reruns the complete
    validation, then builds and verifies the release artifacts and generates
    checksums exactly once. A separate, least-privilege job downloads those
    verified artifacts and creates a draft GitHub Release from the annotated tag
    message or release commit message; it does not rebuild them. Add the drafted
    release summary, review the note and assets, mark a `0.x` release as a
    pre-release, and publish it deliberately. Published releases are immutable;
    a failed preparation is corrected with a new version and tag rather than by
    moving the shared tag.
11. Smoke-test installation through the shared tag and confirm the reported
    version:

    ```bash
    uv tool install --force "git+https://github.com/djulich/devlab.git@vX.Y.Z"
    devlab --version
    ```

Before considering the release complete:

- update README maturity guidance if evaluation confidence changed;
- retain the validation and evaluation results needed to support release
  claims; and
- ensure users can install by immutable tag rather than relying on `main`.

PyPI publication remains a future decision. Until then, release tags and Git
URLs are the expected installation path for non-development users.
