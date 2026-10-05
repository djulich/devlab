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

## Commit Messages

Use Conventional Commits for changes to DevLab itself:

```text
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Choose the type from the primary purpose of the complete logical change. Use a
short description of the outcome and, when helpful, a scope naming the affected
area, such as `cli`, `recovery`, or `tasks`. Add a body or footers when the change
needs further explanation.

| Type | Use in DevLab | Example |
| --- | --- | --- |
| `feat` | Add a capability or extend observable behavior. | `feat(cli): wrap console prose to terminal width` |
| `fix` | Correct unintended or incorrect behavior. | `fix(recovery): reject discard after HEAD changes` |
| `perf` | Improve performance, supported by measurement. | `perf(status): reduce repeated workspace reads` |
| `refactor` | Improve internal structure while preserving observable behavior. | `refactor(tasks): simplify task selection logic` |
| `style` | Change source formatting without changing structure or behavior. | `style: apply Ruff formatting` |
| `test` | Add or improve tests, fixtures, or test assertions. | `test(recovery): cover interrupted discard failures` |
| `docs` | Change documentation, comments, or docstrings. | `docs: clarify prerequisite resolution guidance` |
| `build` | Change package builds, packaging, or runtime dependencies. | `build: include prompt resources in the wheel` |
| `ci` | Change CI workflows or their dependencies. | `ci: update pinned GitHub Actions` |
| `chore` | Maintain repository settings or development tools when no more specific type fits. | `chore: ignore local editor files` |
| `revert` | Undo a previous commit; identify its hash in the body. | `revert: undo terminal-width console formatting` |

Apply these boundaries when more than one type seems plausible:

- Tests and documentation accompanying a feature or fix share that change's
  type. Use `test` or `docs` when testing or documentation is the primary purpose.
- Observable output is behavior. Terminal formatting improvements can be `feat`
  or `fix`; `style` applies to source formatting.
- Error handling that corrects a crash or changes a result is `fix`, even if
  implemented by restructuring code or handling a previously unhandled `None`.
  Use `refactor` only when behavior stays the same.
- Classify file moves and dependency updates by purpose. Moving documentation
  is `docs`, reorganizing code without behavior changes is `refactor`, and
  changing package contents is `build`. Runtime dependency updates use
  `build(deps)`, GitHub Actions updates use `ci(deps)`, and routine development
  tool updates can use `chore(deps)`.
- Split unrelated purposes into separate commits. Use `chore` only when the
  change does not fit a more specific type.

These are DevLab's type-selection conventions. Consult the
[Conventional Commits reference](https://www.conventionalcommits.org)
for unclear format edge cases.

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
