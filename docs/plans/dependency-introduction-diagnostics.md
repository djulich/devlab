# Dependency Introduction Diagnostics

Status: implemented.

## Live calibration — 2026-08-20

The first React/Vite live run failed its independent browser correctness check,
but provided valid dependency-diagnostic evidence. The T0002 developer session
introduced `react`, `react-dom`, `vite`, and `@vitejs/plugin-react` in the direct
`package.json` dependency table. All four were attributed once to that session
and task. The planner, profile developer/reviewer, product reviewer, integrator,
and architecture-review sessions recorded no repeated introductions. The
generated `package-lock.json` and its transitive packages produced no entries.

This is positive evidence for Node attribution, direct-only scope, and
cross-session deduplication. A successful rerun is still required to compare
JSON diagnostics, verbose text diagnostics, and the final run summary while also
confirming that warnings remain advisory through ordinary successful workflow
and evaluation completion.

## Goal

Make direct dependencies introduced by an agent session visible to operators so
they can review package identity and provenance before relying on the generated
system. This is an advisory trust signal, not a package-legitimacy verdict.

## Contract

DevLab snapshots recognized direct dependencies immediately before each normal
software-workflow role invocation and compares them with the workspace after the
session. Newly observed dependency identities are stored in that session's
existing metadata with its role, task, provider, and model provenance.

`devlab diagnostics` aggregates these records and emits a quality warning for
each introduction. The structured run summary also places them under operator
attention. Reporting remains read-only and warnings do not change workflow
state, task status, validation, exit status, or milestone eligibility.

The initial manifest support is deliberately bounded:

- Python: PEP 621 dependencies, optional dependencies, dependency groups, and
  Poetry dependency tables in `pyproject.toml`;
- Node: direct dependency tables in `package.json`;
- Rust: ordinary, development, build, and target-specific direct dependency
  tables in `Cargo.toml`; and
- Go: direct `require` declarations in `go.mod`.

Lockfiles are excluded because most of their additions are transitive and would
produce noisy attribution. Constraint changes to an existing dependency are also
excluded from this first slice; the signal is specifically a newly introduced
dependency identity within a manifest scope. Unreadable or malformed manifests
are left to their owning validation tools rather than being treated as security
findings.

## Boundaries

DevLab does not query registries, install packages, run vulnerability scanners,
or claim that a dependency is safe. It does not turn warnings into tasks or
findings. Operators remain responsible for registry/source review and can use
target-owned verification commands or external policy systems where needed.

Clarification resolver and researcher sessions retain their stricter mutation
isolation and are not dependency-introduction sources. Historical sessions from
before this metadata field was introduced remain readable and simply contribute
no dependency records.

## Follow-up criteria

Add more manifest formats, constraint-change reporting, registry verification,
or blocking policy only after real usage demonstrates a distinct uncovered risk
and acceptable warning precision.
