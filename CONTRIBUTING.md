# Contributing to DevLab

DevLab is pre-1.0 software. Contributions are welcome, but changes
should strengthen the existing workflow before expanding its feature surface.
Its CLI and durable formats remain provisional until the 1.0 release-candidate
freeze.

## Before You Start

- Use a GitHub issue to discuss substantial behavior or durable-format changes
  before implementation.
- Report security problems privately as described in [SECURITY.md](SECURITY.md).
- Read [AGENTS.md](AGENTS.md) for the repository's architecture, ownership
  boundaries, and coding standards. These constraints apply to human- and
  agent-authored changes alike.

## Development Setup

DevLab requires Python 3.12 or newer, Git, and
[`uv`](https://docs.astral.sh/uv/). From a clone:

```bash
make setup
```

This synchronizes the locked development environment and installs the
repository-managed Git hooks. To run DevLab from the checkout without installing
it globally:

```bash
uv run devlab --help
```

To make the `devlab` command available from other target workspaces while
developing DevLab, install the checkout as an editable tool:

```bash
uv tool install --editable .
# or: make install-editable
```

Code changes in the checkout are then reflected in the installed command.

## Making Changes

- Keep workflow policy in the owning module rather than in packaged prompts.
- Preserve the provider, tracker, workspace, and orchestration boundaries in
  `AGENTS.md`.
- Add focused tests for behavior changes, especially file formats, state
  transitions, validation failures, and CLI output.
- Update current documentation when observable behavior changes. Put durable
  trade-off decisions in `docs/adr/`, not in implementation notes.
- Do not commit target-workspace logs, retained prompts, credentials, local
  configuration, or agent-session transcripts.

Run the complete validation before submitting a pull request:

```bash
make check
```

The check includes formatting, linting, type checking, and the full test suite.
If the change affects a repository demonstration, also run:

```bash
make -C demos check
```

## GitHub Actions Dependencies

Reference every external GitHub Action by its full-length commit SHA and put the
corresponding exact release tag in a same-line comment. This keeps workflow code
immutable while preserving a human-readable version, for example:

```yaml
uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0
```

Dependabot checks GitHub Actions dependencies monthly and proposes updated SHAs
and version comments through pull requests. Review the upstream release notes
and workflow diff, then require the normal validation and owner approval; do not
auto-merge these updates. Apply security and runner-compatibility updates
promptly. Treat major-version updates as deliberate maintenance because action
inputs, defaults, or runtime behavior may change.

## Pull Requests

Describe the user-visible outcome, important design choices, and validation you
ran. Call out durable-state replacement or migration effects when relevant.
Keep each pull request focused enough that its workflow and state implications
can be reviewed as one coherent change.

Contributions are accepted under the repository's Apache License 2.0.
