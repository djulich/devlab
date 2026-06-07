# DevLab Project Makefile

## Goal

Add a small repository-level `Makefile` that improves DevLab source-checkout contributor experience without becoming a second build system or encoding target-project workflow policy.

The Makefile is for the DevLab source repository itself. It should help people install, validate, and optionally remove the local `devlab` tool. Target repositories should still invoke the installed `devlab` command directly.

## Scope

Implement a root `Makefile` with documented, low-surprise targets:

- `help`: list available targets and their purpose.
- `sync`: run `uv sync` for local development dependencies.
- `check`: run the standard validation suite used by agents and contributors:
  - `uv run ruff check`
  - `uv run ty check`
  - `uv run pytest -q`
- `test`: run `uv run pytest` or `uv run pytest -q`; choose one and document it.
- `install`: install DevLab as a regular uv tool from the checkout via `uv tool install .`.
- `install-editable`: install DevLab as an editable uv tool via `uv tool install --editable .`.
- `reinstall` or `reinstall-editable`: force-refresh an existing tool install if `uv tool install` requires explicit replacement in practice.
- `uninstall`: run `uv tool uninstall devlab`.

## Shell completion

Do not make shell completion part of the initial Makefile unless DevLab first has an explicit completion-generation command such as `devlab completion bash`.

Once completion generation exists, add separate opt-in targets rather than writing shell configuration during ordinary install:

- `install-completion-bash`: write Bash completion to the user-level completion directory when supported.
- `install-all`: install the tool plus completion.

This keeps normal installation predictable while still making enhanced shell UX easy.

## Non-goals

- Do not replace `uv` project metadata or package configuration.
- Do not add target-project workflow commands such as `make devlab-run`; users should run `devlab run` inside target repositories.
- Do not require root privileges or write to system directories.
- Do not install agent CLIs, deployment tools, or other host prerequisites.
- Do not make live-agent evaluations part of the default `check` target; they are opt-in and token/provider dependent.

## Documentation updates

Update `README.md` to mention the Makefile as a convenience for source checkouts, while keeping direct `uv tool install ...` commands as the canonical installation mechanism.

Suggested examples:

```bash
make install
make install-editable
make check
```

## Validation

After adding the Makefile:

```bash
make check
make install-editable
devlab --help
make uninstall
```
