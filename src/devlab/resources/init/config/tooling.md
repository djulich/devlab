# Tooling Policy

## Coding Standards

- Prefer readable, explicit code over cleverness.
- Preserve separation of concerns: put behavior in the owning module/abstraction and avoid leaking storage formats, external service details, environment assumptions, or workflow rules into unrelated code.
- Add focused tests for behavior changes.
- Add comments/docstrings only when they clarify purpose, contracts, invariants, or design tradeoffs.
- Include a `README.md` with a project overview, installation instructions, and a first-usage example. Create it as part of the project scaffold; keep it current as features are added.

## Project Toolchain

Preserve established build, dependency, formatting, analysis, and test conventions
when adopting an existing repository. For a greenfield project, make the language
and toolchain explicit in the design and add a reusable profile before product
tasks depend on it.

Prefer checked-in, workspace-root validation entry points where practical. Keep
generated dependencies, build products, caches, and editor artifacts out of Git.

DevLab does not install compilers, SDKs, package managers, build systems, or
analyzers. Document required host tools and report unavailable checks as
unverified prerequisites.

Declare reusable external conditions as profile `[[prerequisites]]`, scoped to
the `session`, `setup`, or `validation` operation that consumes them. Automatic
checks must be fast and non-mutating. Use operator attestations only for
authority or conditions that cannot be checked safely. Add a detailed guide
under `.devlab/config/prerequisites/` when resolving the condition requires more
than a concise summary. Never put credentials in profiles, guides, attestations,
or Git.
