# Release Policy

DevLab is a pre-1.0 CLI distributed as a Python package. Its workflow formats
and operator experience are still evolving; the 1.x compatibility contract has
not been frozen.

## Current Distribution

Production PyPI is the supported package distribution channel. Install with
`uv tool install devlab`, as described in the [README](../README.md#install).
Pin a package version, or install from an immutable Git tag or commit, for a
reproducible installation. Source checkouts remain supported. TestPyPI is used
only to rehearse publication; it is not a supported distribution channel.

Before a public release, the project verifies package metadata, license
metadata, source distributions, wheels, and installation from a clean
environment.

## Versioning

DevLab uses semantic versioning.

While the version is `0.x`, minor releases may include breaking changes. Patch
releases are limited to bug fixes and documentation or package-metadata
corrections; they should not intentionally break the representation written by
that minor release.

After `1.0.0`, public compatibility surfaces follow normal semantic versioning:

- major versions may include breaking changes;
- minor versions add backward-compatible functionality; and
- patch versions fix bugs without changing documented behavior and may include
  documentation or package-metadata corrections.

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
  behavior, or documentation and package-metadata corrections that introduce no
  runtime or durable-format changes, for example `0.2.0` to `0.2.1`;
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

A release consists of an immutable Git tag, verified source distribution and
wheel on PyPI, and a GitHub Release containing the same distributions and their
checksums. The package version is `X.Y.Z`, while its Git tag is `vX.Y.Z`; for
example, package version `0.2.0` uses tag `v0.2.0`. The `v` distinguishes a
repository tag from the package version and is not part of the version recorded
in package metadata.

The GitHub Release is the canonical release note; a separate changelog is not
required. The package's `Release Notes` project URL points to the
[GitHub Releases page](https://github.com/djulich/devlab/releases) so users can
find these notes from PyPI. An annotated tag message can seed the draft release
note, while a lightweight tag uses the release commit message. In either case,
review and expand the draft with a concise summary of notable changes and any
scoped recovery guidance before publishing it.

The tag workflow builds once and publishes the verified distributions to
TestPyPI before production PyPI. Both publishing jobs use trusted publishing,
with job-scoped OIDC identity-token permission and attestations. They consume
the same build artifacts without rebuilding; `SHA256SUMS` remains a GitHub
Release asset and is not uploaded to either index.

TestPyPI remains part of every release to keep one consistent, exercised
publication path. Reconsider removing it if repeated releases show little
additional value and its approval or service dependency becomes a meaningful
burden.

Each index has its own trusted publisher for project `devlab`, GitHub repository
`djulich/devlab`, and workflow `release.yml`. The environment must match
`testpypi` or `pypi` respectively; no API token is stored in GitHub. Configure
the production `pypi` environment with required reviewer `djulich`, self-review
allowed, administrator bypass disabled, and a selected-tag rule for `v*`.
Environment protection rules are configured in GitHub settings, not in YAML.

Production publishing waits for the build, draft GitHub Release, and TestPyPI
upload to succeed, then requires environment approval. Inspect the candidate
before approving production. A `0.x` release remains provisional even when
distributed through production PyPI; publication does not freeze the 1.x
compatibility contract.

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
   URLs, absolute README links, package resources, and the source/wheel content
   boundary; runs strict
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
    checksums exactly once. Separate, least-privilege jobs consume the resulting
    artifacts without rebuilding: one creates a draft GitHub Release containing
    the distributions and checksums, while another publishes only the
    distributions to TestPyPI through trusted publishing. Approve the `testpypi`
    deployment in the workflow run's **Review deployments** dialog. The
    draft-release job checks out the tagged commit solely so GitHub CLI can resolve the repository
    and annotated tag notes; it still uses the artifacts from the build job.
    Confirm that TestPyPI shows the expected version, metadata, description,
    wheel, source distribution, and provenance. Open the description links and
    the Documentation and Release Notes sidebar links; rendering checks alone
    do not prove that destinations work. Add the drafted release summary, review
    the note and assets, and mark a `0.x` GitHub Release as a pre-release. This GitHub label
    does not change the package version or how PyPI installers select it.
11. Before approving production, smoke-test installation from TestPyPI and
    through the shared tag in separate temporary virtual environments, confirming
    the reported version and command help for each source. These POSIX-shell
    examples use an installed Python 3.12 and invoke the installed executables by
    absolute path; they do not replace the operator's normal DevLab tool. Replace
    `X.Y.Z` with the release version and run the block in one shell:

    ```bash
    release_smoke=$(mktemp -d /tmp/devlab-release-smoke.XXXXXX)

    uv venv --python 3.12 "$release_smoke/testpypi"
    uv pip install --python "$release_smoke/testpypi/bin/python" \
      --default-index https://test.pypi.org/simple/ \
      "devlab==X.Y.Z"
    "$release_smoke/testpypi/bin/devlab" --version
    "$release_smoke/testpypi/bin/devlab" --help

    uv venv --python 3.12 "$release_smoke/tag"
    uv pip install --python "$release_smoke/tag/bin/python" \
      "git+https://github.com/djulich/devlab.git@vX.Y.Z"
    "$release_smoke/tag/bin/devlab" --version
    "$release_smoke/tag/bin/devlab" --help
    ```

12. In **Actions → Prepare release → the release run → Review deployments**,
    select `pypi` and choose **Approve and deploy**. This uploads the same
    verified distributions to production PyPI. Approval starts publication;
    publishing the draft GitHub Release is a separate action.
13. Verify the production project description, links, version, files, and
    provenance. Compare the published distribution SHA-256 hashes with the
    GitHub Release's `SHA256SUMS`. Smoke-test the production installation in an
    isolated environment:

    ```bash
    production_smoke=$(mktemp -d /tmp/devlab-production-smoke.XXXXXX)
    uv venv --python 3.12 "$production_smoke/installed"
    uv pip install --python "$production_smoke/installed/bin/python" \
      --default-index https://pypi.org/simple/ "devlab==X.Y.Z"
    "$production_smoke/installed/bin/devlab" --version
    "$production_smoke/installed/bin/devlab" --help
    ```

    Publish the reviewed GitHub Release after these checks succeed. Uploaded
    files and shared tags are immutable. If a correction changes the artifacts,
    prepare a new version and tag; do not replace files or move the old tag.

Before considering the release complete:

- update README maturity guidance if evaluation confidence changed;
- retain the validation and evaluation results needed to support release
  claims; and
- ensure users can install the exact version from production PyPI and the
  immutable tag.
