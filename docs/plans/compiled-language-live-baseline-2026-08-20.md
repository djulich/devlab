# Compiled-Language Live Evaluation Baseline — 2026-08-20

Scenarios:

- `live-rust-cli-happy-path`
- `live-cpp-cmake-cli-happy-path`

Both scenarios were run at DevLab commit `26041b8` with role-specific local
agent configuration: Codex `gpt-5.5` for architecture, planning, development,
integration, and architecture review; Claude `opus` for task review. The local
configuration and provider credentials remain outside the repository.

## Outcome

Both evaluations passed their strict profile-verification contract. Each
workflow completed in eight sessions with this role sequence:

```text
architect, planner, developer, reviewer, developer, reviewer, integrator, architect
```

Each produced two closed tasks: a profile-bootstrap task under `default` and a
product task assigned to the dedicated language profile. Neither run had task
rework, findings, review rejections, contract warnings, quality warnings, or
unattributed developer/reviewer sessions. Each target had a clean worktree,
eight session commits, and a `devlab/milestone/M1` tag.

The profile-bootstrap task had `not_configured` developer verification because
the initial `default` profile intentionally had no validation commands. This is
expected. The product tasks inherited their dedicated profile defaults and
recorded passing developer verification. Milestone M1 was `verified` from the
same profile-sourced commands.

## Rust

- Dedicated profile: `rust`, assigned to product task `T0002`
- Developer and milestone commands: `cargo fmt --check`, `cargo test`
- Black-box checks: all 5 passed
- Generated Rust tests: 11 passed across unit and CLI integration suites
- Workflow: 8 sessions, 2 closed tasks, 0 rework or findings
- Git: clean, 8 session commits, M1 tag present

The successful rerun confirmed the fix in `26041b8`. An earlier product run had
copied explicit `validation = []` task boilerplate, suppressing the `rust`
profile even though agents ran Cargo manually. The safer template now omits task
validation so profile defaults are durable workflow evidence, and the live
grader requires that evidence.

## C++/CMake

- Dedicated profile: `cpp`, assigned to product task `T0002`
- Developer and milestone commands: `cmake --preset dev`, `cmake --build
  --preset dev`, `ctest --preset dev`
- Black-box checks: all 6 passed
- Generated CTest suite: 6 passed
- Workflow: 8 sessions, 2 closed tasks, 0 rework or findings
- Git: clean, 8 session commits, M1 tag present

The evaluator also exercised successful signed multiplication plus invalid
command, arity, integer, and overflow boundaries independently of the target's
workflow roles.

## Implications and follow-up

The runs provide positive end-to-end evidence for dedicated compiled-language
profiles, inherited validation, durable developer/milestone records, external
black-box grading, and operator-owned toolchain prerequisites. Equivalent opt-in
Go and C scenarios are the next profile-coverage step; they should remain small
and parallel rather than introduce language-specific orchestration.

Rust `target/` and CMake `build/` were classified as “other ignored” artifacts
rather than conventional toolchain output. The C++ footprint was 355,629 bytes
and produced no warning; the Rust footprint was about 43.6 MB and remained below
the current warning threshold. Treat this as supporting hygiene evidence, not a
correctness failure.

Persistent diagnostics were not copied outside the pytest temporary targets.
Future live runs can set `DEVLAB_EVAL_RESULTS_DIR` when durable raw diagnostics
are useful.
