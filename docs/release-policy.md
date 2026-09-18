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

## 1.x Compatibility Contract

This contract takes effect with `1.0.0`. A supported 1.x release must read and
continue target workspaces created by `1.0.0` and by every earlier 1.x release.
Historical 0.x workspaces are supported only when a release note or a retained
compatibility fixture names that representation explicitly. The minimum
supported representation is therefore the committed 1.0 compatibility fixture,
not every intermediate development format.

Compatibility means that read-only commands can inspect the workspace without
changing it and that eligible workflows can continue without regenerating valid
state. It does not guarantee identical prose, prompts, agent decisions, session
counts, timestamps, generated commit IDs, or provider output.

### CLI and structured output

The `devlab` console script, documented command names and options, their argument
meanings, and whether an operation is read-only or mutating are public 1.x
interfaces. Successful commands exit zero; validation, refusal, or execution
failure exits nonzero. Individual nonzero values are stable only when a command's
reference documentation assigns them a meaning.

Human-readable output is intended for operators. Headings and meaning remain
recognizable, but wording, whitespace, ordering, and added diagnostics are not a
machine interface. Automation should use the documented JSON modes for
`workflow-state`, `diagnostics`, and `history`. During 1.x, existing JSON fields
retain their meaning and value type; minor releases may add fields, and consumers
must ignore fields they do not understand. Removing or repurposing a field, or
changing its type, requires a major release.

Expert phase commands such as `plan` and `implement` remain supported, but
`continue` is the stable normal entry point. The derived next action may change
when a minor release adds a safer validation or recovery case, provided the
documented workflow invariants and stored state remain compatible.

### Configuration and executable behavior

The documented fields and semantics of `.devlab/config/agents.toml`, profile
files under `.devlab/config/profiles/`, and
`.devlab/config/test-services.toml` are public. Required fields remain required;
new optional fields may be added in a minor release. Unknown fields are not a
general extension mechanism: a reader may reject them where the parser protects
an executable or identity-bearing contract. Users must not depend on an
undocumented field being ignored.

Provider commands, profile lifecycle commands, prerequisites, and managed test
services are target-owned executable configuration. Their canonical
fingerprints, authorization boundary, prerequisite-attestation meaning, and
workspace-owned service identity remain compatible throughout 1.x. Adding a new
field that changes executed commands changes the fingerprint and requires fresh
operator authorization; that is a safety property, not a compatibility break.

### Durable workspace formats

Fields are classified as follows:

- **required** fields must be present with a valid type and value;
- **optional** fields may be absent and use the documented default;
- **extensible** formats may contain unknown fields, which a reader preserves or
  ignores as documented; and
- **versioned** formats carry `version`, `schema_version`, `layout_version`, or
  `schema`. A reader must not interpret an unsupported version as the current
  one.

The 1.x format families are:

| Format | Required/versioned core | Optional or extensible behavior |
| --- | --- | --- |
| `.devlab/manifest.toml` | `layout_version = 1` identifies the workspace layout. | Creation metadata may grow additively. An unsupported layout blocks workspace mutation. |
| `.devlab/workflow.toml` | `version = 1` and `[planning].complete` are required. | `[specs]` and `[resume]` are optional state sections. Unknown top-level or section fields are preserved when DevLab updates known state. |
| Task, finding, clarification, and research Markdown | Identity and state fields required by the owning tracker form the control contract; the prose body remains user/agent-authored evidence. | These unversioned front-matter formats are extensible. Tracker mutations preserve unknown front-matter fields. A future incompatible representation must add a version discriminator before 1.x stops accepting this form. |
| Milestone TOML | DevLab-written milestones carry `version = 1`; identity, status, and task membership are workflow control fields. | Optional integration, review, handoff, and finding fields have safe defaults. Unknown fields are preserved by milestone mutations. Missing `version` remains accepted for the 1.0 baseline representation. |
| Workflow events JSONL | Each recognized event requires `version = 1`, `type`, and `at`. | Additional scalar or scalar-list event data is extensible. Events are diagnostic history; they do not override authoritative workflow state. |
| Planning-generation manifests | `version = 1`, generation identity, archive time, and reason are required. | `spec_baseline` is optional for the initial representation. Unknown fields do not change the meaning of known fields. |
| Milestone verification | `schema_version = 1`, milestone identity, state, revision, and recorded command evidence form the verification record. | Later readers may add optional evidence, but must retain the meaning of existing fields. |
| Session metadata, handoffs, and archived submission evidence | Trusted envelopes and structured results use `schema_version = 1` and exact identity fields. | These are closed protocol records, not user extension points. Unknown or missing protocol fields are rejected; rendered Markdown may evolve without becoming a machine API. |
| Prerequisite blockers, attestations, executable-config trust, and managed-test-service records | Their schema/digest, target identity, and semantic fingerprint bind the record to the condition or executable configuration it authorizes. | These are closed safety records. A mismatch invalidates the record instead of being guessed or migrated silently. Operator-local records are not portable workspace state. |

Configuration reference documents and generated templates define the detailed
fields and allowed values. Tracker and workspace APIs remain the mutation
boundary; direct edits that violate required fields or enum values are
unsupported even when the underlying TOML or Markdown is syntactically valid.

Unknown versions of authoritative state must fail before mutation with the path,
found version, supported version, and an actionable upgrade, migration, or
restore instruction. Reporting must not silently rewrite old state. Append-only
diagnostic evidence may skip a malformed record when the report clearly remains
non-authoritative, but continuation may not infer workflow control state from it.

### Python package API

DevLab 1.x exposes no supported Python library API. The installed `devlab`
console script and packaged resources used by that command are public; modules,
classes, functions, dataclasses, and constants under `devlab.*` are internal
implementation details even when they can be imported. Tests and integrations
that import them must track DevLab internals. A future public Python API must be
named and documented explicitly and can then be added compatibly in a minor
release.

Packaged prompts are part of DevLab behavior, but their filenames, prose, and
exact assembled text are not stable APIs. Prompt changes still require review
because they affect generated workflow output. The semantic session contract is
enforced by the versioned envelope and result validation rather than prompt
wording.

### Deprecation and migration

An ordinary 1.x deprecation must remain functional for at least one later minor
release, emit an actionable warning where practical, and appear in release notes
with its replacement. Removal waits for the next major release. A security or
data-integrity defect may require immediate refusal, but the release must explain
the affected state and provide safe recovery guidance.

Format evolution follows reader-before-writer sequencing: release a reader that
accepts the old and new representation before DevLab begins writing the new one.
Additive optional fields do not require a schema-version increase. A change that
cannot be read without ambiguity requires a new format version and an explicit,
operator-invoked migration or regeneration procedure. DevLab does not silently
rewrite authoritative state merely because a newer package opened it.

Migration documentation must identify the source and destination versions,
preconditions, files changed, backup or Git recovery point, validation command,
and whether rollback is supported. Unsupported state must remain untouched and
produce repair guidance rather than best-effort mutation.

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
